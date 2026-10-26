"""Stage 3: turn the analysis into video plans that can stay monetized.

What keeps AI-assisted channels in YPP (July 2026 clarification): every upload has to be visibly
different and show what *you* contributed. So the plans are built around:
  - a series bible (channel/bible.md): your original character, world and running jokes
  - a proven FORMAT from the data, filled with a NEW premise, never a copied title
  - an originality check against your past videos and the niche's top titles
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .llm import chat_json

SYSTEM = """You are the head writer of a YouTube/Facebook channel that uses AI video models for visuals.
Your job is income, so every plan must (1) use a format that the data shows breaking out on several
channels, (2) bring a new premise and real jokes or insight a viewer couldn't get from the existing
videos, and (3) stay monetizable under YouTube's rules. Never produce: template videos that differ only
in surface details, distress/rescue bait, AI people giving finance/legal/medical advice, kids content,
or re-uploads. Long-form is where ad money is; Shorts are for growth and should funnel to long-form
or a series. Write for the target market's culture and language natively, not as a translation.
Each visual_prompt is one renderable 5-8 s shot: subject, action, setting, lighting, camera. Reuse the
bible's character description word for word. Reply with JSON only."""

SCHEMA = """{
 "ideas": [
  {
   "id": 1,
   "format": "short" | "long",
   "proven_format": "which proven format from the data this uses",
   "premise": "the new situation in one sentence",
   "originality": "what this video has that existing videos in the niche don't",
   "title": "...", "alt_titles": ["...", "..."],
   "hook_line": "first 1-2 seconds, spoken or on-screen",
   "why": "2-3 sentences citing the data (outliers, comments, money)",
   "target_duration_s": 35,
   "thumbnail_text": "max 4 words (long-form)",
   "series_link": "how this feeds the series or a long-form video",
   "scenes": [
     {"n": 1, "seconds": 4, "voiceover": "...", "on_screen_text": "...",
      "visual_prompt": "...", "camera": "...", "sfx": "...", "hero": true}
   ],
   "youtube_description": "...", "hashtags": ["#..."], "facebook_caption": "..."
  }
 ]
}"""


def build_brief(a: dict, max_titles: int = 20) -> str:
    def vids(rows):
        return [f"- {r['title']} | {int(r['views']):,} views | {r['outlier']:.1f}x its channel's normal | {r['format']}"
                for r in rows if r.get("outlier") == r.get("outlier") and r.get("outlier") is not None]
    c = a.get("comments", {})
    m = a.get("money", {})
    brief = {
        "niche": a["niche"],
        "verdict": [f"{v['level']}: {v['text']}" for v in a.get("verdict", [])],
        "money": {"category": m.get("category"), "per_format": m.get("per_format"),
                  "sponsor_channels_pct": m.get("channels_with_sponsors_pct")},
        "what_new_channels_get": {k: {kk: v.get(kk) for kk in ("new_channel_median", "new_channel_p75", "median_duration_s")}
                                  for k, v in a["formats"].items() if v},
        "proven_formats": [{"concept": f["concept"], "channels": f["channels"], "median_outlier": f["median_outlier"],
                            "examples": [e["title"] for e in f["examples"][:3]]} for f in a.get("proven_formats", [])[:8]],
        "best_lengths": {k: sorted(v, key=lambda b: -b["median_outlier"])[:2] for k, v in a.get("duration", {}).items() if v},
        "audience_requests": [x["text"] for x in c.get("top_requests", [])[:10]],
        "audience_questions": [x["text"] for x in c.get("top_questions", [])[:8]],
        "audience_complaints": [x["text"] for x in c.get("top_complaints", [])[:6]],
        "policy_risks": a.get("policy_risks", []),
    }
    return ("DATA\n" + json.dumps(brief, ensure_ascii=False, indent=1) +
            "\n\nBREAKOUT VIDEOS (views vs that channel's own normal)\n" + "\n".join(vids(a.get("breakouts", [])[:max_titles])))


def load_bible(cfg: dict) -> str:
    p = cfg["_root"] / cfg.get("channel", {}).get("bible", "channel/bible.md")
    return p.read_text(encoding="utf-8") if p.exists() else ""


