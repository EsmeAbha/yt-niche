"""Stage 1: pull everything about a niche from YouTube and save it as raw JSON."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from .config import niche_dir
from .youtube_api import YouTube


def scan_label(niche: str, market: str | None) -> str:
    return f"{niche} @{market}" if market else niche


def scan_niche(cfg: dict, niche: str, days: int | None = None, log=print, market: str | None = None,
               query: str | None = None) -> dict:
    """market: a key from money.markets() (us, uk, de, jp...). Searches that country's YouTube in its
    language, with `query` as the translated niche term if given."""
    from .money import markets
    yc = cfg.get("youtube", {})
    days = days or yc.get("lookback_days", 90)
    yt = YouTube(yc.get("api_key"), cfg["_output"] / ".cache", yc.get("cache_hours", 12))
    region, lang = yc.get("region"), yc.get("language")
    if market:
        m = markets(cfg)[market]
        region, lang = m["region"], m["lang"]
    label = scan_label(niche, market)
    niche_q = niche
    niche = query or niche

    log(f"Searching '{niche}' (last {days} days{', market ' + market if market else ''})...")
    ids: list[str] = []
    # Shorts: searched explicitly because viewCount order otherwise buries them.
    ids += yt.search(f"{niche} #shorts", days=days, duration="short", region=region, language=lang,
                     pages=yc.get("search_pages", 1))
    ids += yt.search(niche, days=days, duration="medium", region=region, language=lang,
                     pages=yc.get("search_pages", 1))
    ids += yt.search(niche, days=days, duration="long", region=region, language=lang, pages=1)
    # Relevance-ordered pass catches newer videos that are climbing fast.
    ids += yt.search(niche, days=min(days, 21), order="relevance", region=region, language=lang, pages=1)
    ids = list(dict.fromkeys(ids))
    log(f"  {len(ids)} videos found")

    videos = yt.videos(ids)
    channels = yt.channels([v["channel_id"] for v in videos if v["channel_id"]])
    log(f"  {len(channels)} channels")

    # Channel baselines: median views of each channel's recent uploads.
    top_channels = sorted(
        channels.values(),
        key=lambda c: -max((v["views"] for v in videos if v["channel_id"] == c["channel_id"]), default=0),
    )[: yc.get("baseline_channels", 40)]
    # Their last N uploads give per-format baselines (Shorts and long-form are judged separately),
    # upload cadence, and an estimate of the channel's monthly views/revenue.
    for c in top_channels:
        c["recent_uploads"] = yt.recent_uploads(c["uploads_playlist"], yc.get("baseline_uploads", 30))

    # Comments on the best performers.
    top_vids = sorted(videos, key=lambda v: -v["views"])[: yc.get("comment_videos", 15)]
    comments = []
    for v in top_vids:
        if v["comments"] > 0:
            comments += yt.comments(v["video_id"], yc.get("comments_per_video", 100))
    log(f"  {len(comments)} comments from {len(top_vids)} top videos")

    raw = {
        "niche": label,
        "query": niche,
        "base_niche": niche_q,
        "market": market,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": days,
        "quota_units_used": yt.units_used,
        "videos": videos,
        "channels": channels,
        "comments": comments,
    }
    out = niche_dir(cfg, label) / "raw.json"
    out.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    from .tracker import record_snapshot
    record_snapshot(cfg, label, videos)
    log(f"  saved {out} (quota used this run: {yt.units_used} units)")
    return raw
