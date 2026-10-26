"""Loads config.yaml (falls back to config.example.yaml) and environment overrides."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | None = None) -> dict:
    candidates = [Path(path)] if path else [ROOT / "config.yaml", ROOT / "config.example.yaml"]
    for p in candidates:
        if p.exists():
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            break
    else:
        raise FileNotFoundError("No config.yaml found. Copy config.example.yaml to config.yaml.")

    # Environment variables win over the file, so keys never have to live in it.
    env_map = {
        "YOUTUBE_API_KEY": ("youtube", "api_key"),
        "GEMINI_API_KEY": ("llm", "gemini_api_key"),
        "FB_PAGE_ID": ("facebook", "page_id"),
        "FB_PAGE_TOKEN": ("facebook", "page_token"),
    }
    for env, (section, key) in env_map.items():
        if os.environ.get(env):
            cfg.setdefault(section, {})[key] = os.environ[env]

    out = ROOT / cfg.get("output_dir", "output")
    out.mkdir(parents=True, exist_ok=True)
    cfg["_output"] = out
    cfg["_root"] = ROOT
    return cfg


def niche_dir(cfg: dict, niche: str) -> Path:
    slug = "".join(c if c.isalnum() else "-" for c in niche.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    d = cfg["_output"] / slug
    d.mkdir(parents=True, exist_ok=True)
    return d
