"""Stage 5: one idea -> finished video file.

Shot sources, in priority order for each scene:
  1. flow_inbox/shot_XX.mp4  - a clip you made in Google Flow (Veo) and dropped in the folder
  2. ComfyUI on your GPU     - workflows/t2v_api.json
  3. placeholder card        - only if video.fallback_placeholder is true (for testing)

Hero scenes are listed in flow_prompts.md so you can make them in Flow by hand. Google AI Pro has
no API, so this is the one manual step; everything else runs unattended.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from . import assemble
from .comfy import Comfy, ComfyError
from .llm import unload_ollama
from .tts import synthesize

VID_EXT = (".mp4", ".mov", ".webm", ".mkv")


def project_dir(niche_path: Path, idea: dict) -> Path:
    slug = "".join(c if c.isalnum() else "-" for c in idea.get("title", "video").lower())[:50].strip("-")
    d = niche_path / "projects" / f"{idea.get('id', 0):02d}-{slug}"
    for sub in ("shots", "flow_inbox", "audio", "scenes"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def dims(cfg: dict, idea: dict) -> tuple[int, int, int]:
    vc = cfg.get("video", {})
    vertical = idea.get("format", "short") == "short"
    w, h = (vc.get("short_size", [1080, 1920]) if vertical else vc.get("long_size", [1920, 1080]))
    return int(w), int(h), int(vc.get("fps", 30))


def write_flow_prompts(cfg: dict, idea: dict, proj: Path) -> Path:
    vertical = idea.get("format", "short") == "short"
    lines = [f"# Flow / Veo shots for: {idea.get('title')}", "",
             "Make each shot in Google Flow, download it, and save it in this project's `flow_inbox/` "
             "folder with the exact file name shown. Then run `niche make` again; your clips replace the local renders.",
             f"Aspect ratio: **{'9:16' if vertical else '16:9'}**", ""]
    style = cfg.get("video", {}).get("style_suffix", "")
    for s in idea.get("scenes", []):
        if not s.get("hero"):
            continue
        lines += [f"## shot_{s['n']:02d}.mp4  ({s.get('seconds', 5)} s)",
                  "```", f"{s.get('visual_prompt', '')}. Camera: {s.get('camera', '')}. {style}".strip(), "```",
                  f"Sound idea: {s.get('sfx', '') or '-'}  |  Line: {s.get('voiceover', '') or '-'}", ""]
    p = proj / "flow_prompts.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _inbox_clip(proj: Path, n: int) -> Path | None:
    for ext in VID_EXT:
        p = proj / "flow_inbox" / f"shot_{n:02d}{ext}"
        if p.exists():
            return p
    return None


def produce(cfg: dict, niche_path: Path, idea: dict, log=print, render_local: bool = True) -> Path:
    vc = cfg.get("video", {})
    proj = project_dir(niche_path, idea)
    (proj / "idea.json").write_text(json.dumps(idea, ensure_ascii=False, indent=1), encoding="utf-8")
    write_flow_prompts(cfg, idea, proj)
    w, h, fps = dims(cfg, idea)
    scenes = idea.get("scenes", [])
    log(f"[{idea.get('id')}] {idea.get('title')}  ({len(scenes)} scenes, {w}x{h})")

    # 1) voiceover first: it decides how long each scene lasts
    for s in scenes:
        # Your own recording wins over TTS: drop audio/my_vo_01.m4a etc. A real voice is the single
        # biggest "human contribution" signal for YPP reviewers, and it retains viewers better.
        mine = next((p for ext in (".wav", ".mp3", ".m4a", ".ogg") if (p := proj / "audio" / f"my_vo_{s['n']:02d}{ext}").exists()), None)
        vo = mine or synthesize(cfg, s.get("voiceover", ""), proj / "audio" / f"vo_{s['n']:02d}", voice=idea.get("voice"))
        s["_vo"] = str(vo) if vo else None
        speech = assemble.probe(vo)["duration"] if vo else 0
        s["_speech"] = speech
        s["_duration"] = round(max(float(s.get("seconds", 5)), speech + 0.25), 2)

    # 2) shots
    comfy = Comfy(vc.get("comfy_url", "http://127.0.0.1:8188"), cfg["_root"] / vc.get("comfy_workflow", "workflows/t2v_api.json"))
    use_comfy = render_local and comfy.available()
    if render_local and not use_comfy:
        log("  ComfyUI not reachable or workflow missing -> " +
            ("placeholder shots" if vc.get("fallback_placeholder", True) else "skipping missing shots"))
    if use_comfy:
        unload_ollama(cfg)
    style = vc.get("style_suffix", "")
    neg = vc.get("negative_prompt", "")
    seed = random.randint(1, 2**31 - 1) if vc.get("same_seed_per_video", True) else None
    # Character reference image -> image-to-video keeps your character identical across shots and videos.
    ref = cfg.get("channel", {}).get("character_image")
    ref = (cfg["_root"] / ref) if ref and not Path(ref).is_absolute() else (Path(ref) if ref else None)
    ref = ref if ref and ref.exists() else None
    for s in scenes:
        n = s["n"]
        clip = _inbox_clip(proj, n)
        existing = sorted((proj / "shots").glob(f"shot_{n:02d}.*"))
        if clip:
            log(f"  shot {n}: Flow clip")
        elif existing and existing[0].suffix in VID_EXT and not s.get("_rerender"):
            clip = existing[0]
            log(f"  shot {n}: cached local render")
        elif use_comfy:
            frames = min(int(s["_duration"] * vc.get("model_fps", 24)) // 4 * 4 + 1, vc.get("max_frames", 121))
            rw, rh = vc.get("render_size_short", [704, 1280]) if h > w else vc.get("render_size_long", [1280, 704])
            prompt = f"{s.get('visual_prompt', '')}, {s.get('camera', '')}, {style}".strip(", ")
            log(f"  shot {n}: rendering on GPU ({frames} frames @ {rw}x{rh})...")
            try:
                clip = comfy.render(prompt, proj / "shots" / f"shot_{n:02d}", rw, rh, frames, neg, seed, image=ref)
                if clip.is_dir():
                    clip = assemble.frames_to_clip(clip, vc.get("model_fps", 24), proj / "shots" / f"shot_{n:02d}.mp4")
            except ComfyError as e:
                log(f"  shot {n}: ComfyUI failed: {e}")
                clip = None
        if clip is None and vc.get("fallback_placeholder", True):
            clip = assemble.placeholder_clip(cfg, s.get("visual_prompt", ""), s["_duration"], w // 2, h // 2,
                                             proj / "shots" / f"shot_{n:02d}_placeholder.mp4")
        if clip is None:
            raise RuntimeError(f"No clip for scene {n}. Add flow_inbox/shot_{n:02d}.mp4 or start ComfyUI.")
        s["_clip"] = str(clip)
    if use_comfy:
        comfy.free_memory()

    # 3) per-scene encode, captions, final mix
    t = 0.0
    scene_files = []
    for s in scenes:
        s["_start"] = t
        keep = vc.get("keep_clip_audio", True) and _inbox_clip(proj, s["n"]) is not None
        out = assemble.build_scene(Path(s["_clip"]), Path(s["_vo"]) if s["_vo"] else None, s["_duration"],
                                   w, h, fps, keep, proj / "scenes" / f"scene_{s['n']:02d}.mp4")
        scene_files.append(out)
        t += s["_duration"]
    ass = assemble.write_ass(cfg, scenes, w, h, proj / "captions.ass")
    music = _pick_music(cfg)
    final = assemble.final_render(cfg, proj, scene_files, ass, proj / "final.mp4", music)
    if idea.get("format") == "long":
        hero = next((s for s in scenes if s.get("hero")), scenes[0])
        assemble.make_thumbnail(cfg, final, idea.get("thumbnail_text", ""), proj / "thumbnail.jpg",
                                at=hero["_start"] + min(1.5, hero["_duration"] / 2))
    (proj / "render_log.json").write_text(json.dumps(scenes, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  done: {final}  ({t:.1f}s)")
    return final


def _pick_music(cfg: dict) -> Path | None:
    d = cfg.get("video", {}).get("music_dir")
    if not d:
        return None
    p = Path(d) if Path(d).is_absolute() else cfg["_root"] / d
    tracks = [f for f in p.glob("*") if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")] if p.exists() else []
    return random.choice(tracks) if tracks else None
