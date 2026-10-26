"""Publish to your own Facebook Page through the official Graph API.

Setup: developers.facebook.com -> create an app (Business) -> add your Page -> get a long-lived
Page access token with pages_manage_posts, pages_read_engagement, pages_show_list and publish_video.
Put page_id and page_token in config.yaml (or FB_PAGE_ID / FB_PAGE_TOKEN env vars).

Vertical videos go up as Reels (3-step upload); horizontal ones as normal Page videos.
"""
from __future__ import annotations

from pathlib import Path

import requests


def upload(cfg: dict, video: Path, idea: dict, log=print) -> str:
    fc = cfg.get("facebook", {})
    page, token = fc.get("page_id"), fc.get("page_token")
    if not page or not token or str(token).startswith("YOUR_"):
        raise ValueError("Set facebook.page_id and facebook.page_token in config.yaml.")
    ver = fc.get("graph_version", "v23.0")
    caption = idea.get("facebook_caption") or idea.get("title", "")
    caption += "\n" + " ".join(idea.get("hashtags", [])[:5])
    if idea.get("format", "short") == "short":
        return _reel(ver, page, token, video, caption, log)
    url = f"https://graph-video.facebook.com/{ver}/{page}/videos"
    with open(video, "rb") as f:
        r = requests.post(url, data={"access_token": token, "title": idea.get("title", "")[:250],
                                     "description": caption}, files={"source": f}, timeout=1800)
    r.raise_for_status()
    vid = r.json()["id"]
    log(f"  Facebook video: {vid}")
    return vid


def _reel(ver, page, token, video: Path, caption: str, log) -> str:
    base = f"https://graph.facebook.com/{ver}/{page}/video_reels"
    r = requests.post(base, data={"upload_phase": "start", "access_token": token}, timeout=60)
    r.raise_for_status()
    vid = r.json()["video_id"]
    size = video.stat().st_size
    with open(video, "rb") as f:
        up = requests.post(f"https://rupload.facebook.com/video-upload/{ver}/{vid}",
                           headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
                           data=f, timeout=1800)
    up.raise_for_status()
    fin = requests.post(base, data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                    "description": caption, "access_token": token}, timeout=120)
    fin.raise_for_status()
    log(f"  Facebook Reel: {vid} (processing; appears on the Page in a few minutes)")
    return vid
