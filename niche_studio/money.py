"""Revenue estimates. Every number here is a range with a source, and you can edit all of them in config.yaml.

RPM = what the creator keeps per 1,000 views, for a mostly tier-1 (US/UK/AU) audience. Then:
  revenue ~ views / 1000 * RPM * audience_geo_multiplier
Sources: AIR Media-Tech 2026 RPM data from 274 channels (marked "AIR"); the rest are marked
"assumption" and are conservative. Audience geography is a guess from the title script and
language, because the API doesn't show another channel's audience countries.
"""
from __future__ import annotations

import re

# (long_low, long_high, shorts_low, shorts_high, source)
DEFAULT_RPM = {
    "finance_business": (8.0, 20.0, 0.15, 0.40, "assumption"),
    "education_science": (8.0, 18.0, 0.30, 1.00, "AIR long-form 14.97-18.23; Shorts implied"),
    "howto_lifestyle": (3.9, 4.9, 0.16, 0.20, "AIR lifestyle"),
    "people_blogs": (2.0, 4.5, 0.05, 0.20, "assumption"),
    "entertainment_comedy": (1.8, 5.0, 0.03, 0.10, "AIR entertainment long-form; Shorts assumption"),
    "gaming": (1.3, 3.4, 0.03, 0.08, "AIR gaming long-form; Shorts assumption"),
    "music": (1.0, 3.0, 0.97, 1.48, "AIR music Shorts"),
    "kids": (0.4, 0.6, 0.02, 0.05, "AIR kids"),
    "other": (2.0, 5.0, 0.03, 0.10, "assumption"),
}
CATEGORY_TO_BUCKET = {
    "27": "education_science", "28": "education_science", "26": "howto_lifestyle", "22": "people_blogs",
    "23": "entertainment_comedy", "24": "entertainment_comedy", "1": "entertainment_comedy",
    "20": "gaming", "10": "music", "15": "other", "17": "other", "19": "howto_lifestyle", "2": "other",
    "25": "other", "29": "other",
}
FINANCE_WORDS = re.compile(r"\b(financ\w*|invest\w*|stock|crypto|bitcoin|trading|insurance|loan|mortgage|tax|"
                           r"real estate|side hustle|business|saas|marketing|software|credit card|budget\w*)\b", re.I)
KIDS_WORDS = re.compile(r"\b(kids|nursery|cocomelon|for children|toddler|baby songs|cartoon for kids)\b", re.I)

# Share of US-level RPM you get from each audience. Anchors: AIR 2026 CPM is $8-20 for US/UK/AU and
# $0.20-1.50 for South Asia/Nigeria/Philippines. The per-market values in between are conservative
# assumptions; edit them in config.yaml (money.geo_multiplier) once you have your own Studio data.
DEFAULT_GEO = {"tier1_english": 1.0, "global_english": 0.55, "south_asia": 0.10, "other": 0.35,
               "us": 1.0, "uk": 0.85, "ca": 0.85, "au": 0.9, "de": 0.8, "nordics": 0.85, "nl": 0.75,
               "ch": 0.95, "fr": 0.6, "jp": 0.6, "kr": 0.5, "es": 0.45, "it": 0.45, "gulf_ar": 0.4,
               "latam_es": 0.15, "br": 0.15, "id": 0.08, "in": 0.08, "bd": 0.06}

# Markets you can target from anywhere. YouTube pays by viewer location, not creator location.
# region = YouTube regionCode for search, lang = relevanceLanguage, voice = edge-tts voice.
DEFAULT_MARKETS = {
    "us": {"region": "US", "lang": "en", "voice": "en-US-AndrewMultilingualNeural", "language": "English"},
    "uk": {"region": "GB", "lang": "en", "voice": "en-GB-RyanNeural", "language": "English (UK)"},
    "au": {"region": "AU", "lang": "en", "voice": "en-AU-WilliamNeural", "language": "English (Australia)"},
    "de": {"region": "DE", "lang": "de", "voice": "de-DE-ConradNeural", "language": "German"},
    "nordics": {"region": "SE", "lang": "sv", "voice": "sv-SE-MattiasNeural", "language": "Swedish"},
    "fr": {"region": "FR", "lang": "fr", "voice": "fr-FR-HenriNeural", "language": "French"},
    "jp": {"region": "JP", "lang": "ja", "voice": "ja-JP-KeitaNeural", "language": "Japanese"},
    "es": {"region": "ES", "lang": "es", "voice": "es-ES-AlvaroNeural", "language": "Spanish (Spain)"},
    "latam_es": {"region": "MX", "lang": "es", "voice": "es-MX-JorgeNeural", "language": "Spanish (Latin America)"},
    "br": {"region": "BR", "lang": "pt", "voice": "pt-BR-AntonioNeural", "language": "Portuguese (Brazil)"},
    "bd": {"region": "BD", "lang": "bn", "voice": "bn-BD-PradeepNeural", "language": "Bangla"},
}


def markets(cfg: dict) -> dict:
    return {**DEFAULT_MARKETS, **(cfg.get("money", {}).get("markets") or {})}
SCRIPTS = {"south_asia": re.compile(r"[ঀ-৿ऀ-ॿ؀-ۿ਀-੿]")}


def rpm_table(cfg: dict) -> dict:
    t = dict(DEFAULT_RPM)
    for k, v in (cfg.get("money", {}).get("rpm") or {}).items():
        t[k] = tuple(v) + (("config",) if len(v) == 4 else ())
    return t


def geo_table(cfg: dict) -> dict:
    return {**DEFAULT_GEO, **(cfg.get("money", {}).get("geo_multiplier") or {})}


def bucket_for(video: dict, niche: str = "") -> str:
    text = f"{niche} {video.get('title', '')}"
    if FINANCE_WORDS.search(text):
        return "finance_business"
    if KIDS_WORDS.search(text):
        return "kids"
    return CATEGORY_TO_BUCKET.get(str(video.get("category_id")), "other")


def audience_for(video: dict) -> str:
    title = video.get("title", "") or ""
    lang = video.get("language")
    lang = lang.lower() if isinstance(lang, str) else ""
    if SCRIPTS["south_asia"].search(title) or lang[:2] in ("bn", "hi", "ur", "pa", "ta", "te", "mr"):
        return "south_asia"
    if lang.startswith("en-us") or lang.startswith("en-gb"):
        return "tier1_english"
    if lang.startswith("en") or re.fullmatch(r"[\x00-\x7F -⯿\U0001F000-\U0001FAFF]*", title):
        return "global_english"
    return "other"


def revenue_range(cfg: dict, views: float, bucket: str, audience: str, is_short: bool) -> tuple[float, float]:
    lo_l, hi_l, lo_s, hi_s, *_ = rpm_table(cfg)[bucket]
    g = geo_table(cfg)[audience]
    lo, hi = (lo_s, hi_s) if is_short else (lo_l, hi_l)
    return views / 1000 * lo * g, views / 1000 * hi * g


def ypp_rules(cfg: dict) -> dict:
    """Ad-revenue thresholds. AIR reports these rise on 1 Feb 2027; edit config if YouTube changes them."""
    d = {"subs": 1000, "watch_hours_12m": 4000, "shorts_views_90d": 10_000_000,
         "from_2027_02_01": {"watch_hours_12m": 8000, "shorts_views_90d": 20_000_000}}
    d.update(cfg.get("money", {}).get("ypp") or {})
    return d
