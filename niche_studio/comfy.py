"""ComfyUI API client for local text-to-video on your GPU.

How to prepare a workflow (one time):
  1. Build/load a text-to-video workflow in ComfyUI that works (e.g. Wan 2.2 5B or LTX-Video).
  2. Settings -> enable Dev mode, then Workflow -> Export (API). Save it as workflows/t2v_api.json.
  3. In that JSON replace the values with placeholders:
        positive prompt text  -> "{{PROMPT}}"      negative prompt text -> "{{NEGATIVE}}"
        seed / noise_seed     -> "{{SEED}}"        width / height       -> "{{WIDTH}}" / "{{HEIGHT}}"
        length / num_frames   -> "{{FRAMES}}"      output filename_prefix -> "{{PREFIX}}"
        (image-to-video only) LoadImage image -> "{{IMAGE}}"  : your character reference picture
     Numeric placeholders are written as strings in the file; they are converted to numbers here.
"""
from __future__ import annotations

import json
import random
import time
import uuid
from pathlib import Path

import requests

VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv", ".gif", ".webp")
NUMERIC = {"{{SEED}}", "{{WIDTH}}", "{{HEIGHT}}", "{{FRAMES}}"}


class ComfyError(RuntimeError):
    pass


class Comfy:
    def __init__(self, url: str, workflow_path: Path):
        self.url = url.rstrip("/")
        self.workflow_path = Path(workflow_path)
        self.client_id = str(uuid.uuid4())

    def available(self) -> bool:
        try:
            return requests.get(self.url + "/system_stats", timeout=5).ok and self.workflow_path.exists()
        except requests.RequestException:
            return False

    def _fill(self, values: dict) -> dict:
        wf = json.loads(self.workflow_path.read_text(encoding="utf-8"))
        found = set()

        def walk(o):
            if isinstance(o, dict):
                return {k: walk(v) for k, v in o.items()}
            if isinstance(o, list):
                return [walk(v) for v in o]
            if isinstance(o, str):
                for ph, val in values.items():
                    if o == ph:
                        found.add(ph)
                        return int(val) if ph in NUMERIC else val
                    if ph in o and ph not in NUMERIC:
                        found.add(ph)
                        o = o.replace(ph, str(val))
            return o

        wf = walk(wf)
        if "{{PROMPT}}" not in found:
            raise ComfyError(f"{self.workflow_path} has no \"{{{{PROMPT}}}}\" placeholder. See comfy.py header.")
        return wf

    def upload_image(self, path: Path) -> str:
        with open(path, "rb") as f:
            r = requests.post(self.url + "/upload/image", files={"image": (path.name, f)},
                              data={"overwrite": "true"}, timeout=60)
        r.raise_for_status()
        j = r.json()
        return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]

    def render(self, prompt: str, out_path: Path, width: int, height: int, frames: int,
               negative: str = "", seed: int | None = None, timeout_s: int = 1800, image: Path | None = None) -> Path:
        seed = seed if seed is not None else random.randint(1, 2**31 - 1)
        prefix = f"niche/{out_path.stem}_{seed}"
        values = {"{{PROMPT}}": prompt, "{{NEGATIVE}}": negative, "{{SEED}}": seed,
                  "{{WIDTH}}": width, "{{HEIGHT}}": height, "{{FRAMES}}": frames, "{{PREFIX}}": prefix}
        if image is not None and "{{IMAGE}}" in self.workflow_path.read_text(encoding="utf-8"):
            values["{{IMAGE}}"] = self.upload_image(image)
        wf = self._fill(values)
        r = requests.post(self.url + "/prompt", json={"prompt": wf, "client_id": self.client_id}, timeout=30)
        if not r.ok:
            raise ComfyError(f"ComfyUI rejected the workflow: {r.text[:800]}")
        pid = r.json()["prompt_id"]

        start = time.time()
        while time.time() - start < timeout_s:
            h = requests.get(f"{self.url}/history/{pid}", timeout=30).json()
            if pid in h:
                entry = h[pid]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError(f"ComfyUI error: {json.dumps(status.get('messages', []))[:800]}")
                files = self._outputs(entry.get("outputs", {}))
                if files:
                    return self._download(files, out_path)
                if status.get("completed"):
                    raise ComfyError("Workflow finished but produced no video/image output.")
            time.sleep(3)
        raise ComfyError(f"Timed out after {timeout_s}s waiting for ComfyUI.")

    @staticmethod
    def _outputs(outputs: dict) -> list[dict]:
        vids, imgs = [], []
        for node in outputs.values():
            for key in ("gifs", "videos", "video", "images", "animated"):
                for f in node.get(key, []) or []:
                    if not isinstance(f, dict) or "filename" not in f or f.get("type") == "temp":
                        continue
                    (vids if f["filename"].lower().endswith(VIDEO_EXT) else imgs).append(f)
        return vids[:1] if vids else sorted(imgs, key=lambda f: f["filename"])

    def _download(self, files: list[dict], out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if len(files) == 1:
            f = files[0]
            ext = Path(f["filename"]).suffix
            dest = out_path.with_suffix(ext)
            self._get_file(f, dest)
            return dest
        # Image sequence -> frames folder; assembler turns it into a clip.
        frames = out_path.with_suffix("")
        frames.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(files):
            self._get_file(f, frames / f"{i:05d}{Path(f['filename']).suffix}")
        return frames

    def _get_file(self, f: dict, dest: Path):
        r = requests.get(self.url + "/view", params={"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                                      "type": f.get("type", "output")}, timeout=300)
        r.raise_for_status()
        dest.write_bytes(r.content)

    def free_memory(self):
        try:
            requests.post(self.url + "/free", json={"unload_models": True, "free_memory": True}, timeout=10)
        except requests.RequestException:
            pass
