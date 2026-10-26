"""Video plan -> prompts for Google Veo (Google AI Pro: Gemini app / Flow).

Veo 3.1 makes one clip of at most 8 seconds per prompt, 16:9 or 9:16, with its own audio (speech, singing,
effects, music). So a video is planned as clips of at most 8 s. Each clip prompt is one flowing description
(Veo follows prose better than long labelled lists), stands on its own, repeats the characters' look word for
word, puts spoken or sung words in quotes, and keeps "no text" short (long avoid-lists can backfire).
The "complete prompt" is the whole creative spec in one block; for a video of 8 s or less, clip 1 is the video.

Kids songs (nursery rhymes, colors, ABC, numbers) get their own mode: an ORIGINAL song with simple repetitive
lyrics, a chorus, one teaching item per verse, and each clip singing its own lines.
"""
from __future__ import annotations

import json
import re

from .llm import chat_json

CLIP_MAX_S = 8

STYLES = {
    "Auto": "",
    "Kids 3D cartoon": "bright cheerful 3D cartoon for toddlers, round soft characters with big shiny eyes, saturated "
                       "primary colors, clean simple backgrounds, soft lighting, bouncy friendly motion",
    "Kids 2D cartoon": "colorful flat 2D cartoon for toddlers, thick clean outlines, simple shapes, bright pastel "
                       "background, smooth bouncy animation",
    "Cinematic": "cinematic film look, anamorphic lens, dramatic lighting, shallow depth of field, film grain",
    "Realistic": "photorealistic, natural light, handheld real-camera footage, true-to-life colors",
    "Documentary": "documentary style, natural light, observational camera, grounded and authentic",
    "Hyperrealistic": "hyperrealistic, ultra-detailed textures, physically accurate light",
    "3D animation": "high-end 3D animation, Pixar-like characters, soft global illumination",
    "Anime": "anime style, clean cel shading, vibrant colors, expressive motion",
    "Satisfying": "macro close-ups, clean surfaces, smooth continuous motion, crisp tactile sounds",
    "Surreal": "surreal dreamlike imagery, impossible scale, soft volumetric light",
}
VOICES = ["Auto", "Song", "Narration", "Dialogue", "None"]
KIDS = re.compile(r"\b(kids?|child(ren)?|toddlers?|bab(y|ies)|nursery|rhymes?|preschool|abc|alphabets?|"
                  r"colou?rs?|numbers?|counting|baby shark|chu ?chu|cocomelon|lullaby|phonics)\b", re.I)

BASE_NEGATIVE = ["unnatural or jerky movement", "characters changing appearance between shots", "distorted objects",
                 "flickering", "visual artifacts", "extra or missing limbs and fingers", "inconsistent lighting",
                 "on-screen text or subtitles", "watermarks", "logos"]

PLAN_SCHEMA = """{
 "title": "...", "alt_titles": ["...", "..."],
 "objective": "what the video is about and what it should achieve",
 "target_audience": "...", "emotion": "the feeling viewers should leave with",
 "style": "visual style in under 12 words", "platform": "YouTube Shorts / Facebook Reels / YouTube",
 "hook": "exactly what is seen and heard in the first 2 seconds",
 "structure": {"beginning": "...", "middle": "...", "ending": "..."},
 "retention_plan": ["what keeps people watching at each point"],
 "characters": [{"name": "...", "look": "exact appearance: species/body, size, colors, face, eyes, hair/fur, clothes, material/texture; one sentence reused word for word"}],
 "props": [{"name": "...", "look": "exact appearance of each object that appears: shape, size, color, material, texture, any face or detail"}],
 "settings": [{"name": "...", "look": "the place in layers: foreground, midground, far background, sky/walls, ground, plants/furniture, color palette"}],
 "color_grade": "...", "continuity": ["rules that keep scenes consistent"],
 "voice": {"use": "song | narration | dialogue | none",
           "character": "who speaks/sings: age, gender, timbre, pitch, accent, energy, e.g. bright 6-year-old girl, high clear pitch, neutral American accent",
           "delivery": "pace, emotion, articulation, e.g. slow, smiling, every word clearly pronounced for toddlers",
           "quality": "recording quality, e.g. clean close-mic studio vocal, in tune, no echo, no background noise"},
 "music": {"mood": "...", "genre": "...", "tempo_bpm": 100, "instruments": "...", "search_terms": "for the YouTube Audio Library"},
 "audio_mix": "how voice, music and effects sit together, e.g. vocals clear on top, music softly under, effects light",
 "render_quality": "visual finish, e.g. high-end 3D render, soft global illumination, smooth surfaces, crisp 4K detail, fluid 24fps motion",
 SONG_FIELD
 "scenes": [
  {"n": 1, "seconds": 6, "purpose": "hook / build / reveal / payoff ...",
   "environment": "setting name", "background": "what is behind and around the action in this shot: foreground, midground, far background, colors",
   "props": ["names of props visible in this shot"], "subject": "who/what is in the shot", "action": "what happens, beat by beat",
   "camera": "angle and movement", "lighting": "...", "mood": "...", "transition": "into the next scene",
   SCENE_AUDIO
   "sound_effects": "...", "on_screen_text": "text added in editing, or empty", "key_details": "small details that sell the shot"}
 ],
 "negative": ["things to avoid that are specific to this video"],
 "final_scene": "why the ending is satisfying and memorable",
 "assets": [{"type": "image | audio | music | sfx | font | prop", "what": "...", "how": "where to get or make it"}],
 "thumbnail": {"text": "max 4 words", "prompt": "image prompt"},
 "youtube": {"title": "...", "description": "...", "hashtags": ["#..."]},
 "facebook_caption": "..."
}"""
SONG_FIELD = ('"song": {"title": "...", "bpm": 115, "key": "C major", "instruments": "ukulele, xylophone, claps ...", '
              '"vocal": "e.g. cheerful young child voice with a warm adult female voice", '
              '"lyrics": "the WHOLE song with [Verse 1] / [Chorus] labels, one line per line"},')
