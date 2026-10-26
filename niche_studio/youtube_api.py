"""Thin YouTube Data API v3 client with on-disk caching and quota accounting.

Quota costs (default 10,000 units/day per project):
  search.list = 100, videos/channels/playlistItems/commentThreads.list = 1 each.
A full niche scan costs roughly 250-500 units, so ~20-40 scans/day.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://www.googleapis.com/youtube/v3/"
COST = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1, "commentThreads": 1}


class QuotaExceeded(RuntimeError):
    pass


class YouTube:
    def __init__(self, api_key: str, cache_dir: Path, cache_hours: float = 12):
        if not api_key or api_key.startswith("YOUR_"):
            raise ValueError("Set youtube.api_key in config.yaml or the YOUTUBE_API_KEY env var.")
        self.key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = cache_hours * 3600
        self.units_used = 0
        self.session = requests.Session()

    # ---------- low level ----------
    def _get(self, endpoint: str, **params) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        key = hashlib.sha1(json.dumps([endpoint, params], sort_keys=True).encode()).hexdigest()
        cache = self.cache_dir / f"{key}.json"
        if cache.exists() and time.time() - cache.stat().st_mtime < self.ttl:
            return json.loads(cache.read_text(encoding="utf-8"))

        for attempt in range(3):
            r = self.session.get(API + endpoint, params={**params, "key": self.key}, timeout=30)
            if r.status_code == 403 and "quota" in r.text.lower():
                raise QuotaExceeded("YouTube API daily quota used up. It resets at midnight Pacific time.")
            if r.status_code in (500, 503):
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 403 and "commentsDisabled" in r.text:
                return {"items": []}
            r.raise_for_status()
            break
        data = r.json()
        self.units_used += COST.get(endpoint, 1)
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data

    @staticmethod
    def _chunks(seq, n=50):
        for i in range(0, len(seq), n):
            yield seq[i : i + n]

    # ---------- high level ----------
    def search(self, query: str, days: int = 90, duration: str | None = None, order: str = "viewCount",
               max_results: int = 50, region: str | None = None, language: str | None = None,
               pages: int = 1) -> list[str]:
        """Return video IDs. duration: None | 'short' (<4m) | 'medium' (4-20m) | 'long' (>20m)."""
        after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids, token = [], None
        for _ in range(pages):
            d = self._get("search", part="snippet", q=query, type="video", order=order,
                          publishedAfter=after, maxResults=min(max_results, 50), videoDuration=duration,
                          regionCode=region, relevanceLanguage=language, pageToken=token)
            ids += [i["id"]["videoId"] for i in d.get("items", []) if i.get("id", {}).get("videoId")]
            token = d.get("nextPageToken")
            if not token:
                break
        return list(dict.fromkeys(ids))

    def videos(self, ids: list[str]) -> list[dict]:
        out = []
        for chunk in self._chunks(ids):
            d = self._get("videos", part="snippet,statistics,contentDetails", id=",".join(chunk))
            out += [self._flatten_video(v) for v in d.get("items", [])]
        return out

    def channels(self, ids: list[str]) -> dict[str, dict]:
        out = {}
        for chunk in self._chunks(list(dict.fromkeys(ids))):
            d = self._get("channels", part="snippet,statistics,contentDetails", id=",".join(chunk))
            for c in d.get("items", []):
                st = c.get("statistics", {})
                out[c["id"]] = {
                    "channel_id": c["id"],
                    "title": c["snippet"]["title"],
                    "subscribers": int(st.get("subscriberCount", 0) or 0),
                    "channel_views": int(st.get("viewCount", 0) or 0),
                    "video_count": int(st.get("videoCount", 0) or 0),
                    "uploads_playlist": c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
                    "created_at": c["snippet"].get("publishedAt"),
                    "country": c["snippet"].get("country"),
                    "hidden_subs": st.get("hiddenSubscriberCount", False),
                }
        return out

    def recent_uploads(self, uploads_playlist: str, n: int = 30) -> list[dict]:
        """A channel's last n uploads with full stats: the baseline for outliers and channel economics."""
        if not uploads_playlist:
            return []
        d = self._get("playlistItems", part="contentDetails", playlistId=uploads_playlist, maxResults=min(n, 50))
        ids = [i["contentDetails"]["videoId"] for i in d.get("items", [])]
        keep = ("video_id", "published_at", "views", "duration_s", "is_short", "category_id", "has_sponsor",
                "has_affiliate", "has_merch_or_product")
        return [{k: v[k] for k in keep} for v in self.videos(ids)]

    def comments(self, video_id: str, n: int = 100) -> list[dict]:
        d = self._get("commentThreads", part="snippet", videoId=video_id, order="relevance",
                      maxResults=min(n, 100), textFormat="plainText")
        out = []
        for it in d.get("items", []):
            s = it["snippet"]["topLevelComment"]["snippet"]
            out.append({"video_id": video_id, "text": s.get("textDisplay", ""),
                        "likes": int(s.get("likeCount", 0)), "replies": it["snippet"].get("totalReplyCount", 0)})
        return out

    # ---------- helpers ----------
    @staticmethod
    def _flatten_video(v: dict) -> dict:
        sn, st, cd = v.get("snippet", {}), v.get("statistics", {}), v.get("contentDetails", {})
        secs = parse_duration(cd.get("duration", "PT0S"))
        title = sn.get("title", "")
        desc = sn.get("description", "")
        return {
            "video_id": v["id"],
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "title": title,
            "description": desc[:1500],
            "tags": sn.get("tags", [])[:30],
            "channel_id": sn.get("channelId"),
            "channel_title": sn.get("channelTitle"),
            "published_at": sn.get("publishedAt"),
            "thumbnail": (sn.get("thumbnails", {}).get("high") or sn.get("thumbnails", {}).get("default") or {}).get("url"),
            "duration_s": secs,
            "is_short": secs <= 180 and (secs <= 60 or "#short" in (title + desc).lower()),
            "views": int(st.get("viewCount", 0) or 0),
            "likes": int(st.get("likeCount", 0) or 0),
            "comments": int(st.get("commentCount", 0) or 0),
            "language": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"),
            "category_id": sn.get("categoryId"),
            **money_signals(desc),
        }


# Money signals in descriptions: proof that brands/affiliates already pay in this niche.
_SPONSOR = re.compile(r"\b(sponsored by|thanks to .{0,40} for sponsoring|this video is sponsored|use (my )?code|promo code|"
                      r"discount code|partnered with|#ad\b|paid promotion)", re.I)
_AFFILIATE = re.compile(r"(amzn\.to|amazon\.[a-z.]+/[^ ]*tag=|geni\.us|bit\.ly|affiliate|commission|linktr\.ee|"
                        r"shareasale|impact\.com|clickbank|daraz\.com\.bd)", re.I)
_PRODUCT = re.compile(r"\b(my course|merch|shop now|patreon|buy me a coffee|ko-fi|membership|join this channel|"
                      r"preset|template pack|ebook|gumroad|whop\.com|skool\.com)", re.I)


def money_signals(desc: str) -> dict:
    return {"has_sponsor": bool(_SPONSOR.search(desc or "")),
            "has_affiliate": bool(_AFFILIATE.search(desc or "")),
            "has_merch_or_product": bool(_PRODUCT.search(desc or ""))}


def parse_duration(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s
