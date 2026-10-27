"""Make one AI video clip on your own GPU (LTX-2.5, free, no watermark).

  python make_clip.py "a fox running through snow at sunset"
  python make_clip.py "..." --wide --seconds 8 --count 3

Needs ComfyUI running (run_nvidia_gpu.bat). Clips land in output/clips/.
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

from niche_studio.comfy import Comfy

ROOT = Path(__file__).parent
WORKFLOW = ROOT / "workflows" / "ltx25_t2v_api.json"
FPS = 24


def main():
    ap = argparse.ArgumentParser(description="Make an AI video clip locally")
    ap.add_argument("prompt")
    ap.add_argument("--wide", action="store_true", help="16:9 instead of vertical 9:16")
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--count", type=int, default=1, help="how many versions to make (different seeds)")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    a = ap.parse_args()

    # Stage 1 renders at half size; the x2 upscaler brings it to 704x1280 (or 1280x704).
    w, h = (640, 352) if a.wide else (352, 640)
    frames = 1 + int(a.seconds * FPS) // 8 * 8
    comfy = Comfy(a.url, WORKFLOW)
    if not comfy.available():
        raise SystemExit("ComfyUI is not running. Start G:\\sajin\\vidGen\\ComfyUI_windows_portable\\run_nvidia_gpu.bat")

    slug = re.sub(r"[^a-z0-9]+", "-", a.prompt.lower())[:40].strip("-")
    for i in range(a.count):
        seed = a.seed + i if a.seed is not None else None
        out = ROOT / "output" / "clips" / f"{time.strftime('%Y%m%d-%H%M%S')}_{slug}.mp4"
        t = time.time()
        print(f"[{i + 1}/{a.count}] rendering {w * 2}x{h * 2}, {a.seconds:g}s ...", flush=True)
        path = comfy.render(a.prompt, out, w, h, frames, negative="", seed=seed)
        print(f"  done in {time.time() - t:.0f}s -> {path}")


if __name__ == "__main__":
    main()