SPEECH_AUDIO = ('"narration": "exact words, or empty", "dialogue": "Speaker: exact line, or empty", '
                '"music": "what the music does here",')
SONG_AUDIO = '"lyrics": "the exact 3-4 short lines sung in this clip (its verse + the chorus hook)", "dance": "the simple move or gesture",'

SYSTEM = ("You are a film director and video strategist who writes production plans for Google Veo 3.1. Veo makes one "
          "clip of at most 8 seconds per prompt, with its own audio (speech, singing, music, effects), and it sees only "
          "that clip's prompt. Plans are specific to the idea, never generic. Visuals are consistent between scenes and "
          "contain no written text. JSON only.")

SONG_RULES = """
THIS IS A CHILDREN'S SONG VIDEO (the genre of Baby Shark, ChuChu TV, CoComelon, Super Simple Songs).
- Write an ORIGINAL song: new lyrics and melody. Never copy or closely imitate an existing song's lyrics or tune.
- Lyrics a 2-5 year old can sing: short lines of 3-7 words, simple rhymes, lots of repetition, a catchy chorus with
  a sound hook (like "doo doo doo", "la la la", "yay!") repeated at least 3 times.
- Teach one thing per verse (a color, letter, number, animal or habit) paired with a familiar object a toddler knows
  (red apple, yellow sun, A is for apple). Add simple actions kids copy: clap, jump, wave, spin.
- Tempo 100-130 bpm, major key, bright instruments. Each clip sings 3-4 short lines: its verse, then the chorus
  hook, so every clip is catchy on its own. Together the clips sing the whole song once, start to finish.
- on_screen_text is the big word, letter or number being taught in that scene (added in editing).
- Characters are cute, friendly, original (no famous characters). Same characters in every scene.
- Safe and gentle: no scary moments, no danger, nothing a parent would object to.
"""


def is_kids(text: str) -> bool:
    return bool(KIDS.search(text or ""))


