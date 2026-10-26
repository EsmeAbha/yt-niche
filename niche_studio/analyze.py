"""Stage 2: answer four questions with numbers you can check, not made-up scores.

  1. What does a NEW channel realistically get here?  (small/young channel results, not the mega-hits)
  2. Which formats are proven?   (title concepts that beat the channel's normal on 2+ different channels)
  3. Does it pay?                (RPM by category + audience, sponsor/affiliate presence, top channel income)
  4. Is it allowed?              (YouTube's July 2026 inauthentic-content and distressing-content rules)
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from statistics import median

import numpy as np
import pandas as pd

from . import money
from .comments import analyze_comments

MIN_BASELINE = 5            # uploads of the same format needed to trust a channel's "normal"
OUTLIER = 3.0               # 3x the channel's normal = breakout
YOUNG_DAYS = 365

POLICY_RISKS = [
    (re.compile(r"\b(rescue|abandoned|starving|injured|crying|suffering|hurt|tragic|sad animal)\b", re.I),
     "Distress/rescue bait: YouTube removes whole channels built on this from YPP (July 2026), AI or not."),
    (re.compile(r"\b(financ\w*|invest\w*|stock|crypto|legal|lawyer|doctor|medical|health|diet|cure)\b", re.I),
     "Sensitive topic: AI personas of people giving finance/legal/medical advice aren't monetizable. Use a real voice and real sources."),
    (re.compile(r"\b(kids|nursery|cartoon for kids|toddler|baby songs)\b", re.I),
     "Made-for-kids: no personalized ads, comments off, lowest RPM in the data."),
    (re.compile(r"\b(compilation|reupload|best of|tiktok|movie recap|clips)\b", re.I),
     "Reused content risk: compilations or recaps need clear commentary or new material to stay in YPP."),
]


def _age_days(ts: str, now: datetime) -> float:
    return max((now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 86400, 0.25)


def channel_profiles(raw: dict, now: datetime) -> dict[str, dict]:
    """Per-format baseline, cadence and lower-bound monthly income for channels we sampled."""
    out = {}
    for cid, c in raw["channels"].items():
        ups = c.get("recent_uploads") or []
        shorts = [u["views"] for u in ups if u["is_short"]]
        longs = [u["views"] for u in ups if not u["is_short"]]
        prof = {
            "subscribers": c.get("subscribers", 0),
            "age_days": _age_days(c["created_at"], now) if c.get("created_at") else None,
            "median_short": median(shorts) if len(shorts) >= MIN_BASELINE else None,
            "median_long": median(longs) if len(longs) >= MIN_BASELINE else None,
            "sampled": len(ups),
        }
        if ups:
            dates = sorted(datetime.fromisoformat(u["published_at"].replace("Z", "+00:00")) for u in ups)
            span = max((now - dates[0]).days, 7)
            prof["uploads_per_week"] = round(len(ups) / span * 7, 1)
            last30 = [u for u in ups if (now - datetime.fromisoformat(u["published_at"].replace("Z", "+00:00"))).days <= 30]
            prof["views_last30_uploads"] = sum(u["views"] for u in last30)
            prof["sponsor_share"] = round(np.mean([u.get("has_sponsor", False) for u in ups]), 2)
            prof["affiliate_share"] = round(np.mean([u.get("has_affiliate", False) for u in ups]), 2)
            prof["product_share"] = round(np.mean([u.get("has_merch_or_product", False) for u in ups]), 2)
            prof["last30"] = last30
        out[cid] = prof
    return out


def build_frame(raw: dict, cfg: dict, profiles: dict, velocity: dict) -> pd.DataFrame:
    now = datetime.fromisoformat(raw["scanned_at"])
    df = pd.DataFrame(raw["videos"])
    if df.empty:
        return df
    df["age_days"] = df["published_at"].map(lambda t: _age_days(t, now))
    df["lifetime_vpd"] = df["views"] / df["age_days"]
    df["measured_vpd"] = df["video_id"].map(lambda v: velocity.get(v, {}).get("measured_vpd"))
    df["acceleration"] = df["video_id"].map(lambda v: velocity.get(v, {}).get("acceleration"))
    df["engagement"] = (df["likes"] + df["comments"]) / df["views"].clip(lower=1)
    df["subscribers"] = df["channel_id"].map(lambda c: raw["channels"].get(c, {}).get("subscribers", 0))
    df["channel_age_days"] = df["channel_id"].map(lambda c: (profiles.get(c) or {}).get("age_days"))

    def baseline(r):
        p = profiles.get(r["channel_id"]) or {}
        return p.get("median_short") if r["is_short"] else p.get("median_long")
    df["baseline"] = df.apply(baseline, axis=1)
    df["outlier"] = np.where(df["baseline"].fillna(0) > 0, df["views"] / df["baseline"].replace(0, np.nan), np.nan)
    df["format"] = np.where(df["is_short"], "Shorts", "Long-form")
    df["bucket"] = df.apply(lambda r: money.bucket_for(r, raw["niche"]), axis=1)
    # A market scan searched that country's YouTube in its language, so treat its viewers as that market.
    df["audience"] = raw["market"] if raw.get("market") else df.apply(lambda r: money.audience_for(r), axis=1)
    rev = df.apply(lambda r: money.revenue_range(cfg, r["views"], r["bucket"], r["audience"], r["is_short"]), axis=1)
    df["rev_low"] = [x[0] for x in rev]
    df["rev_high"] = [x[1] for x in rev]
    df["small_or_new"] = (df["subscribers"] < 10_000) | (df["channel_age_days"].fillna(9999) < YOUNG_DAYS)
    return df


def _views(d: pd.DataFrame) -> dict:
    if d.empty:
        return {}
    small = d[d["small_or_new"]]
    return {
        "videos": int(len(d)), "channels": int(d["channel_id"].nunique()),
        "max_views": int(d["views"].max()), "p90_views": int(d["views"].quantile(0.9)),
        "median_views": int(d["views"].median()),
        "new_channel_p25": int(small["views"].quantile(0.25)) if len(small) >= 5 else int(d["views"].quantile(0.1)),
        "new_channel_median": int(small["views"].median()) if len(small) >= 5 else None,
        "new_channel_p75": int(small["views"].quantile(0.75)) if len(small) >= 5 else None,
        "new_channel_sample": int(len(small)),
        "median_duration_s": int(d["duration_s"].median()),
        "median_engagement_pct": round(100 * d["engagement"].median(), 2),
    }


def proven_formats(d: pd.DataFrame, min_channels: int = 2) -> list[dict]:
    """Group breakout titles by concept; keep only concepts that broke out on 2+ different channels.
    One channel's hit can be luck or an existing fanbase. The same idea working for different
    channels is a format you can reuse."""
    hits = d[d["outlier"] >= OUTLIER].reset_index(drop=True)
    if len(hits) < 4:
        return []
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, token_pattern=r"(?u)[^\W\d_][\w\u0900-\u0DFF]+",
                          stop_words="english", sublinear_tf=True)
    try:
        X = vec.fit_transform(hits["title"].str.lower()).toarray()
    except ValueError:
        return []
    labels = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                     distance_threshold=0.75).fit_predict(X)
    terms = vec.get_feature_names_out()
    out = []
    for lab in set(labels):
        g = hits[labels == lab]
        if g["channel_id"].nunique() < min_channels:
            continue
        centroid = X[labels == lab].mean(axis=0)
        out.append({
            "concept": ", ".join(terms[i] for i in centroid.argsort()[::-1][:4]),
            "channels": int(g["channel_id"].nunique()), "breakouts": int(len(g)),
            "median_outlier": round(float(g["outlier"].median()), 1),
            "median_views": int(g["views"].median()),
            "formats": dict(Counter(g["format"])),
            "examples": g.sort_values("outlier", ascending=False).head(4)[
                ["title", "url", "channel_title", "views", "outlier", "subscribers"]].round({"outlier": 1}).to_dict("records"),
        })
    return sorted(out, key=lambda f: (-f["channels"], -f["median_outlier"]))


def _duration(d: pd.DataFrame, short: bool) -> list[dict]:
    d = d[d["outlier"].notna()]
    if len(d) < 10:
        return []
    bins = [0, 20, 40, 60, 180] if short else [0, 300, 600, 900, 1200, 1800, 10**6]
    labels = ["0-20s", "20-40s", "40-60s", "60-180s"] if short else ["<5m", "5-10m", "10-15m", "15-20m", "20-30m", "30m+"]
    g = d.assign(b=pd.cut(d["duration_s"], bins=bins, labels=labels, include_lowest=True))
    res = g.groupby("b", observed=True).agg(n=("views", "size"), mo=("outlier", "median"), mv=("views", "median"))
    return [{"bucket": str(k), "videos": int(r.n), "median_outlier": round(float(r.mo), 2), "median_views": int(r.mv)}
            for k, r in res.iterrows() if r.n >= 3]


def _money(df: pd.DataFrame, profiles: dict, raw: dict, cfg: dict) -> dict:
    bucket = df["bucket"].mode().iat[0]
    mix = (df.groupby("audience")["views"].sum() / max(df["views"].sum(), 1)).round(3)
    audience = mix.idxmax()
    lo_l, hi_l, lo_s, hi_s, src = money.rpm_table(cfg)[bucket][:5]
    geo = money.geo_table(cfg)
    g = float(sum(geo[k] * v for k, v in mix.items()))  # view-weighted blend of audience ad rates
    prof = [p for p in profiles.values() if p.get("sampled")]

    econ = []
    for cid, p in profiles.items():
        if not p.get("last30"):
            continue
        lo = hi = 0.0
        for u in p["last30"]:
            b = money.bucket_for(u, raw["niche"])
            a, z = money.revenue_range(cfg, u["views"], b, "tier1_english", u["is_short"])
            a, z = a * g, z * g
            lo, hi = lo + a, hi + z
        ch = raw["channels"][cid]
        econ.append({"channel": ch["title"], "subscribers": ch["subscribers"],
                     "age_months": round(p["age_days"] / 30.4) if p.get("age_days") else None,
                     "uploads_per_week": p.get("uploads_per_week"),
                     "median_short": int(p["median_short"]) if p.get("median_short") else None,
                     "median_long": int(p["median_long"]) if p.get("median_long") else None,
                     "views_from_last30_uploads": p["views_last30_uploads"],
                     "ad_rev_month_low": round(lo), "ad_rev_month_high": round(hi),
                     "sponsors": bool(p.get("sponsor_share", 0) >= 0.10),
                     "affiliate": bool(p.get("affiliate_share", 0) >= 0.20),
                     "own_product": bool(p.get("product_share", 0) >= 0.20)})
    econ.sort(key=lambda e: -e["ad_rev_month_high"])

    def share(key, min_share):
        # a channel counts only if it does this regularly, not once
        return round(100 * np.mean([p.get(key, 0) >= min_share for p in prof]), 1) if prof else 0.0

    per_format = {}
    for f, short in (("Shorts", True), ("Long-form", False)):
        sub = df[df["is_short"] == short]
        if sub.empty:
            continue
        nm = sub[sub["small_or_new"]]["views"].median() if sub["small_or_new"].sum() >= 5 else sub["views"].quantile(0.25)
        lo, hi = (lo_s, hi_s) if short else (lo_l, hi_l)
        per_format[f] = {"rpm_low": round(lo * g, 3), "rpm_high": round(hi * g, 3),
                         "typical_new_video_views": int(nm),
                         "typical_new_video_usd": [round(nm / 1000 * lo * g, 2), round(nm / 1000 * hi * g, 2)],
                         "p90_video_usd": [round(sub["views"].quantile(.9) / 1000 * lo * g, 2),
                                           round(sub["views"].quantile(.9) / 1000 * hi * g, 2)]}
    return {
        "category": bucket, "audience": audience, "audience_mix": mix.to_dict(), "geo_multiplier": round(g, 3), "rpm_source": src,
        "per_format": per_format,
        "channels_with_sponsors_pct": share("sponsor_share", 0.10),
        "channels_with_affiliate_pct": share("affiliate_share", 0.20),
        "channels_selling_own_product_pct": share("product_share", 0.20),
        "channel_economics": econ[:15],
        "note": "Ad revenue counts only views on uploads from the last 30 days, so it's a lower bound. "
                "Sponsors, affiliates and products often earn more than ads, especially for Shorts.",
    }


def _entry(df: pd.DataFrame, profiles: dict) -> dict:
    young = df[(df["channel_age_days"].fillna(9999) < YOUNG_DAYS)]
    thresh = {True: 100_000, False: 20_000}
    young_hits = young[young.apply(lambda r: r["views"] >= thresh[r["is_short"]], axis=1)] if len(young) else young
    share = df.groupby("channel_id")["views"].sum().sort_values(ascending=False)
    return {
        "young_channels": int(young["channel_id"].nunique()),
        "young_channel_hits": int(young_hits["channel_id"].nunique()) if len(young_hits) else 0,
        "young_hit_examples": young_hits.sort_values("views", ascending=False).head(5)[
            ["title", "url", "channel_title", "subscribers", "views", "channel_age_days"]]
            .assign(channel_age_days=lambda x: x["channel_age_days"].round()).to_dict("records") if len(young_hits) else [],
        "top5_view_share_pct": round(100 * float(share.head(5).sum() / max(share.sum(), 1)), 1),
        "hit_threshold": "100K views for a Short, 20K for long-form, from a channel under 12 months old",
    }


def _verdict(a: dict) -> list[dict]:
    """Plain pass/warn/fail checks with the reason behind each. No hidden weights."""
    out = []

    def add(level, area, text):
        out.append({"level": level, "area": area, "text": text})
    pf = a["money"]["per_format"]
    lf = pf.get("Long-form")
    if lf and lf["rpm_high"] >= 3:
        add("pass", "Money", f"Long-form pays: about ${lf['rpm_low']:.2f}-${lf['rpm_high']:.2f} per 1K views for this audience.")
    elif lf:
        add("warn", "Money", f"Low long-form RPM (${lf['rpm_low']:.2f}-${lf['rpm_high']:.2f}). You'll need volume, or sponsors and products.")
    if "Shorts" in pf and (not lf or a["formats"].get("Long-form", {}).get("videos", 0) < 10):
        add("warn", "Money", "Mostly Shorts. They pay cents per 1K views, so use them to grow and earn from long-form, sponsors or products.")
    if a["money"]["geo_multiplier"] < 0.3:
        add("warn", "Money", f"This audience pays about {round(a['money']['geo_multiplier'] * 100)}% of US ad rates. "
            "Run `niche markets` to find a higher-paying market for the same format.")
    e = a["entry"]
    if e["young_channel_hits"] >= 2:
        add("pass", "Entry", f"{e['young_channel_hits']} channels under 12 months old already hit ({e['hit_threshold']}).")
    elif e["young_channels"]:
        add("warn", "Entry", "Young channels are present but few are breaking out.")
    else:
        add("fail", "Entry", "No young channels among the results. Established channels own this search space.")
    if e["top5_view_share_pct"] > 80:
        add("warn", "Entry", f"The top 5 channels take {e['top5_view_share_pct']}% of views.")
    n = len(a["proven_formats"])
    add("pass" if n >= 2 else "warn" if n == 1 else "fail", "Repeatable",
        f"{n} format(s) broke out on 2+ different channels." if n else "No format has broken out on more than one channel. Hits here look like luck or existing fanbases.")
    sp = a["money"]["channels_with_sponsors_pct"] + a["money"]["channels_with_affiliate_pct"]
    if sp >= 25:
        add("pass", "Brands", f"Brands already pay here: {a['money']['channels_with_sponsors_pct']}% of sampled channels show sponsors and {a['money']['channels_with_affiliate_pct']}% use affiliate links.")
    else:
        add("warn", "Brands", "Few sponsors or affiliate links. Income would depend almost entirely on ads.")
    for r in a["policy_risks"]:
        add("fail" if "removes" in r else "warn", "Policy", r)
    return out


def analyze(raw: dict, cfg: dict) -> dict:
    from .tracker import velocities
    now = datetime.fromisoformat(raw["scanned_at"])
    profiles = channel_profiles(raw, now)
    try:
        vel = velocities(cfg, raw["niche"]) if "_output" in cfg else {}
    except Exception:
        vel = {}
    df = build_frame(raw, cfg, profiles, vel)
    if df.empty:
        return {"niche": raw["niche"], "error": "No videos found. Try a broader niche term."}

    cols = ["video_id", "url", "title", "channel_title", "subscribers", "views", "lifetime_vpd", "measured_vpd",
            "acceleration", "outlier", "format", "duration_s", "published_at", "rev_low", "rev_high", "thumbnail"]
    breakouts = df[df["outlier"] >= OUTLIER].sort_values("outlier", ascending=False)
    if df["measured_vpd"].notna().sum() >= 5:
        trending = df[df["measured_vpd"].notna()].sort_values("measured_vpd", ascending=False)
        trend_basis = "measured views/day between your last two scans"
    else:
        trending = df[df["age_days"] <= 14].sort_values("lifetime_vpd", ascending=False)
        trend_basis = "average views/day since upload (videos under 14 days old). Run `niche track` daily for measured velocity."

    text = " ".join([raw["niche"]] + df["title"].tolist())
    risks = [msg for pat, msg in POLICY_RISKS
             if pat.search(raw["niche"]) or df["title"].map(lambda t: bool(pat.search(t))).mean() >= 0.2]
    baseline_cov = round(100 * df["outlier"].notna().mean(), 1)

    a = {
        "niche": raw["niche"], "scanned_at": raw["scanned_at"], "lookback_days": raw["lookback_days"],
        "quota_units_used": raw.get("quota_units_used"),
        "overall": _views(df),
        "formats": {f: _views(df[df["format"] == f]) for f in ("Shorts", "Long-form")},
        "baseline_coverage_pct": baseline_cov,
        "proven_formats": proven_formats(df),
        "breakouts": breakouts.head(25)[cols].round(2).to_dict("records"),
        "trending": trending.head(12)[cols].round(2).to_dict("records"),
        "trend_basis": trend_basis,
        "duration": {"Shorts": _duration(df[df["is_short"]], True), "Long-form": _duration(df[~df["is_short"]], False)},
        "entry": _entry(df, profiles),
        "money": _money(df, profiles, raw, cfg),
        "policy_risks": risks,
        "comments": analyze_comments(raw.get("comments", []), cfg),
    }
    a["verdict"] = _verdict(a)
    return a
