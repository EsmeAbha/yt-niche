"""Voiceover per scene.

engines:
  edge   - Microsoft Edge neural voices via the `edge-tts` package. Free, needs internet,
           many languages incl. Bangla (bn-BD-NabanitaNeural, bn-BD-PradeepNeural).
  piper  - fully offline (`piper` binary + a .onnx voice). Set tts.piper_model.
  none   - no voiceover (music/sfx-only shorts, or Veo clips that carry their own audio).
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path


def synthesize(cfg: dict, text: str, out: Path, voice: str | None = None) -> Path | None:
    tc = cfg.get("tts", {})
    engine = tc.get("engine", "edge")
    text = (text or "").strip()
    if not text or engine == "none":
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    if engine == "edge":
        import edge_tts

        async def run():
            c = edge_tts.Communicate(text, voice or tc.get("voice", "en-US-AndrewMultilingualNeural"),
                                     rate=tc.get("rate", "+8%"), pitch=tc.get("pitch", "+0Hz"))
            await c.save(str(out.with_suffix(".mp3")))
        asyncio.run(run())
        return out.with_suffix(".mp3")
    if engine == "piper":
        exe = shutil.which(tc.get("piper_bin", "piper")) or tc.get("piper_bin", "piper")
        wav = out.with_suffix(".wav")
        subprocess.run([exe, "--model", tc["piper_model"], "--output_file", str(wav)],
                       input=text.encode("utf-8"), check=True, capture_output=True)
        return wav
    raise ValueError(f"Unknown tts.engine '{engine}'")
