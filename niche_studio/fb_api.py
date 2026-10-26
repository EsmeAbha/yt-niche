"""Facebook Graph API client. Free, official, no scraping.

What Meta lets you read:
  YOUR Page (Page token with read_insights + pages_read_engagement + pages_manage_engagement):
    every Reel and video, with plays, avg watch time, retention, followers gained, views by country.
  OTHER Pages (needs the "Page Public Content Access" feature, which is free but requires Meta app review
  and business verification): their public posts with reactions, comments and shares. Meta does NOT
  expose other Pages' view counts, so competitor analysis uses engagement.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

REEL_METRICS = ["fb_reels_total_plays", "blue_reels_play_count", "fb_reels_replay_count", "post_impressions_unique",
                "post_video_avg_time_watched", "post_video_view_time", "post_video_followers", "post_video_social_actions"]
VIDEO_METRICS = ["total_video_views", "total_video_views_unique", "total_video_avg_time_watched",
                 "total_video_complete_views", "total_video_10s_views", "total_video_impressions_unique",
                 "total_video_views_by_country_id", "total_video_view_total_time"]


class GraphError(RuntimeError):
    pass


class Graph:
    def __init__(self, token: str, version: str = "v23.0", cache_dir: Path | None = None, cache_hours: float = 6):
        if not token or str(token).startswith("YOUR_"):
            raise ValueError("Set facebook.page_token in config.yaml (or FB_PAGE_TOKEN).")
        self.token, self.base = token, f"https://graph.facebook.com/{version}/"
        self.cache_dir, self.ttl = cache_dir, cache_hours * 3600
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self.s = requests.Session()

    def get(self, path: str, **params) -> dict:
        key = hashlib.sha1(json.dumps([path, params], sort_keys=True).encode()).hexdigest()
        cache = self.cache_dir / f"fb_{key}.json" if self.cache_dir else None
        if cache and cache.exists() and time.time() - cache.stat().st_mtime < self.ttl:
            return json.loads(cache.read_text(encoding="utf-8"))
        for attempt in range(3):
            r = self.s.get(self.base + path.lstrip("/"), params={**params, "access_token": self.token}, timeout=60)
            if r.status_code in (500, 502, 503) or (r.status_code == 400 and '"code":4' in r.text.replace(" ", "")):
                time.sleep(3 * (attempt + 1))  # transient or app rate limit
                continue
            break
        data = r.json()
        if "error" in data:
            err = data["error"]
            hint = ""
            if err.get("code") in (10, 200) or "Public Content Access" in err.get("message", ""):
                hint = (" -> Reading other Pages needs the 'Page Public Content Access' feature. Apply in your "
                        "Meta app (App Review), or log competitor Reels by hand with `niche fb-log`.")
            if err.get("code") == 190:
                hint = " -> Token expired or invalid. Generate a new long-lived Page token."
            raise GraphError(f"Graph API {err.get('code')}: {err.get('message')}{hint}")
        if cache:
            cache.write_text(json.dumps(data), encoding="utf-8")
        return data

    def paged(self, path: str, max_items: int = 300, **params) -> list[dict]:
        out, after = [], None
        while len(out) < max_items:
            d = self.get(path, limit=min(100, max_items - len(out)), after=after, **params)
            out += d.get("data", [])
            after = d.get("paging", {}).get("cursors", {}).get("after")
            if not after or not d.get("paging", {}).get("next"):
                break
        return out

    def insights(self, video_id: str, metrics: list[str]) -> dict:
        """Ask for all metrics at once; if Meta rejects one, fall back to asking one by one."""
        def parse(d):
            res = {}
            for m in d.get("data", []):
                vals = m.get("values") or [{}]
                res[m["name"]] = vals[0].get("value")
            return res
        try:
            return parse(self.get(f"{video_id}/video_insights", metric=",".join(metrics)))
        except GraphError:
            res = {}
            for m in metrics:
                try:
                    res.update(parse(self.get(f"{video_id}/video_insights", metric=m)))
                except GraphError:
                    pass
            return res


def my_page(cfg: dict, log=print) -> dict:
    fc = cfg.get("facebook", {})
    g = Graph(fc.get("page_token"), fc.get("graph_version", "v23.0"), cfg["_output"] / ".cache")
    page_id = fc.get("page_id")
    page = g.get(page_id, fields="id,name,followers_count,fan_count")
    reels = g.paged(f"{page_id}/video_reels", fc.get("max_items", 200),
                    fields="id,description,created_time,length,permalink_url")
    videos = g.paged(f"{page_id}/videos", fc.get("max_items", 200),
                     fields="id,title,description,created_time,length,permalink_url")
    reel_ids = {r["id"] for r in reels}
    items = []
    for r in reels:
        items.append({**r, "kind": "reel", "insights": g.insights(r["id"], REEL_METRICS)})
    for v in videos:
        if v["id"] in reel_ids:
            continue
        items.append({**v, "kind": "video", "insights": g.insights(v["id"], VIDEO_METRICS)})
    log(f"  {page.get('name')}: {len(reels)} reels, {len(items) - len(reels)} other videos")
    return {"page": page, "items": items}


def watch_pages(cfg: dict, pages: list[str], log=print) -> dict:
    """Public posts of other Pages (needs Page Public Content Access)."""
    fc = cfg.get("facebook", {})
    g = Graph(fc.get("page_token"), fc.get("graph_version", "v23.0"), cfg["_output"] / ".cache")
    out = {}
    fields = ("id,created_time,message,permalink_url,shares,attachments{media_type,type},"
              "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)")
    for ref in pages:
        info = g.get(ref, fields="id,name,followers_count,fan_count,category")
        posts = g.paged(f"{info['id']}/posts", fc.get("watch_posts", 100), fields=fields)
        out[info["id"]] = {"page": info, "posts": posts}
        log(f"  {info.get('name')}: {len(posts)} posts")
    return out
