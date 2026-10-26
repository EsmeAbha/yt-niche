"""Trending research: find videos that are really performing now, measure them honestly, explain why.

Every number carries where it came from:
  verified  - read from the platform's API right now (YouTube views, likes, comments, subscribers, dates)
  measured  - computed from two of our own snapshots of the same video (real growth between checks)
  derived   - plain arithmetic on verified numbers (views per hour since upload, ratios); formula shown
  entered   - typed in by you (Facebook Reels; Meta gives no public view counts for other Pages)
  inferred  - an AI reading of title, description, transcript and comments; never presented as data
  unavailable - not exposed by the platform (YouTube shares, retention of other people's videos)
Nothing is ever filled in with a guess.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .llm import chat_json
from .youtube_api import YouTube

UNAVAILABLE = "Data unavailable"

# Content types from the brief -> extra search words. Kept short: YouTube search matches titles and tags.
CONTENT_TYPES = {
    "Kids songs & rhymes": "nursery rhymes kids songs", "Colors song": "colors song for kids",
    "ABC / alphabet": "abc song phonics for kids", "Numbers / counting": "counting numbers song for kids",
    "Baby & toddler": "baby songs toddler learning",
    "AI cinematic": "AI cinematic video", "Interesting facts": "facts you didn't know", "Animals": "animals",
    "Emotional stories": "emotional story", "Motivation": "motivational", "Educational": "explained",
    "Satisfying": "satisfying", "Before & after": "before and after transformation", "Mystery": "mystery unsolved",
    "Documentary": "documentary", "Science & tech": "science technology", "History": "history",
    "Storytelling": "story animation", "Visual experiments": "experiment",
}
# YouTube category ids (videos.list chart=mostPopular supports these per region)
YT_CATEGORIES = {"Any": None, "Film & Animation": "1", "Music": "10", "Pets & Animals": "15", "Sports": "17",
                 "Gaming": "20", "People & Blogs": "22", "Comedy": "23", "Entertainment": "24",
                 "News & Politics": "25", "Howto & Style": "26", "Education": "27", "Science & Technology": "28"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _yt(cfg) -> YouTube:
    yc = cfg.get("youtube", {})
    return YouTube(yc.get("api_key", ""), cfg["_output"] / "_cache", cache_hours=yc.get("cache_hours", 12))


def _dir(cfg) -> Path:
    d = cfg["_output"] / "trending"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- YouTube search
def search_youtube(cfg: dict, query: str = "", fmt: str = "any", after: datetime | None = None,
                   before: datetime | None = None, region: str | None = None, category: str | None = None,
                   pages: int = 1, chart: bool = False) -> tuple[list[dict], int]:
    """Videos with verified stats. chart=True reads YouTube's own Trending chart (1 quota unit) instead of search.
    Returns (videos, quota units used)."""
    yt = _yt(cfg)
    if chart or not query.strip():
        d = yt._get("videos", part="snippet,statistics,contentDetails", chart="mostPopular", maxResults=50,
                    regionCode=region or "US", videoCategoryId=category)
        vids = [yt._flatten_video(v) for v in d.get("items", [])]
        for v in vids:
            v["on_trending_chart"] = True
    else:
        dur = {"shorts": "short", "long": None}.get(fmt)
        ids, token = [], None
        for _ in range(pages):
            d = yt._get("search", part="snippet", q=query, type="video", order="viewCount", maxResults=50,
                        publishedAfter=after.strftime("%Y-%m-%dT%H:%M:%SZ") if after else None,
                        publishedBefore=before.strftime("%Y-%m-%dT%H:%M:%SZ") if before else None,
                        videoDuration=dur, regionCode=region, videoCategoryId=category, pageToken=token)
            ids += [i["id"]["videoId"] for i in d.get("items", []) if i.get("id", {}).get("videoId")]
            token = d.get("nextPageToken")
            if not token:
                break
        vids = yt.videos(list(dict.fromkeys(ids)))
    if fmt == "shorts":
        vids = [v for v in vids if v["is_short"]]
    elif fmt == "long":
        vids = [v for v in vids if not v["is_short"]]
    if after:
        vids = [v for v in vids if _pub(v) >= after]
    chans = yt.channels([v["channel_id"] for v in vids if v.get("channel_id")])
    for v in vids:
        ch = chans.get(v.get("channel_id"), {})
        v["platform"] = "YouTube"
        v["subscribers"] = None if ch.get("hidden_subs") or not ch else ch.get("subscribers")
        v["shares"] = None  # YouTube's API does not expose share counts
    enrich(cfg, vids)
    return vids, yt.units_used


def _pub(v) -> datetime:
    return datetime.fromisoformat(str(v["published_at"]).replace("Z", "+00:00"))


# ---------------------------------------------------------------- metrics
def _snap_path(cfg) -> Path:
    return _dir(cfg) / "snapshots.json"


def _record(cfg, vids: list[dict]) -> dict:
    """Keep a views history per video so growth is measured, not guessed. Returns the history."""
    p = _snap_path(cfg)
    hist = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    ts = _now().isoformat()
    for v in vids:
        if v.get("platform") != "YouTube":
            continue
        h = hist.setdefault(v["video_id"], [])
        if not h or (_now() - datetime.fromisoformat(h[-1][0])).total_seconds() > 600:
            h.append([ts, v["views"]])
        del h[:-20]
    p.write_text(json.dumps(hist), encoding="utf-8")
    return hist


def _pct_rank(values: list[float | None]) -> list[float | None]:
    ok = sorted(x for x in values if x is not None)
    if not ok:
        return [None] * len(values)
    return [None if x is None else sum(y <= x for y in ok) / len(ok) for x in values]


def enrich(cfg: dict, vids: list[dict]) -> None:
    """Add derived/measured metrics, a status with its reason, and the explained viral-potential score."""
    if not vids:
        return
    hist = _record(cfg, vids)
    now = _now()
    for v in vids:
        age_h = max((now - _pub(v)).total_seconds() / 3600, 1.0)
        v["age_hours"] = round(age_h, 1)
        views = v.get("views")
        v["views_per_hour"] = round(views / age_h, 1) if views is not None else None
        v["views_per_day"] = round(views / age_h * 24) if views is not None else None
        eng = [x for x in (v.get("likes"), v.get("comments"), v.get("shares")) if x is not None]
        v["engagement_rate"] = round(sum(eng) / views * 100, 2) if views and eng else None
        v["like_rate"] = round(v["likes"] / views * 100, 2) if views and v.get("likes") is not None else None
        v["comment_rate"] = round(v["comments"] / views * 100, 3) if views and v.get("comments") is not None else None
        v["share_rate"] = round(v["shares"] / views * 100, 3) if views and v.get("shares") is not None else None
        subs = v.get("subscribers")
        v["views_vs_subs"] = round(views / subs, 2) if views is not None and subs else None
        # real growth between two of our own checks, at least 1 hour apart
        v["growth_per_hour"] = None
        h = hist.get(v.get("video_id", ""), [])
        if len(h) >= 2:
            (t0, v0), (t1, v1) = h[0], h[-1]
            dt = (datetime.fromisoformat(t1) - datetime.fromisoformat(t0)).total_seconds() / 3600
            if dt >= 1:
                v["growth_per_hour"] = round((v1 - v0) / dt, 1)
                v["growth_window_h"] = round(dt, 1)
    # comparable = same platform and same format among these results
    for key in {(v.get("platform"), v.get("is_short")) for v in vids}:
        group = [v for v in vids if (v.get("platform"), v.get("is_short")) == key and v.get("views") is not None]
        med = statistics.median([v["views"] for v in group]) if group else 0
        for v in group:
            v["views_vs_median"] = round(v["views"] / med, 2) if med else None
    vph = _pct_rank([v.get("views_per_hour") for v in vids])
    rel = _pct_rank([v.get("views_vs_subs") if v.get("views_vs_subs") is not None else v.get("views_vs_median") for v in vids])
    er = _pct_rank([v.get("engagement_rate") for v in vids])
    top_vph = sorted([x for x in (v.get("views_per_hour") for v in vids) if x is not None], reverse=True)
    q75 = top_vph[len(top_vph) // 4] if top_vph else None
    for v, a, b, c in zip(vids, vph, rel, er):
        parts = [(a, 0.5), (b, 0.3), (c, 0.2)]
        have = [(x, w) for x, w in parts if x is not None]
        v["viral_potential"] = round(100 * sum(x * w for x, w in have) / sum(w for _, w in have)) if have else None
        v["status"], v["status_reason"] = _status(v, q75)


def _status(v: dict, q75: float | None) -> tuple[str, str]:
    views, age_h, vph, g = v.get("views") or 0, v["age_hours"], v.get("views_per_hour"), v.get("growth_per_hour")
    if g is not None and vph:
        if g >= 1.5 * vph:
            return "Rapidly growing", f"measured {g:,.0f} views/h over the last {v['growth_window_h']}h, above its {vph:,.0f}/h average"
        if g <= 0.3 * vph and age_h > 48:
            return "Declining", f"measured {g:,.0f} views/h now vs {vph:,.0f}/h average since upload"
    if v.get("on_trending_chart"):
        return "Currently trending", "on YouTube's own Trending chart right now"
    if views >= 1_000_000 and age_h <= 24 * 30:
        return "Already viral", f"{views:,} views in {age_h / 24:.0f} days"
    if age_h <= 24 * 7 and q75 and vph and vph >= q75:
        return "Currently trending", f"uploaded {age_h / 24:.1f} days ago, top-quarter views/hour in these results"
    if age_h <= 72 and (v.get("views_vs_subs") or 0) >= 1:
        return "Emerging", f"new ({age_h:.0f}h old) and already has more views than its channel has subscribers"
    if age_h > 24 * 180 and views >= 100_000:
        return "Evergreen", f"{age_h / 24 / 30:.0f} months old and still among the top results"
    return "Steady", "no strong signal either way"


# ---------------------------------------------------------------- search interest
def search_interest(query: str, lang: str = "en") -> dict:
    """Real autocomplete phrases from YouTube and Google. They show what people type, not how many people;
    Google Trends has no free official API, so search volume is reported as unavailable."""
    def suggest(q, ds):
        try:
            r = requests.get("https://suggestqueries.google.com/complete/search",
                             params={"client": "firefox", "ds": ds, "q": q, "hl": lang}, timeout=8)
            return r.json()[1] if r.ok else []
        except (requests.RequestException, ValueError, IndexError):
            return []
    yt = suggest(query, "yt")
    questions = []
    for w in ("how", "why", "what"):
        questions += [s for s in suggest(f"{w} {query}", "yt") if s.startswith(w)]
    return {"youtube_suggestions": yt, "google_suggestions": suggest(query, ""), "questions": questions[:12],
            "search_volume": UNAVAILABLE,
            "basis": "Live YouTube/Google autocomplete: phrases people are typing now. Volume is not published."}


# ---------------------------------------------------------------- Facebook (entered by you)
FB_FIELDS = ["url", "page", "page_followers", "posted", "views", "reactions", "comments", "shares", "length_s", "caption"]


def fb_entries(cfg) -> list[dict]:
    p = _dir(cfg) / "facebook.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def fb_save(cfg, rows: list[dict]) -> None:
    (_dir(cfg) / "facebook.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def fb_as_videos(cfg, query: str = "") -> list[dict]:
    out = []
    for i, r in enumerate(fb_entries(cfg)):
        if query and not any(w.lower() in (r.get("caption", "") + " " + r.get("page", "")).lower() for w in query.split()):
            continue
        posted = r.get("posted") or _now().isoformat()
        out.append({"video_id": f"fb{i}", "platform": "Facebook", "url": r.get("url"), "title": r.get("caption") or "(no caption)",
                    "description": r.get("caption", ""), "channel_title": r.get("page"), "published_at": posted,
                    "thumbnail": None, "duration_s": int(r.get("length_s") or 0),
                    "is_short": int(r.get("length_s") or 0) <= 90, "views": r.get("views"),
                    "likes": r.get("reactions"), "comments": r.get("comments"), "shares": r.get("shares"),
                    "subscribers": r.get("page_followers"), "entered": True})
    enrich(cfg, out)
    return out


# ---------------------------------------------------------------- deep look at one video
def transcript(video_id: str, seconds: int | None = None) -> list[dict] | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        t = YouTubeTranscriptApi().fetch(video_id, languages=["en", "en-US", "en-GB", "de", "fr", "es", "ja", "bn", "pt", "hi"])
        rows = [{"start": round(s.start, 1), "text": s.text} for s in t]
    except Exception:  # noqa: BLE001  no captions, blocked, or library missing
        return None
    return [r for r in rows if seconds is None or r["start"] <= seconds]


def video_evidence(cfg: dict, v: dict) -> dict:
    """Everything we can actually read about a video, each piece labelled."""
    ev = {"title": v.get("title"), "description": (v.get("description") or "")[:1500], "tags": v.get("tags", []),
          "duration_s": v.get("duration_s"), "format": "short/vertical" if v.get("is_short") else "long/horizontal",
          "platform": v.get("platform"), "channel": v.get("channel_title")}
    if v.get("platform") == "YouTube":
        tr = transcript(v["video_id"])
        ev["transcript_opening"] = " ".join(r["text"] for r in tr if r["start"] <= 20) if tr else None
        ev["transcript"] = " ".join(f"[{r['start']:.0f}s] {r['text']}" for r in tr)[:6000] if tr else None
        try:
            ev["top_comments"] = [c["text"][:300] for c in _yt(cfg).comments(v["video_id"], 40)][:40]
        except Exception:  # noqa: BLE001
            ev["top_comments"] = []
    else:
        ev["transcript"], ev["top_comments"] = None, []
    ev["sources"] = {"transcript": "auto captions" if ev.get("transcript") else UNAVAILABLE,
                     "comments": f"{len(ev['top_comments'])} top comments" if ev["top_comments"] else UNAVAILABLE}
    return ev


ANALYSIS_KEYS = ["central_idea", "topic", "target_audience", "opening_hook", "visual_style", "story_structure",
                 "scene_sequence", "pacing", "camera_angles", "camera_movement", "lighting", "environment",
                 "characters_or_objects", "narration", "sound_effects", "music", "editing", "transitions",
                 "emotional_impact", "ending", "call_to_action", "why_it_performs"]


def analyze_video(cfg: dict, v: dict, ev: dict) -> dict:
    numbers = {k: v.get(k) for k in ("views", "likes", "comments", "shares", "subscribers", "age_hours",
                                     "views_per_hour", "engagement_rate", "views_vs_subs", "views_vs_median", "status")}
    out = chat_json(cfg,
        "You analyse why videos perform well, for a creator who will make an original video inspired by them. "
        "You have NOT watched the video. You only have its title, description, tags, transcript and comments. "
        "For every point say whether it is 'verified' (stated in the transcript/description/comments) or "
        "'inferred' (your reasonable reading). Never invent numbers. JSON only.",
        f"VIDEO NUMBERS (verified from the platform): {json.dumps(numbers)}\n\nEVIDENCE:\n{json.dumps(ev, ensure_ascii=False)[:9000]}\n\n"
        "Return JSON: {" + ", ".join(f'"{k}": {{"text": "...", "basis": "verified|inferred"}}' for k in ANALYSIS_KEYS) +
        ', "hook_structure": "e.g. mystery question / shocking visual / transformation", "hook_score": 1-10, '
        '"viewer_themes": ["what commenters talk about or ask for"], "viewer_requests": ["..."], '
        '"quality_notes": "what can be judged about production quality from the evidence, else say unknown", '
        '"retention_drivers": ["observable things that keep people watching"]}', 0.3)
    return out if isinstance(out, dict) else {}


def rate_hooks(cfg: dict, vids: list[dict]) -> dict[str, dict]:
    """Hook and quality reading for several videos from their opening transcript and title (inferred)."""
    items = []
    for v in vids:
        tr = transcript(v["video_id"], 15) if v.get("platform") == "YouTube" else None
        items.append({"id": v["video_id"], "title": v.get("title"), "opening": " ".join(r["text"] for r in tr) if tr else None,
                      "description": (v.get("description") or "")[:300]})
    out = chat_json(cfg, "You judge video hooks. You have only titles and the first seconds of transcript. JSON only.",
                    "For each video rate the hook 1-10 and name its structure. If opening is null, judge from the title only "
                    "and say so.\n" + json.dumps(items, ensure_ascii=False) +
                    '\nReturn {"videos": [{"id": "...", "hook_score": 7, "hook_structure": "...", "why": "one line", '
                    '"quality_guess": "one line on likely production quality", "from_transcript": true}]}', 0.2)
    rows = out.get("videos", []) if isinstance(out, dict) else []
    return {r["id"]: r for r in rows if isinstance(r, dict) and r.get("id")}


# ---------------------------------------------------------------- idea + research (modes A/C)
def research_idea(cfg: dict, idea: str, platforms: list[str], fmt: str = "any", days: int = 30,
                  region: str | None = None) -> dict:
    q = chat_json(cfg, "You turn a video idea into YouTube search phrases. JSON only.",
                  f"Idea: {idea}\nGive 2 short search phrases (2-4 words each) that find similar popular videos.\n"
                  'Return {"queries": ["...", "..."]}', 0.2)
    queries = [x for x in (q.get("queries", []) if isinstance(q, dict) else []) if isinstance(x, str)][:2] or [idea[:60]]
    vids, units = [], 0
    if "YouTube" in platforms:
        after = _now() - timedelta(days=days)
        for query in queries:
            got, u = search_youtube(cfg, query, fmt, after=after, region=region)
            vids += got
            units += u
    if "Facebook" in platforms:
        for query in queries:
            vids += fb_as_videos(cfg, query)
    seen, uniq = set(), []
    for v in sorted(vids, key=lambda v: -(v.get("views") or 0)):
        if v["video_id"] not in seen:
            seen.add(v["video_id"])
            uniq.append(v)
    top = uniq[:12]
    interest = search_interest(queries[0])
    comments = []
    for v in [v for v in top if v["platform"] == "YouTube"][:3]:
        try:
            comments += [c["text"][:200] for c in _yt(cfg).comments(v["video_id"], 20)]
        except Exception:  # noqa: BLE001
            pass
    lengths = [v["duration_s"] for v in top if v.get("duration_s")]
    facts = [{"title": v["title"], "platform": v["platform"], "views": v.get("views"), "views_per_hour": v.get("views_per_hour"),
              "age_days": round(v["age_hours"] / 24, 1), "engagement_rate_pct": v.get("engagement_rate"),
              "views_vs_subs": v.get("views_vs_subs"), "duration_s": v.get("duration_s"), "status": v.get("status")} for v in top]
    brief = chat_json(cfg,
        "You are a video strategist. Use ONLY the data given; do not invent numbers. When the data cannot answer "
        "a question, say 'not enough data'. Keep the creator's core idea. JSON only.",
        f"CREATOR'S IDEA: {idea}\nSEARCHES: {queries} (last {days} days)\nTOP VIDEOS (verified numbers): "
        f"{json.dumps(facts, ensure_ascii=False)}\nSEARCH PHRASES PEOPLE TYPE: {json.dumps(interest, ensure_ascii=False)}\n"
        f"VIEWER COMMENTS: {json.dumps(comments[:50], ensure_ascii=False)}\n\n"
        'Return {"answers": {"is_topic_popular": "...", "are_people_searching": "...", "similar_videos_views": "...", '
        '"best_related_concepts": "...", "successful_hooks": "...", "visual_styles": "...", "common_lengths": "...", '
        '"storytelling": "...", "what_viewers_respond_to": "...", "opportunities": "..."}, '
        '"improved_idea": {"idea": "the creator\'s idea, improved but recognisably the same", "stronger_opening": "...", '
        '"angle": "...", "visual_concept": "...", "story_structure": "...", "emotional_element": "...", '
        '"ending": "...", "title_options": ["...", "..."]}}', 0.4)
    return {"idea": idea, "queries": queries, "platforms": platforms, "days": days, "videos": top, "interest": interest,
            "median_length_s": statistics.median(lengths) if lengths else None, "quota_units": units,
            "brief": brief if isinstance(brief, dict) else {}}