def generate_ideas(cfg: dict, analysis: dict, n: int | None = None, fmt: str = "mix",
                   language: str | None = None, extra: str = "", market: str | None = None) -> dict:
    from .money import markets
    ic = cfg.get("ideas", {})
    n = n or ic.get("count", 6)
    mk = markets(cfg).get(market) if market else None
    language = language or (mk or {}).get("language") or ic.get("language", "English")
    hero = cfg.get("video", {}).get("veo_hero_shots_per_video", 2)
    bible = load_bible(cfg)
    fmt_rule = {"short": "All ideas are vertical Shorts/Reels, 20-60 s, each pointing to a series or long video.",
                "long": "All ideas are 16:9 long-form, 8-12 min; script the first 60 s fully and outline the rest as 20-40 s scenes.",
                "mix": "Mix: at least a third long-form (8-12 min, the money), the rest Shorts that funnel to them."}[fmt]
    user = (build_brief(analysis) +
            (f"\n\nSERIES BIBLE (keep everything consistent with this)\n{bible}" if bible else
             "\n\nNo series bible yet: invent ONE original recurring character and use it in every idea.") +
            f"\n\nTASK\nWrite {n} plans. {fmt_rule}\nLanguage of voiceover and on-screen text: {language}"
            + (f" (target market: {market}; write natively for that audience)" if market else "") + ".\n"
            f"Shorts: hook lands in 2 s; scenes 2-6 s; end on a punchline or loop.\n"
            f"Mark at most {hero} scenes per video \"hero\": true (the shots that sell it; made in Veo).\n"
            "Every idea must use a different premise. Don't reuse a title from the data.\n"
            + (f"Extra: {extra}\n" if extra else "") + f"\nReturn JSON in exactly this shape:\n{SCHEMA}")
    out = chat_json(cfg, SYSTEM, user)
    if isinstance(out, list):
        out = {"ideas": out}
    for i, idea in enumerate(out.get("ideas", []), 1):
        idea.setdefault("id", i)
        if market:
            idea["market"] = market
            idea["voice"] = mk["voice"]
            idea["language"] = language
        for j, s in enumerate(idea.get("scenes", []), 1):
            s.setdefault("n", j)
            s.setdefault("seconds", 5)
            s.setdefault("hero", False)
    check_originality(cfg, out, analysis)
    return out


# ---------------- originality guard ----------------

def history_path(cfg) -> Path:
    return cfg["_root"] / cfg.get("channel", {}).get("history", "channel/history.jsonl")


def add_to_history(cfg: dict, idea: dict, status: str):
    p = history_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"title": idea.get("title"), "premise": idea.get("premise", ""), "status": status,
           "text": " ".join(s.get("voiceover", "") for s in idea.get("scenes", []))}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _history(cfg) -> list[dict]:
    p = history_path(cfg)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def check_originality(cfg: dict, ideas: dict, analysis: dict, max_sim: float | None = None) -> None:
    """Flags ideas too close to (a) your own past videos -> 'repetitive' risk, (b) the niche's existing
    top titles -> copy risk, (c) each other. Uses TF-IDF cosine similarity on title + premise + script."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    max_sim = max_sim or cfg.get("channel", {}).get("max_similarity", 0.5)
    items = ideas.get("ideas", [])
    if not items:
        return
    mine = [f"{i.get('title', '')} {i.get('premise', '')} " + " ".join(s.get("voiceover", "") for s in i.get("scenes", []))
            for i in items]
    hist = _history(cfg)
    past = [f"{h['title']} {h.get('premise', '')} {h.get('text', '')}" for h in hist]
    niche_titles = [r["title"] for r in analysis.get("breakouts", [])] + \
                   [e["title"] for f in analysis.get("proven_formats", []) for e in f["examples"]]
    corpus = mine + past + niche_titles
    vec = TfidfVectorizer(ngram_range=(1, 2), token_pattern=r"(?u)[^\W\d_][\wऀ-෿]+", sublinear_tf=True)
    X = vec.fit_transform(corpus)
    M = X[: len(mine)]
    for k, idea in enumerate(items):
        flags = []
        if past:
            s = cosine_similarity(M[k], X[len(mine): len(mine) + len(past)]).ravel()
            j = int(s.argmax())
            if s[j] >= max_sim:
                flags.append(f"{s[j]:.2f} similar to your past video '{hist[j]['title']}'")
        if niche_titles:
            # Swap-one-word copies ("AI chef takes over..." -> "AI robot takes over...") = word-set overlap
            mine_w = set(re.findall(r"[^\W\d_][\w\u0900-\u0DFF]*", idea.get("title", "").lower()))
            best, best_t = 0.0, ""
            for t in niche_titles:
                tw = set(re.findall(r"[^\W\d_][\w\u0900-\u0DFF]*", t.lower()))
                j = len(mine_w & tw) / max(len(mine_w | tw), 1)
                if j > best:
                    best, best_t = j, t
            if best >= 0.6:
                flags.append(f"title {best:.2f} overlaps existing '{best_t}' (one-word swap of someone else's video)")
        if k:  # only compare with earlier ideas, so the first of two near-duplicates survives
            others = cosine_similarity(M[k], M[:k]).ravel()
            if others.max() >= max_sim:
                flags.append(f"{others.max():.2f} similar to idea {items[int(others.argmax())].get('id')} in this batch")
        idea["originality_flags"] = flags
        idea["blocked"] = bool(flags)
