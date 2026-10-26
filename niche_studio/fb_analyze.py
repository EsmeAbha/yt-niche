"""Facebook analysis: the same "beat your own normal" logic as YouTube, on the data Meta actually gives.

Three sources, best first:
  mine   - your Page's Reels/videos with real plays, watch time, followers gained, views by country
  watch  - competitor Pages' public posts (engagement only; Meta hides their views)
  log    - Reels you note down by hand while scrolling (CSV), for when you have no API access
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .analyze import OUTLIER, proven_formats

LOG_COLUMNS = ["url", "page", "page_followers", "posted", "views", "reactions", "comments", "shares",
               "length_s", "type", "caption"]


def _ts(s):
    return pd.to_datetime(s, utc=True, errors="coerce")


def _outlier(df: pd.DataFrame, metric: str, group: str = "page_id") -> pd.Series:
    """metric / median(metric) of the same page and same type, needing 3+ posts for a baseline."""
    key = df[group].astype(str) + "|" + df["type"].astype(str)
    val = pd.to_numeric(df[metric], errors="coerce")
    n = val.groupby(key).transform("count")
    med = val.groupby(key).transform("median")
    return (val / med).where((n >= 3) & (med > 0))


def _length_table(df: pd.DataFrame, metric: str) -> list[dict]:
    d = df[df["length_s"].fillna(0) > 0]
    if len(d) < 8:
        return []
    bins, labels = [0, 15, 30, 60, 90, 180, 600, 10**6], ["0-15s", "15-30s", "30-60s", "60-90s", "90s-3m", "3-10m", "10m+"]
    g = d.assign(b=pd.cut(d["length_s"], bins=bins, labels=labels)).groupby("b", observed=True)
    return [{"length": str(k), "posts": int(len(v)), "median": int(v[metric].median()),
             "median_outlier": None if v["outlier"].isna().all() else round(float(v["outlier"].median()), 2)}
            for k, v in g if len(v) >= 3]


def _formats(df: pd.DataFrame, value: str, min_channels: int = 2) -> list[dict]:
    pf = df.rename(columns={"caption": "title", "page_id": "channel_id", "page": "channel_title",
                            "followers": "subscribers", value: "views"}).assign(format=df["type"])
    pf["title"] = pf["title"].fillna("").str.split("\n").str[0].str[:140]
    return proven_formats(pf[pf["title"].str.len() > 3], min_channels=min_channels)


def analyze_mine(data: dict, cfg: dict) -> dict:
    page = data["page"]
    rows = []
    for it in data["items"]:
        ins = it.get("insights", {})
        reel = it["kind"] == "reel"
        plays = (ins.get("fb_reels_total_plays") or ins.get("blue_reels_play_count") or 0) if reel else (ins.get("total_video_views") or 0)
        avg_ms = ins.get("post_video_avg_time_watched") if reel else ins.get("total_video_avg_time_watched")
        length = float(it.get("length") or 0)
        social = ins.get("post_video_social_actions")
        rows.append({
            "id": it["id"], "url": it.get("permalink_url", ""), "type": it["kind"],
            "caption": (it.get("description") or it.get("title") or "").strip(),
            "created": it.get("created_time"), "length_s": length, "plays": int(plays or 0),
            "avg_watch_s": round(avg_ms / 1000, 1) if avg_ms else None,
            "watched_pct": round(100 * avg_ms / 1000 / length, 1) if avg_ms and length else None,
            "followers_gained": ins.get("post_video_followers"),
            "interactions": sum(social.values()) if isinstance(social, dict) else social,
            "countries": ins.get("total_video_views_by_country_id") if isinstance(ins.get("total_video_views_by_country_id"), dict) else None,
            "page_id": page["id"], "page": page.get("name"), "followers": page.get("followers_count", 0),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return {"page": page, "error": "No Reels or videos found on this Page."}
    df["outlier"] = _outlier(df, "plays")
    df["follows_per_1k"] = 1000 * df["followers_gained"].astype(float) / df["plays"].clip(lower=1)
    countries = {}
    for c in df["countries"].dropna():
        for k, v in c.items():
            countries[k] = countries.get(k, 0) + v
    tot = sum(countries.values()) or 1
    top_c = sorted(((k, round(100 * v / tot, 1)) for k, v in countries.items()), key=lambda x: -x[1])[:8]
    by_type = {t: {"posts": int(len(g)), "median_plays": int(g["plays"].median()), "max_plays": int(g["plays"].max()),
                   "median_watched_pct": None if g["watched_pct"].isna().all() else round(float(g["watched_pct"].median()), 1),
                   "median_follows_per_1k": None if g["follows_per_1k"].isna().all() else round(float(g["follows_per_1k"].median()), 2)}
               for t, g in df.groupby("type")}
    cols = ["url", "type", "caption", "plays", "outlier", "avg_watch_s", "watched_pct", "followers_gained", "length_s", "created"]
    return {
        "page": page, "by_type": by_type, "audience_countries": top_c,
        "best": df.sort_values("outlier", ascending=False).head(12)[cols].round(2).to_dict("records"),
        "worst": df[df["outlier"].notna()].sort_values("outlier").head(6)[cols].round(2).to_dict("records"),
        "followers_drivers": df.sort_values("follows_per_1k", ascending=False).head(6)[cols].round(2).to_dict("records"),
        "lengths": _length_table(df.rename(columns={"plays": "v"}), "v"),
        "formats": _formats(df, "plays", min_channels=1),  # your own topics that beat your normal more than once
    }


def analyze_engagement(posts: pd.DataFrame, source: str) -> dict:
    """Competitor posts (watch) or hand-logged Reels (log). Uses views when present, else engagement."""
    df = posts.copy()
    df["engagement"] = df[["reactions", "comments", "shares"]].fillna(0).sum(axis=1)
    has_views = "views" in df and df["views"].fillna(0).sum() > 0
    metric = "views" if has_views else "engagement"
    df["outlier"] = _outlier(df, metric)
    if df["outlier"].isna().all() and df["followers"].fillna(0).sum() > 0:   # few posts per page: relative to audience
        df["outlier"] = df[metric] / (df["followers"].clip(lower=100) * (0.5 if has_views else 0.01))
    df["shares_per_100"] = 100 * df["shares"].fillna(0) / df["engagement"].clip(lower=1)
    by_type = {t: {"posts": int(len(g)), f"median_{metric}": int(g[metric].median()),
                   "median_outlier": None if g["outlier"].isna().all() else round(float(g["outlier"].median()), 2)}
               for t, g in df.groupby("type")}
    cols = ["url", "page", "followers", "type", "caption", metric, "reactions", "comments", "shares", "outlier", "created"]
    cols = [c for c in cols if c in df]
    return {
        "source": source, "metric": metric, "posts": int(len(df)), "pages": int(df["page_id"].nunique()),
        "by_type": by_type,
        "breakouts": df[df["outlier"] >= OUTLIER].sort_values("outlier", ascending=False).head(20)[cols].round(2).to_dict("records"),
        "most_shared": df.sort_values("shares_per_100", ascending=False).head(8)[cols].round(2).to_dict("records"),
        "formats": _formats(df, metric),
        "lengths": _length_table(df, metric) if "length_s" in df else [],
        "note": ("Views aren't public for other Pages, so posts are ranked by reactions + comments + shares "
                 "against that Page's own normal. Shares matter most on Facebook because they drive distribution.")
                if not has_views else "Ranked by views against each Page's own normal.",
    }


def watch_frame(data: dict) -> pd.DataFrame:
    rows = []
    for pid, d in data.items():
        info = d["page"]
        for p in d["posts"]:
            att = ((p.get("attachments") or {}).get("data") or [{}])[0]
            mt = (att.get("media_type") or att.get("type") or "text").lower()
            rows.append({"page_id": pid, "page": info.get("name"), "followers": info.get("followers_count") or info.get("fan_count") or 0,
                         "url": p.get("permalink_url", ""), "caption": p.get("message", ""), "created": p.get("created_time"),
                         "type": "video" if "video" in mt else ("photo" if "photo" in mt or "album" in mt else "text/link"),
                         "reactions": (p.get("reactions") or {}).get("summary", {}).get("total_count", 0),
                         "comments": (p.get("comments") or {}).get("summary", {}).get("total_count", 0),
                         "shares": (p.get("shares") or {}).get("count", 0)})
    return pd.DataFrame(rows)


def log_template(path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(LOG_COLUMNS)
        w.writerow(["https://www.facebook.com/reel/123", "Example Page", 250000, "2026-10-20", 1200000, 35000, 900, 4200,
                    28, "reel", "When the landlord finds out about the new tenant"])
    return path


def log_frame(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in ("page", "reactions", "comments", "shares") if c not in df]
    if missing:
        raise ValueError(f"{path} is missing columns {missing}. Expected: {', '.join(LOG_COLUMNS)}")
    df = df[~df["url"].astype(str).str.contains("/reel/123$", regex=True)] if "url" in df else df  # drop the example row
    df["page_id"] = df["page"]
    df["followers"] = pd.to_numeric(df.get("page_followers", 0), errors="coerce").fillna(0)
    df["created"] = df.get("posted")
    df["type"] = df.get("type", "reel").fillna("reel").str.lower()
    for c in ("views", "reactions", "comments", "shares", "length_s"):
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else np.nan
    df["caption"] = df.get("caption", "").fillna("")
    return df
