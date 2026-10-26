"""Real trend detection: measured view velocity between snapshots, not views/age guesses.

`views / age` flatters old videos and can't tell a video that is taking off today from one that
peaked a month ago. Every scan stores a snapshot; `niche track` re-reads the same videos for
~1 quota unit per 50 videos (no search), so you can run it daily for almost nothing.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _db(cfg):
    con = sqlite3.connect(cfg["_output"] / "tracker.db")
    con.execute("""CREATE TABLE IF NOT EXISTS snap(niche TEXT, video_id TEXT, ts TEXT, views INT,
                   likes INT, comments INT, PRIMARY KEY(niche, video_id, ts))""")
    return con


def record_snapshot(cfg: dict, niche: str, videos: list[dict], ts: str | None = None) -> None:
    ts = ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _db(cfg) as con:
        con.executemany("INSERT OR REPLACE INTO snap VALUES (?,?,?,?,?,?)",
                        [(niche, v["video_id"], ts, v["views"], v["likes"], v["comments"]) for v in videos])


def tracked_ids(cfg: dict, niche: str) -> list[str]:
    with _db(cfg) as con:
        return [r[0] for r in con.execute("SELECT DISTINCT video_id FROM snap WHERE niche=?", (niche,))]


def velocities(cfg: dict, niche: str) -> dict[str, dict]:
    """video_id -> measured views/day over the last two snapshots and acceleration vs the one before."""
    with _db(cfg) as con:
        rows = con.execute("SELECT video_id, ts, views FROM snap WHERE niche=? ORDER BY video_id, ts",
                           (niche,)).fetchall()
    by: dict[str, list] = {}
    for vid, ts, views in rows:
        by.setdefault(vid, []).append((datetime.fromisoformat(ts), views))
    out = {}
    for vid, s in by.items():
        if len(s) < 2:
            continue
        (t1, v1), (t2, v2) = s[-2], s[-1]
        days = max((t2 - t1).total_seconds() / 86400, 1 / 24)
        vel = (v2 - v1) / days
        acc = None
        if len(s) >= 3:
            t0, v0 = s[-3]
            prev = (v1 - v0) / max((t1 - t0).total_seconds() / 86400, 1 / 24)
            acc = round(vel / prev, 2) if prev > 0 else None
        out[vid] = {"measured_vpd": round(vel), "acceleration": acc, "snapshots": len(s),
                    "window_days": round(days, 2)}
    return out


def refresh(cfg: dict, niche: str, log=print) -> int:
    """Cheap daily refresh of already-found videos (videos.list only)."""
    from .youtube_api import YouTube
    yc = cfg.get("youtube", {})
    yt = YouTube(yc.get("api_key"), cfg["_output"] / ".cache", cache_hours=0)
    ids = tracked_ids(cfg, niche)
    if not ids:
        raise ValueError(f"Nothing tracked for '{niche}' yet. Run scan first.")
    vids = yt.videos(ids)
    record_snapshot(cfg, niche, vids)
    log(f"  refreshed {len(vids)} videos for {yt.units_used} quota units")
    return len(vids)