def write_plan(cfg: dict, idea: str, style: str = "Auto", aspect: str = "9:16", length_s: int = 30,
               language: str = "English", voice: str = "Auto", extra: str = "", context: dict | None = None) -> dict:
    song = voice == "Song" or (voice == "Auto" and is_kids(idea + " " + extra))
    if song and style == "Auto":
        style = "Kids 3D cartoon"
    n_min = max(1, -(-length_s // CLIP_MAX_S))
    style_rule = (f"Visual style: {style} ({STYLES[style]})." if STYLES.get(style)
                  else "Choose the visual style that fits the idea best.")
    voice_rule = (SONG_RULES if song else
                  {"Auto": "Use narration or dialogue only if the idea needs it; satisfying/visual ideas often need none.",
                   "Narration": "Use a narrator.", "Dialogue": "Characters speak short lines.",
                   "None": "No narration or dialogue; sound effects, ambience and music only."}.get(voice, ""))
    schema = (PLAN_SCHEMA.replace("SONG_FIELD", SONG_FIELD if song else "")
              .replace("SCENE_AUDIO", SONG_AUDIO if song else SPEECH_AUDIO))
    user = (f"IDEA: {idea}\n"
            + (f"\nRESEARCH AND ANALYSIS TO BUILD ON (use what works, keep the idea original; do not copy):\n"
               f"{json.dumps(context, ensure_ascii=False)[:7000]}\n" if context else "") +
            f"\nFORMAT: {aspect} ({'vertical, for Shorts/Reels' if aspect == '9:16' else 'horizontal'}), "
            f"about {length_s} seconds in total.\n{style_rule}\nLanguage for all spoken/sung words, text and titles: {language}.\n"
            f"Voice: {voice_rule}\n" + (f"Creator's requirements: {extra}\n" if extra else "") +
            f"\nRULES\n- At least {n_min} scenes; every scene 4-{CLIP_MAX_S} seconds (one Veo clip each); seconds add up to "
            f"about {length_s}.\n- The first 2 seconds grab attention: a striking visual or sound, no slow intro.\n"
            "- Each scene changes something (new item, action, reveal, angle) so attention never drops.\n"
            "- Words must fit the scene length (about 2.5 spoken words per second; fewer when sung).\n"
            "- Describe each character in one exact sentence and reuse it word for word.\n"
            "- End on a satisfying payoff, loop or happy finish.\n"
            f"\nReturn JSON in exactly this shape:\n{schema}")
    plan = chat_json(cfg, SYSTEM, user, 0.7)
    if not isinstance(plan, dict) or not plan.get("scenes"):
        raise ValueError("The writer returned an incomplete plan. Try again.")
    for i, s in enumerate(plan["scenes"], 1):
        s["n"] = i
        s["seconds"] = min(float(s.get("seconds") or 5), CLIP_MAX_S)
    plan["_style"], plan["_aspect"], plan["_length"], plan["_language"] = style, aspect, length_s, language
    plan["_song"] = song
    return plan


def _c(x) -> str:
    """Field text without trailing punctuation, so joined sentences don't get '..' or '.,'."""
    return str(x or "").strip().rstrip(".;, ")


def _style_text(plan: dict) -> str:
    return STYLES.get(plan.get("_style", ""), "") or plan.get("style", "")


def _negatives(plan: dict) -> list[str]:
    own = [re.sub(r"^(no|avoid|don't|do not)\s+", "", _c(x), flags=re.I) for x in plan.get("negative", [])]
    return list(dict.fromkeys([x for x in own if x] + BASE_NEGATIVE))


def _s(x) -> str:
    """Mid-sentence form: 'A round panda' -> 'a round panda' (keeps names and 'I')."""
    x = _c(x)
    return x[:1].lower() + x[1:] if x[:2].istitle() and x.split(" ", 1)[0] in ("A", "An", "The") else x


def _a(x) -> str:
    x = _c(x)
    return x if re.match(r"(?i)^(a|an|the)", x) else f"A {x[:1].lower() + x[1:]}" if x else x


def _camera(s: dict) -> str:
    return _c(s.get("camera") or ", ".join(x for x in (s.get("camera_angle"), s.get("camera_movement")) if x))


DEFAULT_QUALITY = {
    "kids": "high-end 3D animated render, soft global illumination, gentle ambient occlusion, smooth rounded surfaces, "
            "clean saturated colors, crisp 4K detail, fluid 24fps motion",
    "other": "crisp 4K detail, realistic textures, natural motion blur, fluid 24fps motion, professional color grading",
}
DEFAULT_VOICE_QUALITY = "clean close-mic studio-quality recording, clear words, no echo, no background noise"
DEFAULT_MIX = "voice clear and upfront, music softly underneath, effects light; no clipping or distortion"


def _voice_desc(plan: dict) -> str:
    v = plan.get("voice", {})
    sg = plan.get("song") or {}
    who = _c(v.get("character") or sg.get("vocal") or v.get("style"))
    return "; ".join(x for x in [who, _c(v.get("delivery")), _c(v.get("quality")) or DEFAULT_VOICE_QUALITY] if x)


def _words(s: dict, plan: dict) -> str:
    if s.get("lyrics"):
        return f'Sings (in tune, on the beat): "{s["lyrics"].strip()}"'
    if s.get("dialogue"):
        spk, _, line = str(s["dialogue"]).partition(":")
        return f'{_c(spk)} says: "{line.strip()}"' if line else f'Says: "{_c(spk)}"'
    if s.get("narration"):
        return f'Voiceover says: "{s["narration"].strip()}"'
    return ""


def _sound(s: dict, plan: dict) -> str:
    """Short audio summary (used in the complete prompt)."""
    parts = [x for x in [_words(s, plan), f"Music: {_c(s['music'])}" if s.get("music") else "",
                         f"Sound effects: {_c(s['sound_effects'])}" if s.get("sound_effects") else ""] if x]
    return ". ".join(parts) + "." if parts else "No speech."


def clip_prompt(plan: dict, s: dict, prev: dict | None = None) -> str:
    """One self-contained Veo prompt (one clip, at most 8 s). Every block is complete: Veo sees nothing else."""
    aspect = "vertical 9:16" if plan.get("_aspect", "9:16") == "9:16" else "horizontal 16:9"
    text = json.dumps(s, ensure_ascii=False).lower()
    kids = plan.get("_song") or "kids" in str(plan.get("_style", "")).lower()
    chars = [f"{_c(c.get('name'))}: {_s(c.get('look'))}" for c in plan.get("characters", [])
             if c.get("name") and c["name"].lower() in text]
    in_shot = [str(x).lower() for x in s.get("props", []) if x]
    props = [f"{_c(p.get('name'))}: {_s(p.get('look'))}" for p in plan.get("props", [])
             if p.get("name") and (p["name"].lower() in in_shot or p["name"].lower() in text)]
    places = {p.get("name", "").lower(): _c(p.get("look")) for p in plan.get("settings", [])}
    env = _c(s.get("environment"))
    setting = places.get(env.lower(), "")
    bg = "; ".join(x for x in [_c(s.get("background")), _s(setting) if setting else ""] if x)
    sg = plan.get("song") or {}
    m = plan.get("music", {})
    if s.get("lyrics"):
        music = (f"upbeat children's song, {sg.get('bpm') or m.get('tempo_bpm', 115)} bpm, {_c(sg.get('key'))}, "
                 f"{_c(sg.get('instruments') or m.get('instruments'))}")
    else:
        music = _c(s.get("music")) or ", ".join(x for x in [_c(m.get("mood")), _c(m.get("genre")), _c(m.get("instruments"))] if x)
    words = _words(s, plan)
    L = [f"SHOT: {s['seconds']:g}-second {aspect} video. {_c(_style_text(plan))[:1].upper() + _c(_style_text(plan))[1:]}."
         + (f" Color palette: {_c(plan['color_grade'])}." if plan.get("color_grade") else ""),
         f"CHARACTERS: {' | '.join(chars)}." if chars else "",
         f"PROPS: {' | '.join(props)}." if props else "",
         f"SETTING AND BACKGROUND: {env}. {bg}." if (env or bg) else "",
         f"ACTION: {_c(s.get('action'))}." + (f" Move: {_c(s['dance'])}." if s.get("dance") else "")
         + (f" {_c(s['key_details'])}." if s.get("key_details") else ""),
         f"CAMERA: {_camera(s)}." if _camera(s) else "",
         f"LIGHTING AND MOOD: {_c(s.get('lighting'))}; {_s(s.get('mood'))}." if s.get("lighting") else "",
         f"VOICE: {_voice_desc(plan)}." if words else "VOICE: no speech or singing.",
         words + "." if words else "",
         f"MUSIC: {music}." if music else "",
         f"SOUND EFFECTS: {_c(s.get('sound_effects'))}." if s.get("sound_effects") else "",
         f"AUDIO MIX: {_c(plan.get('audio_mix')) or DEFAULT_MIX}.",
         f"QUALITY: {_c(plan.get('render_quality')) or DEFAULT_QUALITY['kids' if kids else 'other']}; "
         "same character design, colors and proportions as every other clip.",
         "CONTINUITY: continues straight on from the previous clip, same characters, props, place and lighting." if prev else "",
         "AVOID: subtitles or any on-screen text, watermarks, logos, distorted faces or hands, flicker, characters changing look."]
    return "\n".join(x for x in L if x.strip(" ."))


def clip_prompts(plan: dict) -> list[str]:
    sc = plan.get("scenes", [])
    return [clip_prompt(plan, s, sc[i - 1] if i else None) for i, s in enumerate(sc)]


def complete_prompt(plan: dict) -> str:
    """The whole video as one structured prompt (objective to platform), ready to paste."""
    aspect = plan.get("_aspect", "9:16")
    total = sum(float(s.get("seconds") or 0) for s in plan.get("scenes", []))
    st_ = plan.get("structure", {})
    sg = plan.get("song") or {}
    L = [f"VIDEO: {plan.get('title', '')}", "",
         "1. OBJECTIVE", f"{_c(plan.get('objective'))}. Audience: {_c(plan.get('target_audience'))}. "
         f"Viewers should feel: {_c(plan.get('emotion'))}.", "",
         "2. FORMAT", f"{'Vertical 9:16' if aspect == '9:16' else 'Horizontal 16:9'}, about {total:.0f} seconds, "
         f"for {plan.get('platform', '')}. {len(plan.get('scenes', []))} clips of up to {CLIP_MAX_S} s each.", "",
         "3. STYLE", f"{_c(_style_text(plan))}." + (f" Color grade: {_c(plan['color_grade'])}." if plan.get("color_grade") else ""), "",
         "4. HOOK (first 2 seconds)", plan.get("hook", ""), "",
         "5. STRUCTURE", f"Beginning: {st_.get('beginning', '')}", f"Middle: {st_.get('middle', '')}",
         f"Ending: {st_.get('ending', '')}", "",
         "6. CHARACTERS AND PLACES (identical in every scene)"]
    L += [f"- {c.get('name', '')}: {c.get('look', '')}" for c in plan.get("characters", [])]
    L += [f"- {p.get('name', '')}: {p.get('look', '')}" for p in plan.get("settings", [])]
    if plan.get("props"):
        L += ["", "PROPS AND OBJECTS (identical every time they appear)"]
        L += [f"- {p.get('name', '')}: {p.get('look', '')}" for p in plan.get("props", [])]
    if sg:
        L += ["", f"7. SONG: \"{sg.get('title', '')}\" ({sg.get('bpm', '')} bpm, {sg.get('key', '')}, {sg.get('instruments', '')})",
              f"Vocal: {sg.get('vocal', '')}", str(sg.get("lyrics", ""))]
    L += ["", "8. SCENES"]
    t = 0.0
    for s in plan.get("scenes", []):
        end = t + float(s.get("seconds") or 0)
        L += [f"Scene {s['n']} ({t:.0f}-{end:.0f}s, {s.get('purpose', '')})",
              f"  Setting: {_c(s.get('environment'))}. Background: {_c(s.get('background'))}",
              f"  Subject: {_c(s.get('subject'))}" + (f". Props: {', '.join(map(str, s['props']))}" if s.get("props") else ""),
              f"  Action: {_c(s.get('action'))}" + (f". Move: {_c(s['dance'])}" if s.get("dance") else ""),
              f"  Camera: {_camera(s)}. Lighting: {_c(s.get('lighting'))}. Mood: {_c(s.get('mood'))}",
              f"  Audio: {_sound(s, plan)}"]
        if s.get("on_screen_text"):
            L.append(f"  On-screen text (added in editing): {s['on_screen_text']}")
        L.append(f"  Transition: {_c(s.get('transition'))}")
        t = end
    v, m = plan.get("voice", {}), plan.get("music", {})
    L += ["", "9. AUDIO", f"Voice: {_c(v.get('use'))}; {_voice_desc(plan)}.",
          f"Mix: {_c(plan.get('audio_mix')) or DEFAULT_MIX}.",
          f"Music: {_c(m.get('mood'))} {_c(m.get('genre'))}, about {m.get('tempo_bpm', '')} bpm, {_c(m.get('instruments'))}.", "",
          "10. RETENTION", *[f"- {x}" for x in plan.get("retention_plan", [])], "",
          "11. CONTINUITY", *[f"- {x}" for x in plan.get("continuity", [])],
          "- Same characters, clothing, props, place and lighting from scene to scene.", "",
          "12. QUALITY", (_c(plan.get("render_quality")) or DEFAULT_QUALITY["kids" if plan.get("_song") else "other"])
          + ". Clean composition, natural smooth motion, consistent subjects.", "",
          "13. AVOID", ", ".join(_negatives(plan)) + ".", "",
          "14. ENDING", plan.get("final_scene", ""), "",
          "15. PLATFORM", f"Optimised for {plan.get('platform', '')}: grabs attention in the first 2 seconds, "
          f"{'subject centred for vertical framing' if aspect == '9:16' else 'wide framing for horizontal'}."]
    return "\n".join(L)
