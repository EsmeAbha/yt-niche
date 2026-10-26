"""FFmpeg assembly: scene clips + voiceover -> captioned, music-bedded final video."""
from __future__ import annotations

import json
import random
import re
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def run(cmd: list[str], cwd: Path | None = None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + " ".join(cmd) + "\n" + p.stderr[-2000:])
    return p


def probe(path: Path) -> dict:
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", str(path)])
    d = json.loads(p.stdout)
    return {"duration": float(d.get("format", {}).get("duration", 0) or 0),
            "has_audio": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}


def font(cfg: dict, size: int):
    for f in [cfg.get("video", {}).get("font_file"), "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        if not f:
            continue
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def placeholder_clip(cfg: dict, text: str, seconds: float, w: int, h: int, out: Path) -> Path:
    """Stand-in shot when no GPU/Flow clip exists, so the whole pipeline can be tested end to end."""
    img = Image.new("RGB", (w, h), random.choice([(40, 44, 52), (60, 36, 30), (28, 52, 48), (52, 40, 64)]))
    d = ImageDraw.Draw(img)
    f = font(cfg, max(w // 22, 18))
    body = "\n".join(textwrap.wrap("PLACEHOLDER SHOT\n\n" + text, width=26))[:700]
    d.multiline_text((w // 12, h // 3), body, fill=(235, 235, 230), font=f, spacing=10)
    png = out.with_suffix(".png")
    img.save(png)
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-t", f"{seconds:.2f}", "-r", "30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", str(out)])
    return out


def frames_to_clip(frames: Path, fps: int, out: Path) -> Path:
    ext = next(frames.iterdir()).suffix
    run(["ffmpeg", "-y", "-framerate", str(fps), "-i", str(frames / f"%05d{ext}"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", str(out)])
    return out


def build_scene(clip: Path, vo: Path | None, duration: float, w: int, h: int, fps: int,
                keep_clip_audio: bool, out: Path) -> Path:
    info = probe(clip)
    cd = info["duration"] or duration
    slow = min(duration / cd, 1.5) if cd < duration else 1.0  # gentle slow-mo before freezing
    v = (f"[0:v]setpts={slow:.4f}*PTS,scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
         f"fps={fps},setsar=1,tpad=stop_mode=clone:stop_duration={duration:.2f},"
         f"trim=duration={duration:.2f},setpts=PTS-STARTPTS[v]")
    inputs = ["-i", str(clip)]
    a_parts = []
    if vo:
        inputs += ["-i", str(vo)]
        a_parts.append("[1:a]aresample=48000,aformat=channel_layouts=stereo,apad[vo]")
    if keep_clip_audio and info["has_audio"]:
        a_parts.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo,volume={0.35 if vo else 1.0},apad[ca]")
    if vo and keep_clip_audio and info["has_audio"]:
        a_parts.append(f"[vo][ca]amix=inputs=2:duration=longest:normalize=0,atrim=0:{duration:.2f}[a]")
    elif vo:
        a_parts.append(f"[vo]atrim=0:{duration:.2f}[a]")
    elif keep_clip_audio and info["has_audio"]:
        a_parts.append(f"[ca]atrim=0:{duration:.2f}[a]")
    else:
        inputs += ["-f", "lavfi", "-t", f"{duration:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        a_parts.append(f"[{1 if not vo else 2}:a]acopy[a]")
    fc = ";".join([v] + a_parts)
    run(["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
         "-t", f"{duration:.2f}", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])
    return out


def _ts(t: float) -> str:
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_ass(cfg: dict, scenes: list[dict], w: int, h: int, out: Path) -> Path:
    """Big word-chunk captions (bottom-middle) + hook/on-screen text (top)."""
    vc = cfg.get("video", {})
    fontname = vc.get("caption_font", "Arial")
    vertical = h > w
    cap_size = int(h * (0.052 if vertical else 0.06))
    top_size = int(h * (0.045 if vertical else 0.055))
    margin_v = int(h * (0.28 if vertical else 0.08))
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{fontname},{cap_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{max(cap_size // 9, 3)},2,2,60,60,{margin_v},1
Style: Top,{fontname},{top_size},&H0000E6FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{max(top_size // 9, 3)},2,8,60,60,{int(h * 0.09)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    words_per = vc.get("caption_words", 3)
    for s in scenes:
        t0, dur = s["_start"], s["_duration"]
        speech = min(s.get("_speech") or dur, dur)
        if vc.get("captions", True) and s.get("voiceover"):
            words = s["voiceover"].split()
            chunks = [" ".join(words[i:i + words_per]) for i in range(0, len(words), words_per)]
            total_chars = sum(len(c) for c in chunks) or 1
            t = t0
            for c in chunks:
                d = speech * len(c) / total_chars
                text = c.upper() if vc.get("caption_uppercase", True) else c
                lines.append(f"Dialogue: 0,{_ts(t)},{_ts(t + d)},Cap,,0,0,0,,{_ass_escape(text)}")
                t += d
        if s.get("on_screen_text"):
            lines.append(f"Dialogue: 1,{_ts(t0)},{_ts(t0 + dur)},Top,,0,0,0,,{_ass_escape(s['on_screen_text'])}")
    out.write_text(hdr + "\n".join(lines) + "\n", encoding="utf-8")
    return out


def _ass_escape(t: str) -> str:
    return re.sub(r"[{}]", "", t).replace("\n", "\\N")


def final_render(cfg: dict, project: Path, scene_files: list[Path], ass: Path | None, out: Path,
                 music: Path | None = None) -> Path:
    listing = project / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in scene_files), encoding="utf-8")
    inputs = ["-f", "concat", "-safe", "0", "-i", listing.name]
    vf = f"[0:v]ass={ass.name}[v]" if ass else "[0:v]null[v]"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music.resolve())]
        vol = cfg.get("video", {}).get("music_volume", 0.12)
        af = (f"[1:a]volume={vol},aresample=48000[m];[m][0:a]sidechaincompress=threshold=0.05:ratio=6:"
              f"attack=20:release=300[duck];[0:a][duck]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        af = "[0:a]anull[a]"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "19", "-preset", cfg.get("video", {}).get("x264_preset", "veryfast"),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest",
         str(out.resolve())], cwd=project)
    return out


def make_thumbnail(cfg: dict, video: Path, text: str, out: Path, at: float = 1.5) -> Path:
    frame = out.with_name("thumb_frame.png")
    run(["ffmpeg", "-y", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-vf",
         "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720", str(frame)])
    img = Image.open(frame).convert("RGB")
    if text:
        d = ImageDraw.Draw(img)
        f = font(cfg, 120)
        lines = textwrap.wrap(text.upper(), 14)[:2]
        y = 720 - 80 - 130 * len(lines)
        for ln in lines:
            d.text((60, y), ln, font=f, fill=(255, 230, 0), stroke_width=10, stroke_fill=(0, 0, 0))
            y += 130
    img.save(out, quality=92)
    return out
