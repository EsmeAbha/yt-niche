"""Comment mining: what the audience asks for, praises, complains about.

Rule-based intent tags, then the real comments ranked by likes. No topic clustering: on short,
slangy, mixed-language comments it produces word salad. The ideas stage hands these comments to
the LLM, which reads them properly.
"""
from __future__ import annotations

import re
from collections import Counter

INTENTS = {
    "request": r"\b(please make|make a video|do a video|can you (make|do|show)|part ?2|next video|more of|do one on|you should)\b",
    "question": r"\?|\b(how (do|did|can|to)|what (is|app|software|tool)|which|where (can|do|did)|is it)\b",
    "praise": r"\b(love|amazing|best|great|awesome|helpful|underrated|legend|thank|goat|subscribed)\b",
    "complaint": r"\b(clickbait|boring|fake|waste|misleading|too long|annoying|ai generated|ai slop|scam|dislike)\b",
    "humor": r"(😂|🤣|💀|\blol\b|\blmao\b|\bhaha|\bdead\b)",
    "relatable": r"\b(literally me|so true|me when|this is me|relatable|same here|every time)\b",
}


def _clean(t: str) -> str:
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"@\S+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def analyze_comments(comments: list[dict], cfg: dict | None = None) -> dict:
    if not comments:
        return {"total": 0, "intents": {}, "top_requests": [], "top_questions": [], "top_liked": []}
    for c in comments:
        c["clean"] = _clean(c["text"])
        c["intents"] = [n for n, p in INTENTS.items() if re.search(p, c["clean"], re.I)]

    intent_counts = Counter(i for c in comments for i in c["intents"])
    total = len(comments)

    def top(intent, n=12):
        rows = [c for c in comments if intent in c["intents"] and 15 <= len(c["clean"]) <= 300]
        return [{"text": c["clean"], "likes": c["likes"]} for c in sorted(rows, key=lambda c: -c["likes"])[:n]]

    return {
        "total": total,
        "intents": {k_: {"count": v, "pct": round(100 * v / total, 1)} for k_, v in intent_counts.most_common()},
        "top_requests": top("request"),
        "top_questions": top("question"),
        "top_complaints": top("complaint", 8),
        "top_liked": [{"text": c["clean"], "likes": c["likes"]}
                      for c in sorted(comments, key=lambda c: -c["likes"])[:10]],
    }

