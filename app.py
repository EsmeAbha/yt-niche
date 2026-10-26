"""Niche Studio, local web app.  Start:  streamlit run app.py   (or double-click start.bat)"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import traceback
from datetime import datetime, time as dtime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import yaml

from niche_studio.config import ROOT, load_config, niche_dir

st.set_page_config(page_title="Niche Studio", page_icon="🎬", layout="wide")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, textarea, select {font-family:'Inter',sans-serif !important}
.block-container{padding-top:2rem;max-width:1150px}
h1{font-weight:800 !important;letter-spacing:-.02em}
h2,h3{font-weight:700 !important;letter-spacing:-.01em}
section[data-testid="stSidebar"]{background:#140f1f}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]{border-radius:10px;padding:.45rem .7rem;margin:2px 0}
section[data-testid="stSidebar"] a[aria-current="page"]{background:rgba(167,107,255,.18)}
div[data-testid="stVerticalBlockBorderWrapper"]{background:#1a1526;border-color:#2a2238 !important}
div[data-testid="stMetric"]{background:#1a1526;border:1px solid #2a2238;border-radius:14px;padding:.8rem 1rem}
div[data-testid="stMetricValue"]{font-size:1.45rem;font-weight:700}
.stButton>button, .stFormSubmitButton>button{border-radius:10px;font-weight:600;padding:.5rem 1.1rem}
.stButton>button[kind="primary"]{background:linear-gradient(135deg,#8b4dff,#c06bff);border:0}
.stButton>button[kind="primary"]:hover{filter:brightness(1.1)}
.v{padding:.6rem .9rem;border-radius:10px;margin:.35rem 0;border-left:4px solid;background:#1a1526}
.v.pass{border-color:#34c27a}.v.warn{border-color:#e8b130}.v.fail{border-color:#ef5a50}
.small{font-size:.85rem;opacity:.75}
.hero{padding:2rem 2.2rem;border-radius:20px;margin-bottom:1.4rem;
  background:radial-gradient(circle at 85% 20%,rgba(192,107,255,.35),transparent 55%),linear-gradient(135deg,#231a36,#140f1f);
  border:1px solid #2f2545}
.hero h1{margin:0 0 .4rem 0;font-size:2.3rem}
.hero p{margin:0;opacity:.8;font-size:1.05rem}
.step{display:flex;gap:1rem;align-items:flex-start;padding:1rem 1.2rem;border-radius:14px;background:#1a1526;border:1px solid #2a2238;margin-bottom:.7rem}
.step .n{flex:none;width:34px;height:34px;border-radius:50%;display:grid;place-items:center;font-weight:700;background:#2a2040;color:#c9a4ff}
.step.done .n{background:#1f3b2c;color:#5fe39b}
.step.now{border-color:#8b4dff;box-shadow:0 0 0 1px #8b4dff55}
.step b{display:block;margin-bottom:.15rem}
.step span{opacity:.72;font-size:.92rem}
.badge{display:inline-block;padding:.12rem .55rem;border-radius:999px;background:#2a2040;color:#d3b5ff;font-size:.78rem;font-weight:600}
table.mt{width:100%;font-size:.82rem;border-collapse:collapse;margin:.3rem 0}
table.mt td{padding:.18rem .2rem;border-bottom:1px solid #2a2238}
table.mt td:last-child{text-align:right;opacity:.7;width:1.2rem}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- helpers
def cfg():
    try:
        return load_config()
    except FileNotFoundError:
        return None


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


def save(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def run(label: str, fn, *args, **kwargs):
    """Run a pipeline step, show its log live-ish, never crash the page."""
    buf = io.StringIO()
    with st.status(label, expanded=False) as box:
        try:
            with contextlib.redirect_stdout(buf):
                out = fn(*args, **kwargs)
            box.update(label=f"{label}: done", state="complete")
            if buf.getvalue().strip():
                st.code(buf.getvalue()[-6000:], language=None)
            return out
        except SystemExit as e:
            box.update(label=f"{label}: stopped", state="error")
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            box.update(label=f"{label}: failed", state="error")
            st.error(f"{type(e).__name__}: {e}")
            with st.expander("Details"):
                st.code(buf.getvalue()[-3000:] + "\n" + traceback.format_exc())
    return None


def scanned(c) -> dict[str, Path]:
    """label -> folder for every niche that has an analysis."""
    out = {}
    if c:
        for p in sorted(c["_output"].glob("*/analysis.json"), key=lambda p: -p.stat().st_mtime):
            a = load(p)
            if a and "niche" in a and "error" not in a:
                out[a["niche"]] = p.parent
    return out


def pick_niche(c, key: str):
    opts = scanned(c)
    if not opts:
        st.info("No niche scanned yet. Go to **Find a niche** first.")
        return None, None
    labels = list(opts)
    cur = st.session_state.get("cur_niche")
    if cur not in opts:  # default: most recent niche that already has ideas, else most recent
        cur = next((l for l in labels if (opts[l] / "ideas.json").exists()), labels[0])
    label = st.selectbox("Niche", labels, index=labels.index(cur), key=key)
    st.session_state["cur_niche"] = label   # remembered across pages
    return label, opts[label]


def money(r, md: bool = True) -> str:
    """md=True escapes $ so Streamlit doesn't render it as LaTeX math."""
    if not r:
        return "–"
    lo, hi = r
    d = "\\$" if md else "$"
    return f"{d}{lo:,.2f}–{d}{hi:,.2f}" if hi < 10 else f"{d}{lo:,.0f}–{d}{hi:,.0f}"


def verdict(a):
    for v in a.get("verdict", []):
        st.markdown(f"<div class='v {v['level']}'><b>{v['area']}</b> · {v['text']}</div>", unsafe_allow_html=True)


def check(url: str) -> bool:
    try:
        return requests.get(url, timeout=2).ok
    except requests.RequestException:
        return False


def bible_empty(c) -> bool:
    import re
    p = ROOT / c.get("channel", {}).get("bible", "channel/bible.md")
    if not p.exists():
        return True
    text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S)
    text = re.sub(r"^#.*$", "", text, flags=re.M)
    return len(text.strip()) < 40


def ns(**kw):
    import argparse
    return argparse.Namespace(**kw)


# ---------------------------------------------------------------- pages
def _home_checks(c):
    yk = str(c.get("youtube", {}).get("api_key", ""))
    fb = str(c.get("facebook", {}).get("page_token", ""))
    lc = c.get("llm", {})
    vc = c.get("video", {})
    checks = [
        ("YouTube API key", bool(yk) and not yk.startswith("YOUR_"), "Needed to scan niches. Free: Settings → YouTube."),
        ("Idea writer (Ollama)" if lc.get("provider") == "ollama" else f"Idea writer ({lc.get('provider')})",
         check(lc.get("ollama_url", "http://localhost:11434") + "/api/tags") if lc.get("provider") == "ollama" else lc.get("provider") != "none",
         "Install Ollama and run `ollama pull qwen3:14b`, or write ideas with Claude."),
        ("ComfyUI (GPU video)", check(vc.get("comfy_url", "http://127.0.0.1:8188") + "/system_stats"), "Start ComfyUI before rendering. Without it you get placeholder shots."),
        ("ComfyUI workflow", (ROOT / vc.get("comfy_workflow", "workflows/t2v_api.json")).exists(), "Export your workflow (API) to workflows/t2v_api.json."),
        ("FFmpeg", shutil.which("ffmpeg") is not None, "winget install Gyan.FFmpeg"),
        ("Facebook Page token (optional)", bool(fb) and not fb.startswith("YOUR_"), "Only for analysing your own Page automatically."),
    ]
    cols = st.columns(3)
    for i, (name, ok, hint) in enumerate(checks):
        with cols[i % 3].container(border=True):
            st.markdown(f"{'✅' if ok else '⚪'} **{name}**")
            if not ok:
                st.caption(hint)



FLOW_URL = "https://labs.google/fx/tools/flow"
GEMINI_URL = "https://gemini.google.com/app"
VIBES = ["Kids rhyme / song", "Funny", "Cute", "Satisfying", "Dramatic", "Mysterious", "Educational", "Wholesome"]
REGIONS = {"United States": "US", "United Kingdom": "GB", "India": "IN", "Bangladesh": "BD", "Germany": "DE",
           "Canada": "CA", "Australia": "AU", "Japan": "JP", "France": "FR", "Brazil": "BR", "Worldwide (search only)": None}
BASIS = {"verified": ("✔", "verified from the platform's API"), "derived": ("ƒ", "calculated from verified numbers"),
         "measured": ("⏱", "measured between two of our own checks"), "entered": ("✎", "entered by you"),
         "inferred": ("≈", "AI reading, not data"), "unavailable": ("–", "not published by the platform")}


def copy_button(text: str, label: str = "Copy", key: str = "c"):
    """A real copy-to-clipboard button (st.code's icon is easy to miss)."""
    import html as _h
    import streamlit.components.v1 as components
    components.html(f"""
<textarea id="t" style="position:absolute;left:-9999px">{_h.escape(text)}</textarea>
<button id="b" style="width:100%;padding:.62rem 1rem;border:0;border-radius:10px;cursor:pointer;font:600 15px Inter,sans-serif;
 color:#fff;background:linear-gradient(135deg,#8b4dff,#c06bff)">📋 {_h.escape(label)}</button>
<script>
const b=document.getElementById('b'), t=document.getElementById('t');
b.onclick=async()=>{{ try{{await navigator.clipboard.writeText(t.value);}}catch(e){{t.select();document.execCommand('copy');}}
 b.textContent='✅ Copied! Now paste it into Google'; setTimeout(()=>b.textContent='📋 {_h.escape(label)}',2500);}};
</script>""", height=50)


def _fmt_n(x, pct=False, dec=0):
    if x is None:
        return None
    return f"{x:,.{dec}f}%" if pct else (f"{x:,.{dec}f}" if dec else f"{x:,.0f}")


def _metric_rows(v: dict) -> list[tuple[str, str | None, str]]:
    src = "entered" if v.get("entered") else "verified"
    grow = v.get("growth_per_hour")
    return [("Views", _fmt_n(v.get("views")), src),
            ("Likes" if v["platform"] == "YouTube" else "Reactions", _fmt_n(v.get("likes")), src),
            ("Comments", _fmt_n(v.get("comments")), src),
            ("Shares", _fmt_n(v.get("shares")), src if v.get("shares") is not None else "unavailable"),
            ("Views / hour (avg since upload)", _fmt_n(v.get("views_per_hour")), "derived"),
            ("Growth now", f"{grow:,.0f} views/h over {v.get('growth_window_h')}h" if grow is not None else None,
             "measured" if grow is not None else "unavailable"),
            ("Engagement", _fmt_n(v.get("engagement_rate"), pct=True, dec=2), "derived"),
            ("Views ÷ subscribers", f"{v['views_vs_subs']}×" if v.get("views_vs_subs") is not None else None,
             "derived" if v.get("views_vs_subs") is not None else "unavailable"),
            ("Views vs similar results", f"{v['views_vs_median']}× median" if v.get("views_vs_median") else None, "derived"),
            ("Retention / watch time", None, "unavailable")]


def video_card(v: dict, key: str, compact: bool = False, actions: bool = True):
    with st.container(border=True):
        if v.get("thumbnail"):
            st.image(v["thumbnail"], width="stretch")
        age_d = v.get("age_hours", 0) / 24
        st.markdown(f"**[{v.get('title', '')[:90]}]({v.get('url') or '#'})**  \n"
                    f"<span class='small'>{v['platform']} · {v.get('channel_title') or ''} · "
                    f"{str(v.get('published_at', ''))[:10]} ({age_d:.1f} days ago) · "
                    f"{'Short/Reel' if v.get('is_short') else 'Long'} · {v.get('duration_s', 0) // 60}:{v.get('duration_s', 0) % 60:02d}</span>",
                    unsafe_allow_html=True)
        st.markdown(f"<span class='badge'>{v.get('status', '')}</span> <span class='small'>{v.get('status_reason', '')}</span>",
                    unsafe_allow_html=True)
        rows = _metric_rows(v)[: 4 if compact else None]
        st.markdown("<table class='mt'>" + "".join(
            f"<tr><td>{n}</td><td><b>{val if val is not None else 'Data unavailable'}</b></td>"
            f"<td title='{BASIS[b][1]}'>{BASIS[b][0]}</td></tr>" for n, val, b in rows) + "</table>", unsafe_allow_html=True)
        if v.get("viral_potential") is not None:
            st.caption(f"Viral potential: **{v['viral_potential']}/100** (formula under the tabs)")
        hk = st.session_state.get("tr_hooks", {}).get(v["video_id"])
        if hk:
            st.caption(f"Hook ≈ {hk.get('hook_score')}/10 · {hk.get('hook_structure', '')} · {hk.get('why', '')}")
        if actions:
            st.checkbox("Compare", key=f"cmp_{key}_{v['video_id']}",
                        value=v["video_id"] in st.session_state.get("tr_cmp", set()),
                        on_change=_toggle_cmp, args=(v["video_id"], f"cmp_{key}_{v['video_id']}"))
            if st.button("Select this video and generate prompt", key=f"sel_{key}_{v['video_id']}", type="primary", width="stretch"):
                st.session_state["sel_video"] = v
                st.session_state.pop("sel_analysis", None)
                st.session_state["cr_src"] = "A trending video"
                st.switch_page(PAGE_CREATE)


def _toggle_cmp(vid, k):
    s = st.session_state.setdefault("tr_cmp", set())
    (s.add if st.session_state.get(k) else s.discard)(vid)


# ---------------------------------------------------------------- home
def page_home():
    st.markdown("<div class='hero'><h1>Niche Studio</h1><p>Find what's working. Turn it into a ready-to-paste "
                "Google Veo prompt. Make the video.</p></div>", unsafe_allow_html=True)
    a, b = st.columns(2, gap="large")
    with a.container(border=True):
        st.markdown("### 🔥 Discover trending videos")
        st.markdown("Search YouTube (and Facebook Reels you've seen) by topic, format and date. See real views, "
                    "growth and engagement, pick a winner, and get a prompt built from it.")
        if st.button("Discover trending videos  →", type="primary", width="stretch"):
            st.switch_page(PAGE_DISCOVER)
    with b.container(border=True):
        st.markdown("### ✨ Create a video from my idea")
        st.markdown("Type your idea. Optionally check what's working for that topic first. Get the complete "
                    "prompt, clip by clip, ready for Google AI Pro.")
        if st.button("Create from my idea  →", type="primary", width="stretch"):
            st.session_state["cr_src"] = "My idea"
            st.switch_page(PAGE_CREATE)
    c = cfg()
    yk = str((c or {}).get("youtube", {}).get("api_key", ""))
    if not yk or yk.startswith("YOUR_"):
        st.warning("Add your free YouTube API key in **Settings** to use trending research.")


# ---------------------------------------------------------------- discover
def page_discover():
    from datetime import timedelta, timezone
    from niche_studio.trending import CONTENT_TYPES, YT_CATEGORIES, fb_as_videos, fb_entries, fb_save, rate_hooks, search_youtube
    st.title("Discover trending videos")
    c = cfg()
    if not c:
        st.warning("Save Settings first.")
        return
    ss = st.session_state
    with st.container(border=True):
        f1, f2 = st.columns(2)
        plats = f1.pills("Platform", ["YouTube", "Facebook"], selection_mode="multi", default=["YouTube"]) or ["YouTube"]
        fmt = f2.segmented_control("Format", ["Any", "Shorts / Reels", "Long videos"], default="Any") or "Any"
        topic = st.text_input("Topic or keywords", placeholder="e.g. nursery rhymes, baby shark, colors song, asteroid. Empty = YouTube's Trending chart (it never includes kids videos)")
        ctype = st.pills("Content type (optional)", list(CONTENT_TYPES))
        d1, d2, d3 = st.columns([2, 1, 1])
        when = d1.segmented_control("Uploaded in the last", ["24 hours", "7 days", "30 days", "Custom"], default="7 days") or "7 days"
        region = REGIONS[d2.selectbox("Country", list(REGIONS))]
        cat = YT_CATEGORIES[d3.selectbox("YouTube category", list(YT_CATEGORIES))]
        now = datetime.now(timezone.utc)
        after, before = now - timedelta(days={"24 hours": 1, "7 days": 7, "30 days": 30}.get(when, 30)), None
        if when == "Custom":
            rng = st.date_input("Date range", (now.date() - timedelta(days=30), now.date()))
            if isinstance(rng, tuple) and len(rng) == 2:
                after = datetime.combine(rng[0], dtime.min, timezone.utc)
                before = datetime.combine(rng[1], dtime.max, timezone.utc)
        with st.expander("More filters"):
            m1, m2, m3 = st.columns(3)
            min_views = m1.number_input("Minimum views", 0, 10**9, 0, step=10000)
            min_eng = m2.number_input("Minimum engagement %", 0.0, 100.0, 0.0, step=0.5)
            depth = m3.segmented_control("How many results", ["50", "100", "150"], default="50") or "50"
            st.caption("Each YouTube search costs 100 quota units per 50 results (10,000 free per day). "
                       "The Trending chart costs 1. Repeat searches within 12 hours are free (cached).")
        query = " ".join(x for x in [topic.strip(), CONTENT_TYPES.get(ctype, "") if ctype else ""] if x)
        go = st.button("🔍  Find trending videos", type="primary", width="stretch")

    if "Facebook" in plats:
        with st.expander(f"Facebook Reels you've seen ({len(fb_entries(c))} added)"):
            st.caption("Meta doesn't give anyone view counts for other people's Pages, so no tool can search Facebook "
                       "trends honestly. Add Reels you see while scrolling; they're ranked here with the same rules. "
                       "Leave a number empty if you can't see it: it stays 'Data unavailable'.")
            with st.form("fb_add", clear_on_submit=True):
                a1, a2, a3 = st.columns(3)
                url = a1.text_input("Reel link")
                page = a2.text_input("Page name")
                fol = a3.number_input("Page followers", 0, 10**10, 0)
                b1, b2, b3, b4 = st.columns(4)
                views = b1.number_input("Views", 0, 10**11, 0)
                reac = b2.number_input("Reactions", 0, 10**10, 0)
                com = b3.number_input("Comments", 0, 10**10, 0)
                sh = b4.number_input("Shares", 0, 10**10, 0)
                c1_, c2_, c3_ = st.columns(3)
                posted = c1_.date_input("Posted on", datetime.now().date())
                length = c2_.number_input("Length (seconds)", 0, 36000, 30)
                cap = c3_.text_input("Caption / what it shows")
                if st.form_submit_button("Add Reel") and url:
                    rows = fb_entries(c)
                    rows.append({"url": url, "page": page, "page_followers": fol or None, "views": views or None,
                                 "reactions": reac or None, "comments": com or None, "shares": sh or None,
                                 "posted": datetime.combine(posted, dtime(12), timezone.utc).isoformat(),
                                 "length_s": length, "caption": cap})
                    fb_save(c, rows)
                    st.rerun()

    if go:
        vids, units = [], 0
        if "YouTube" in plats:
            pages = int(depth) // 50
            fm = {"Any": "any", "Shorts / Reels": "shorts", "Long videos": "long"}[fmt]
            out = run("Searching YouTube" if query else "Reading YouTube's Trending chart", search_youtube, c, query, fm,
                      after if query else None, before, region, cat, pages, not query)
            if out:
                vids, units = out
                if not query and when != "Custom":
                    vids = [v for v in vids if v["age_hours"] <= (now - after).total_seconds() / 3600] or vids
        if "Facebook" in plats:
            fb = [v for v in fb_as_videos(c, query) if after <= datetime.fromisoformat(v["published_at"]) and
                  (before is None or datetime.fromisoformat(v["published_at"]) <= before)]
            if fmt != "Any":
                fb = [v for v in fb if v["is_short"] == (fmt == "Shorts / Reels")]
            vids += fb
        vids = [v for v in vids if (v.get("views") or 0) >= min_views and (v.get("engagement_rate") or 0) >= min_eng]
        ss["tr_results"], ss["tr_units"], ss["tr_query"] = vids, units, query or "YouTube Trending chart"
        ss["tr_hooks"] = {}

    vids = ss.get("tr_results")
    if vids is None:
        return
    if not vids:
        st.info("Nothing matched. Try a wider date range, fewer filters, or another keyword.")
        return
    st.markdown(f"**{len(vids)} videos** for *{ss['tr_query']}* · YouTube quota used: {ss.get('tr_units', 0)} units  \n"
                + " · ".join(f"{m} {t}" for m, t in BASIS.values()), unsafe_allow_html=True)

    cmp = [v for v in vids if v["video_id"] in ss.get("tr_cmp", set())]
    if len(cmp) >= 2:
        with st.container(border=True):
            st.markdown(f"**Comparing {len(cmp)} videos**")
            st.dataframe(pd.DataFrame([{"Title": v["title"][:50], "Platform": v["platform"], "Views": v.get("views"),
                                        "Views/h": v.get("views_per_hour"), "Engagement %": v.get("engagement_rate"),
                                        "Views÷subs": v.get("views_vs_subs"), "Shares": v.get("shares"),
                                        "Age (days)": round(v["age_hours"] / 24, 1), "Status": v.get("status"),
                                        "Viral potential": v.get("viral_potential")} for v in cmp]),
                         hide_index=True, width="stretch")
            if st.button("Clear comparison"):
                ss["tr_cmp"] = set()
                st.rerun()

    def by(key, rows=None):
        rows = rows if rows is not None else vids
        return sorted([v for v in rows if v.get(key) is not None], key=lambda v: -v[key])

    trending = sorted([v for v in vids if v.get("status") in ("Currently trending", "Rapidly growing", "Emerging")],
                      key=lambda v: -(v.get("views_per_hour") or 0))
    measured = by("growth_per_hour")
    tabs = {
        "Most viewed": (by("views"), "Total views (verified)."),
        "Currently trending": (trending, "On YouTube's Trending chart, or ≤7 days old with top-quarter views/hour, or "
                               "measured growth well above its average. Sorted by views per hour."),
        "Fastest growing": (measured or by("views_per_hour"),
                            "Measured views/hour between two of your searches." if measured else
                            "Average views per hour since upload (views ÷ hours online). Search again in a few hours "
                            "and this switches to real measured growth."),
        "Highest engagement": (by("engagement_rate", [v for v in vids if (v.get("views") or 0) >= 1000]),
                               "(likes + comments + shares where known) ÷ views. Videos under 1,000 views are left out."),
        "Most shared": (by("shares"), "Verified share counts only. YouTube doesn't publish shares; Facebook Reels you add do."),
        "Beats its channel": (by("views_vs_subs"), "Views ÷ subscribers. Above 1× means it reached far beyond its own audience."),
        "Best hooks": (sorted([v for v in vids if v["video_id"] in ss.get("tr_hooks", {})],
                              key=lambda v: -(ss["tr_hooks"][v["video_id"]].get("hook_score") or 0)),
                       "AI reading of each video's title and first 15 seconds of transcript (≈ inferred, not data)."),
        "Highest viral potential": (by("viral_potential"),
                                    "Score = 50% views/hour rank + 30% views÷subscribers rank (or vs similar results) + "
                                    "20% engagement rank, each as a percentile within these results."),
    }
    for tab, (name, (rows, how)) in zip(st.tabs(list(tabs)), tabs.items()):
        with tab:
            st.caption(how)
            if name == "Best hooks":
                if st.button("Analyse hooks of the top 10 by views (takes a minute)"):
                    got = run("Reading openings", rate_hooks, c, by("views")[:10])
                    if got:
                        ss["tr_hooks"] = got
                        st.rerun()
            if not rows:
                st.info({"Most shared": "No verified share counts in these results. YouTube doesn't publish shares.",
                         "Currently trending": "None of these is both recent (≤7 days) and in the top quarter for views/hour. "
                                               "Try 'Uploaded in the last 7 days' or '24 hours'.",
                         "Best hooks": "Press the button above to analyse the openings."}.get(name, "No data for this ranking yet."))
                continue
            cols = st.columns(3)
            for i, v in enumerate(rows[:12]):
                with cols[i % 3]:
                    video_card(v, key=name)


# ---------------------------------------------------------------- create
def _plans_dir(c) -> Path:
    d = c["_output"] / "create" / "plans"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gallery_dir(c) -> Path:
    d = c["_output"] / "create"
    d.mkdir(parents=True, exist_ok=True)
    return d


def page_create():
    from niche_studio.llm import chat_json
    from niche_studio.money import markets
    from niche_studio.prompts import STYLES, VOICES, write_plan
    from niche_studio.trending import analyze_video, research_idea, video_evidence
    st.markdown("<div class='hero'><h1>Create</h1><p>Idea or trending video → analysis → a complete prompt you paste "
                "into Google AI Pro.</p></div>", unsafe_allow_html=True)
    c = cfg()
    if not c:
        st.warning("Save Settings first.")
        return
    ss = st.session_state
    if "cr_idea_next" in ss:
        ss["cr_idea"] = ss.pop("cr_idea_next")
    src = st.segmented_control("Start from", ["My idea", "A trending video"],
                               default=ss.get("cr_src", "My idea")) or "My idea"
    ss["cr_src"] = src
    context, base, default_aspect = None, "", "9:16"

    if src == "A trending video":
        v = ss.get("sel_video")
        if not v:
            st.info("No video selected yet.")
            if st.button("Find a trending video  →", type="primary"):
                st.switch_page(PAGE_DISCOVER)
            return
        left, right = st.columns([1, 2], gap="large")
        with left:
            video_card(v, key="sel", actions=False)
        with right:
            st.subheader("1 · Analyse the video")
            st.caption("Reads its transcript, description and top comments. The video itself can't be watched by the "
                       "app, so visual points are marked ≈ inferred.")
            if st.button("🔎  Analyse this video", type="primary", disabled="sel_analysis" in ss):
                ev = run("Reading transcript and comments", video_evidence, c, v)
                if ev:
                    an = run("Analysing", analyze_video, c, v, ev)
                    if an:
                        ss["sel_analysis"] = {"evidence_sources": ev["sources"], **an}
                        st.rerun()
            an = ss.get("sel_analysis")
            if an:
                st.markdown(f"Sources: transcript **{an['evidence_sources']['transcript']}** · "
                            f"comments **{an['evidence_sources']['comments']}**")
                from niche_studio.trending import ANALYSIS_KEYS
                st.dataframe(pd.DataFrame([{"What": k.replace("_", " ").capitalize(),
                                            "Finding": (an.get(k) or {}).get("text", "") if isinstance(an.get(k), dict) else str(an.get(k, "")),
                                            "Basis": "✔ verified" if isinstance(an.get(k), dict) and an[k].get("basis") == "verified" else "≈ inferred"}
                                           for k in ANALYSIS_KEYS]), hide_index=True, width="stretch", height=420)
                st.markdown(f"**Hook:** {an.get('hook_structure', '')} (≈ {an.get('hook_score', '?')}/10)  \n"
                            f"**Viewers talk about:** {', '.join(an.get('viewer_themes', [])[:5])}  \n"
                            f"**Viewers ask for:** {', '.join(an.get('viewer_requests', [])[:5])}")
        base = f"An original video inspired by \"{v['title']}\" ({v['platform']})."
        context = {"source_video": {k: v.get(k) for k in ("title", "platform", "views", "views_per_hour", "engagement_rate",
                                                           "status", "duration_s", "is_short")},
                   "analysis": ss.get("sel_analysis")}
        default_aspect = "9:16" if v.get("is_short") else "16:9"
        twist = st.text_input("Your twist (optional)", placeholder="e.g. same idea but with a robot instead of a cat")
        if twist:
            base += f" Creator's twist: {twist}"
    else:
        st.subheader("1 · Your idea")
        with st.container(border=True):
            st.text_area("Describe the video", key="cr_idea", height=90,
                         placeholder="e.g. A cinematic video of what happens when a huge asteroid approaches Earth")
            with st.expander("Need an idea? ✨"):
                t1, t2 = st.columns([2, 1])
                topic = t1.text_input("Topic", placeholder="e.g. cats, space, cooking")
                vibe = t2.selectbox("Vibe", VIBES)
                if st.button("Suggest 4 ideas", disabled=not topic):
                    out = run("Thinking", chat_json, c, "You invent original short video ideas. JSON only.",
                              f"Topic: {topic}. Vibe: {vibe}. 4 clearly different ideas, each one visual sentence.\n"
                              'Return {"ideas": ["...", "...", "...", "..."]}', 0.9)
                    ss["cr_sugg"] = (out or {}).get("ideas", []) if isinstance(out, dict) else []
                for i, idea in enumerate(ss.get("cr_sugg", [])):
                    if st.button(f"➜ {idea}", key=f"sg{i}"):
                        ss["cr_idea_next"] = idea
                        st.rerun()
            r1, r2 = st.columns([2, 1])
            research = r1.segmented_control("Trend research", ["Skip", "YouTube", "Facebook", "Both"], default="Skip") or "Skip"
            days = r2.selectbox("Look at the last", [7, 30, 90], index=1, format_func=lambda d: f"{d} days",
                                disabled=research == "Skip")
            if research != "Skip":
                if st.button("🔍  Research this idea", disabled=not ss.get("cr_idea", "").strip()):
                    plats = ["YouTube", "Facebook"] if research == "Both" else [research]
                    out = run("Researching (searches YouTube, reads comments, analyses)", research_idea, c,
                              ss["cr_idea"], plats, "any", days)
                    if out:
                        ss["cr_research"] = out
                        st.rerun()
        idea = ss.get("cr_idea", "").strip()
        rs = ss.get("cr_research") if research != "Skip" else None
        if rs and rs.get("idea") != idea:
            rs = None
        if rs:
            _show_research(rs)
            imp = rs.get("brief", {}).get("improved_idea", {})
            use_imp = bool(imp.get("idea")) and st.toggle("Use the improved idea", value=True)
            base = (imp.get("idea") if use_imp else idea) or idea
            context = {"trend_research": rs.get("brief"), "top_videos": [
                {k: v.get(k) for k in ("title", "views", "views_per_hour", "duration_s", "status")} for v in rs["videos"][:8]],
                "search_phrases": rs["interest"].get("youtube_suggestions", [])[:8]}
            if rs.get("median_length_s") and rs["median_length_s"] <= 90:
                default_aspect = "9:16"
        else:
            base = idea

    # ---- settings + generate
    st.subheader("2 · Generate the prompt")
    with st.container(border=True):
        style = st.pills("Style", list(STYLES), default="Auto") or "Auto"
        s1, s2, s3 = st.columns(3)
        aspect = s1.segmented_control("Size", ["9:16", "16:9"], default=default_aspect, key=f"asp{default_aspect}") or default_aspect
        length = s2.segmented_control("Length", ["8s", "15s", "30s", "60s", "90s"], default="30s") or "30s"
        voice = s3.segmented_control("Voice", VOICES, default="Auto") or "Auto"
        g1, g2 = st.columns(2)
        langs = sorted({m["language"] for m in markets(c).values()} | {"English"})
        lang = g1.selectbox("Language", langs, index=langs.index("English"))
        extra = g2.text_input("Anything else? (optional)", placeholder="e.g. no people, end with a loop")
        if not base:
            st.caption("Describe your idea above first.")
        if st.button("✨  Generate complete prompt", type="primary", width="stretch", disabled=not base):
            plan = run("Writing the full video plan (1–2 minutes)", write_plan, c, base, style, aspect,
                       int(length[:-1]), lang, voice, extra, context)
            if plan:
                plan["_id"] = int(datetime.now().strftime("%d%H%M%S"))
                plan["_source"] = {"type": src, "idea": base,
                                   "video": (ss.get("sel_video") or {}).get("url") if src == "A trending video" else None}
                save(_plans_dir(c) / f"{plan['_id']}.json", plan)
                ss["cr_plan"] = str(plan["_id"])
                st.rerun()

    plans = sorted(_plans_dir(c).glob("*.json"), key=lambda p: -p.stat().st_mtime)
    if plans:
        st.subheader("3 · Your prompt")
        names = {p.stem: (load(p) or {}).get("title", p.stem) for p in plans}
        cur = str(ss.get("cr_plan", plans[0].stem))
        cur = cur if cur in names else plans[0].stem
        pid = st.selectbox("Plan", list(names), index=list(names).index(cur), format_func=lambda k: names[k])
        ss["cr_plan"] = pid
        _show_plan(c, _plans_dir(c) / f"{pid}.json")


def _show_research(rs: dict):
    b = rs.get("brief", {})
    with st.container(border=True):
        st.markdown(f"**Trend research** · searched {', '.join(rs['queries'])} · last {rs['days']} days · "
                    f"{len(rs['videos'])} videos · {rs.get('quota_units', 0)} quota units")
        a = b.get("answers", {})
        labels = {"is_topic_popular": "Is it popular?", "are_people_searching": "Are people searching?",
                  "similar_videos_views": "How do similar videos do?", "best_related_concepts": "Best related concepts",
                  "successful_hooks": "Hooks that work", "visual_styles": "Visual styles", "common_lengths": "Common lengths",
                  "storytelling": "Storytelling", "what_viewers_respond_to": "What viewers respond to",
                  "opportunities": "Opportunities"}
        st.dataframe(pd.DataFrame([{"Question": q, "Answer (≈ AI reading of the data below)": a.get(k, "")}
                                   for k, q in labels.items()]), hide_index=True, width="stretch")
        st.markdown("**Top videos found** (✔ verified numbers)")
        st.dataframe(pd.DataFrame([{"Title": v["title"][:60], "Platform": v["platform"], "Views": v.get("views"),
                                    "Views/h": v.get("views_per_hour"), "Engagement %": v.get("engagement_rate"),
                                    "Age (days)": round(v["age_hours"] / 24, 1), "Status": v.get("status"),
                                    "Link": v.get("url")} for v in rs["videos"]]),
                     hide_index=True, width="stretch", column_config={"Link": st.column_config.LinkColumn()})
        it = rs.get("interest", {})
        st.markdown("**What people type into YouTube** (✔ live autocomplete; volumes: Data unavailable)  \n"
                    + " · ".join(it.get("youtube_suggestions", [])[:10]))
        if it.get("questions"):
            st.markdown("**Questions people ask:** " + " · ".join(it["questions"][:8]))
        imp = b.get("improved_idea", {})
        if imp.get("idea"):
            st.markdown(f"**Improved idea:** {imp['idea']}  \n**Opening:** {imp.get('stronger_opening', '')}  \n"
                        f"**Angle:** {imp.get('angle', '')}  \n**Ending:** {imp.get('ending', '')}")


def _plan_to_idea(plan: dict, prompts: list[str]) -> dict:
    """Shape a plan for the existing renderer (voice, captions, music)."""
    yt = plan.get("youtube", {})
    scenes = [{"n": s["n"], "seconds": float(s.get("seconds") or 5), "hero": True, "visual_prompt": p,
               "voiceover": s.get("lyrics") or s.get("narration") or "", "on_screen_text": s.get("on_screen_text") or "",
               "sfx": s.get("sound_effects", "")} for s, p in zip(plan.get("scenes", []), prompts)]
    return {"id": plan["_id"], "title": plan.get("title", "video"),
            "format": "short" if plan.get("_aspect", "9:16") == "9:16" else "long", "scenes": scenes,
            "thumbnail_text": plan.get("thumbnail", {}).get("text", ""), "youtube_description": yt.get("description", ""),
            "hashtags": yt.get("hashtags", []), "facebook_caption": plan.get("facebook_caption", "")}


def _show_plan(c, path: Path):
    from niche_studio.produce import produce, project_dir
    from niche_studio.prompts import clip_prompts, complete_prompt
    plan = load(path)
    if not plan or not plan.get("scenes"):
        return
    prompts = clip_prompts(plan)
    full = complete_prompt(plan)
    idea = _plan_to_idea(plan, prompts)
    proj = project_dir(_plans_dir(c), idea)
    total = sum(float(s.get("seconds") or 0) for s in plan["scenes"])
    one_clip = len(plan["scenes"]) == 1

    st.markdown(f"<div class='hero' style='padding:1.3rem 1.6rem'><h1 style='font-size:1.6rem'>{plan.get('title', '')}</h1>"
                f"<p>{plan.get('hook', '')}</p></div>", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Length", f"{total:.0f}s")
    m2.metric("Clips", len(plan["scenes"]))
    m3.metric("Size", plan.get("_aspect", ""))
    m4.metric("Style", (plan.get("_style") if plan.get("_style") != "Auto" else plan.get("style", ""))[:18] or "–")

    t_full, t_clips, t_assets, t_sound, t_post = st.tabs(
        ["📋 Complete prompt", f"🎬 Clip prompts ({len(prompts)})", "🧰 Assets", "🎵 Audio", "📤 Title & post"])
    with t_full:
        if one_clip:
            st.success("This video is one clip (8 s or less): paste this prompt straight into Gemini or Flow.")
        else:
            st.info(f"Google Veo makes up to 8 seconds per generation, so this {total:.0f}s video is {len(prompts)} clips. "
                    "This complete prompt is the whole creative brief; to generate, use the **Clip prompts** tab, one per clip.")
        copy_button(full, "Copy Complete Video Prompt", key=f"full{path.stem}")
        st.code(full, language=None, wrap_lines=True)
        st.download_button("Download as text", full, file_name=f"{proj.name}.txt")
    with t_clips:
        st.markdown(f"In **[Google Flow]({FLOW_URL})** (or the **[Gemini app]({GEMINI_URL})** → Video): set "
                    f"**{plan.get('_aspect')}**, paste a clip prompt, generate, download, and drop the file in that clip's box.")
        for s, p in zip(plan["scenes"], prompts):
            n = s["n"]
            have = any((proj / "flow_inbox").glob(f"shot_{n:02d}.*"))
            with st.container(border=True):
                st.markdown(f"**{'✅' if have else '⬜'} Clip {n}** · {s['seconds']:g}s · {s.get('purpose', '')}")
                copy_button(p, f"Copy clip {n} prompt", key=f"cp{path.stem}{n}")
                st.code(p, language=None, wrap_lines=True)
                up = st.file_uploader("Drop the downloaded clip here", type=["mp4", "mov", "webm"], key=f"up{path.stem}{n}")
                if up:
                    for old in (proj / "flow_inbox").glob(f"shot_{n:02d}.*"):
                        old.unlink()
                    (proj / "flow_inbox" / f"shot_{n:02d}{Path(up.name).suffix.lower()}").write_bytes(up.getvalue())
    with t_assets:
        for ch in plan.get("characters", []):
            st.markdown(f"- 🧑 **{ch.get('name', '')}**: {ch.get('look', '')}")
        for pl in plan.get("settings", []):
            st.markdown(f"- 📍 **{pl.get('name', '')}**: {pl.get('look', '')}")
        for pr in plan.get("props", []):
            st.markdown(f"- 🧸 **{pr.get('name', '')}**: {pr.get('look', '')}")
        st.markdown("**Checklist**")
        for i, a in enumerate(plan.get("assets", [])):
            st.checkbox(f"{a.get('type', '').upper()} · {a.get('what', '')}: {a.get('how', '')}", key=f"as{path.stem}{i}")
    with t_sound:
        v, m = plan.get("voice", {}), plan.get("music", {})
        st.markdown(f"**Voice:** {v.get('use', '')} · {v.get('character') or v.get('style', '')} · "
                    f"{v.get('delivery', '')} · {v.get('quality', '')}  \n"
                    f"**Music:** {m.get('mood', '')} · {m.get('genre', '')} · {m.get('tempo_bpm', '')} bpm")
        if m.get("search_terms"):
            st.markdown(f"YouTube Audio Library search: `{m['search_terms']}` (put the track in the `music` folder to mix it in)")
        if plan.get("song"):
            sg = plan["song"]
            st.markdown(f"**Song:** {sg.get('title', '')} · {sg.get('bpm', '')} bpm · {sg.get('key', '')} · "
                        f"{sg.get('instruments', '')}  \n**Singer:** {sg.get('vocal', '')}")
            st.code(str(sg.get("lyrics", "")), language=None, wrap_lines=True)
        script = "\n".join(f"[{s['n']}] " + (s.get("lyrics") or s.get("dialogue") or s.get("narration") or "(no speech)")
                           for s in plan["scenes"])
        st.code(script, language=None, wrap_lines=True)
    with t_post:
        yt, th = plan.get("youtube", {}), plan.get("thumbnail", {})
        st.code(yt.get("title") or plan.get("title", ""), language=None, wrap_lines=True)
        if plan.get("alt_titles"):
            st.caption("Other titles: " + " · ".join(plan["alt_titles"]))
        desc = yt.get("description", "")
        tags = [t for t in yt.get("hashtags", []) if t.lower() not in desc.lower()]
        st.code((desc + "\n\n" + " ".join(tags)).strip(), language=None, wrap_lines=True)
        st.markdown("**Facebook caption**")
        st.code(plan.get("facebook_caption", ""), language=None, wrap_lines=True)
        st.markdown(f"**Thumbnail** · text `{th.get('text', '')}`")
        st.code(th.get("prompt", ""), language=None, wrap_lines=True)

    added = sum(any((proj / "flow_inbox").glob(f"shot_{s['n']:02d}.*")) for s in plan["scenes"])
    with st.expander(f"Build the finished video from your clips ({added}/{len(prompts)} added)"):
        st.caption("Joins your downloaded clips in order. Missing clips become placeholder cards.")
        tts = st.checkbox("Add an AI voiceover too (leave off if Veo already speaks in the clips)", value=False, key=f"tts{path.stem}")
        if st.button("🎬  Build video", key=f"b{path.stem}"):
            cc = {**c, "tts": {**c.get("tts", {}), "engine": c.get("tts", {}).get("engine", "edge") if tts else "none"}}
            final = run("Building the video", produce, cc, _plans_dir(c), idea, print, False)
            if final and Path(final).exists():
                dest = _gallery_dir(c) / f"{proj.name}.mp4"
                shutil.copyfile(final, dest)
                save(dest.with_suffix(".json"), {"title": plan.get("title", ""), "aspect": plan.get("_aspect")})
                st.success("Done")
        vids = sorted(_gallery_dir(c).glob("*.mp4"), key=lambda p: -p.stat().st_mtime)
        for p in vids[:3]:
            st.video(str(p))
            st.download_button("Download " + p.name, p.read_bytes(), file_name=p.name, key=f"dl{path.stem}{p.name}")


def page_find():
    from niche_studio.analyze import analyze
    from niche_studio.collect import scan_label, scan_niche
    from niche_studio.money import markets
    from niche_studio.planner import project
    st.title("Pick a topic")
    st.caption("Type a topic. We check which country pays most for it.")
    c = cfg()
    if not c:
        st.warning("Save Settings first.")
        return
    mk = markets(c)
    with st.expander("More options"):
        mode = st.segmented_control("Mode", ["One niche, many countries", "Many niches, one country", "Single scan"],
                                    default="One niche, many countries") or "One niche, many countries"
        o1, o2 = st.columns(2)
        shorts = o1.number_input("Shorts you'll post per week", 0, 30, 7)
        longs = o2.number_input("Long videos you'll post per week", 0, 7, 1)
        days = st.slider("Look back (days)", 14, 180, c.get("youtube", {}).get("lookback_days", 90))
        refresh = st.checkbox("Rescan even if scanned recently (uses API quota)")
    with st.container(border=True):
        col1 = st.container()

        if mode == "One niche, many countries":
            niche = col1.text_input("Your topic", placeholder="e.g. funny cat videos")
            chosen = st.multiselect("Countries", list(mk), default=c.get("money", {}).get("default_markets", ["us", "uk", "de", "jp", "bd"]),
                                    format_func=lambda k: f"{k} · {mk[k]['language']}")
            local = [k for k in chosen if mk[k]["lang"] != "en"]
            auto = st.checkbox("Translate the niche for each country automatically (uses the idea writer)",
                               value=c.get("llm", {}).get("provider") != "none", disabled=c.get("llm", {}).get("provider") == "none")
            queries = {}
            if local:
                qx = st.expander("Search phrase per country (optional, leave blank to auto-translate)")
                qcols = qx.columns(4)
                queries = {k: qcols[i % 4].text_input(f"{k} · {mk[k]['language']}", key=f"q_{k}") for i, k in enumerate(local)}
            go = st.button("Check this topic  →", type="primary", disabled=not niche)
            if go and auto and local and niche:
                from niche_studio.llm import chat_json
                missing = {k: mk[k]["language"] for k in local if not queries.get(k)}
                if missing:
                    tr = run("Translating the niche", chat_json, c,
                             "You translate YouTube search phrases the way locals would actually type them. JSON only.",
                             f"Niche: {niche}\nReturn {{\"market\": \"phrase\"}} for: {json.dumps(missing, ensure_ascii=False)}", 0.2) or {}
                    queries.update({k: v for k, v in tr.items() if k in missing and isinstance(v, str)})
            targets = [(niche, k, queries.get(k) or None) for k in chosen]
        elif mode == "Many niches, one country":
            text = col1.text_area("Niches (one per line)", height=110, placeholder="funny robot sketches\nai pet videos\ncricket memes")
            market = st.selectbox("Country", list(mk), format_func=lambda k: f"{k} · {mk[k]['language']}")
            go = st.button("Scan and rank niches", type="primary", disabled=not text.strip())
            targets = [(n.strip(), market, None) for n in text.splitlines() if n.strip()]
        else:
            niche = col1.text_input("Niche")
            market = st.selectbox("Country", ["(any)"] + list(mk))
            query = st.text_input("Search phrase (optional)")
            go = st.button("Scan", type="primary", disabled=not niche)
            targets = [(niche, None if market == "(any)" else market, query or None)]

    if go:
        rows = []
        for n, k, q in targets:
            label = scan_label(n, k)
            d = niche_dir(c, label)
            a = load(d / "analysis.json")
            fresh = a and (datetime.now().astimezone() - datetime.fromisoformat(a["scanned_at"])).total_seconds() < 12 * 3600
            if refresh or not fresh:
                raw = run(f"Scanning {label}", scan_niche, c, n, days, market=k, query=q)
                if not raw:
                    continue
                a = analyze(raw, c)
                save(d / "analysis.json", a)
            if "error" in a:
                st.warning(f"{label}: {a['error']}")
                continue
            p = project(a, c, shorts, longs)
            t, g = p["scenarios"]["typical"], p["scenarios"]["good"]
            rows.append({"Niche": label, "Ad rate vs US": a["money"]["geo_multiplier"],
                         "Monetized (typical)": f"month {t['ypp_month']}" if t["ypp_month"] else "not in plan",
                         "Ads/month typical": money(t["final_month_ad_rev"], False),
                         "Monetized (good)": f"month {g['ypp_month']}" if g["ypp_month"] else "not in plan",
                         "Ads/month good": money(g["final_month_ad_rev"], False),
                         "_sort": (sum(v["level"] == "fail" for v in a["verdict"]), -t["final_month_ad_rev"][1], -g["final_month_ad_rev"][1]),
                         "Young channel hits": a["entry"]["young_channel_hits"], "Proven formats": len(a["proven_formats"]),
                         "Sponsors %": a["money"]["channels_with_sponsors_pct"],
                         "Fails": sum(v["level"] == "fail" for v in a["verdict"])})
        if rows:
            df = pd.DataFrame(sorted(rows, key=lambda r: r["_sort"])).drop(columns="_sort")
            st.session_state["find_result"] = df
    if "find_result" in st.session_state:
        st.subheader("Ranking")
        st.dataframe(st.session_state["find_result"], hide_index=True, width="stretch",
                     column_config={"Ad rate vs US": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})
        st.caption("Typical / good = a new channel at the 50th / 75th percentile of small channels in that niche. "
                   "Open **Niche report** for the full picture of any row.")


def page_report():
    from niche_studio.tracker import refresh
    from niche_studio.analyze import analyze
    st.title("📊 Niche report")
    c = cfg()
    label, d = pick_niche(c, "rep_n")
    if not label:
        return
    a = load(d / "analysis.json")
    top = st.columns([4, 1, 1])
    top[0].caption(f"Scanned {a['scanned_at'][:16].replace('T', ' ')} UTC · {a['overall']['videos']} videos · "
                   f"{a['overall']['channels']} channels · baselines for {a['baseline_coverage_pct']}% of videos")
    if top[1].button("Refresh trends", help="Re-reads the same videos for ~1 quota unit per 50. Do it daily."):
        if run("Refreshing", refresh, c, label):
            raw = load(d / "raw.json")
            if raw:
                save(d / "analysis.json", analyze(raw, c))
                st.rerun()
    html_path = d / "report.html"
    if html_path.exists():
        top[2].download_button("Full report", html_path.read_bytes(), file_name=f"{d.name}.html", mime="text/html")

    st.subheader("Verdict")
    verdict(a)

    st.subheader("What a new channel gets")
    cols = st.columns(2)
    for col, (f, s) in zip(cols, a["formats"].items()):
        if not s:
            continue
        pf = a["money"]["per_format"].get(f, {})
        with col.container(border=True):
            st.markdown(f"**{f}**")
            m = st.columns(3)
            m[0].metric("Typical new channel", f"{s.get('new_channel_median') or 0:,}")
            m[1].metric("Good new channel", f"{s.get('new_channel_p75') or 0:,}")
            m[2].metric("Top 10% of all", f"{s['p90_views']:,}")
            m = st.columns(3)
            m[0].metric("Per 1K views", money((pf.get("rpm_low", 0), pf.get("rpm_high", 0))))
            m[1].metric("Ads, typical video", money(pf.get("typical_new_video_usd")))
            m[2].metric("Max views", f"{s['max_views']:,}")

    t1, t2, t3, t4, t5 = st.tabs(["💰 Money", "🧩 Proven formats", "🚀 Breakouts & trending", "🌱 Young channels", "💬 Audience"])
    with t1:
        mo = a["money"]
        mix = " · ".join(f"{k} {round(v * 100)}%" for k, v in mo.get("audience_mix", {}).items())
        st.markdown(f"Category **{mo['category']}** · audience {mix} → **{round(mo['geo_multiplier'] * 100)}%** of US ad rates  \n"
                    f"<span class='small'>Source: {mo['rpm_source']}</span>", unsafe_allow_html=True)
        m = st.columns(3)
        m[0].metric("Channels with regular sponsors", f"{mo['channels_with_sponsors_pct']}%")
        m[1].metric("Use affiliate links", f"{mo['channels_with_affiliate_pct']}%")
        m[2].metric("Sell their own product", f"{mo['channels_selling_own_product_pct']}%")
        econ = pd.DataFrame(mo["channel_economics"])
        if not econ.empty:
            econ["Ads/month (lower bound)"] = [money((l, h), False) for l, h in zip(econ.ad_rev_month_low, econ.ad_rev_month_high)]
            st.dataframe(econ[["channel", "subscribers", "age_months", "uploads_per_week", "median_short", "median_long",
                               "Ads/month (lower bound)", "sponsors", "affiliate", "own_product"]],
                         hide_index=True, width="stretch")
        st.caption(mo["note"])
    with t2:
        if not a["proven_formats"]:
            st.info("No format broke out on 2+ channels.")
        for f in a["proven_formats"]:
            with st.expander(f"**{f['concept']}**: {f['channels']} channels, {f['median_outlier']}× their normal, {f['median_views']:,} views"):
                for x in f["examples"]:
                    st.markdown(f"- [{x['title']}]({x['url']}) · {x['channel_title']} ({x['subscribers']:,} subs) · {x['views']:,} views · **{x['outlier']}×**")
    with t3:
        vc = {"url": st.column_config.LinkColumn("Link", display_text="open"),
              "outlier": st.column_config.NumberColumn("vs normal", format="%.1f×"),
              "views": st.column_config.NumberColumn(format="compact"),
              "lifetime_vpd": st.column_config.NumberColumn("views/day", format="compact"),
              "measured_vpd": st.column_config.NumberColumn("measured/day", format="compact")}
        cols_show = ["title", "channel_title", "format", "views", "outlier", "lifetime_vpd", "measured_vpd", "url"]
        st.markdown("**Biggest breakouts** (vs their own channel)")
        st.dataframe(pd.DataFrame(a["breakouts"])[cols_show] if a["breakouts"] else pd.DataFrame(), hide_index=True, width="stretch", column_config=vc)
        st.markdown(f"**Trending** <span class='small'>· {a['trend_basis']}</span>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(a["trending"])[cols_show] if a["trending"] else pd.DataFrame(), hide_index=True, width="stretch", column_config=vc)
        for f, rows in a["duration"].items():
            if rows:
                st.markdown(f"**{f} length vs channel normal**")
                st.bar_chart(pd.DataFrame(rows).set_index("bucket")["median_outlier"], height=200)
    with t4:
        e = a["entry"]
        st.caption(f"{e['hit_threshold']}. Top 5 channels hold {e['top5_view_share_pct']}% of views.")
        for x in e["young_hit_examples"]:
            st.markdown(f"- [{x['title']}]({x['url']}) · {x['channel_title']}, {int(x['channel_age_days'] or 0)} days old, {x['views']:,} views")
        if not e["young_hit_examples"]:
            st.info("No channel under 12 months old hit here.")
    with t5:
        cm = a.get("comments", {})
        cols = st.columns(3)
        for col, (k, title) in zip(cols, [("top_requests", "Requests"), ("top_questions", "Questions"), ("top_complaints", "Complaints")]):
            col.markdown(f"**{title}**")
            for x in cm.get(k, [])[:10]:
                col.markdown(f"- {x['text']} <span class='small'>· {x['likes']:,} likes</span>", unsafe_allow_html=True)


def page_plan():
    from niche_studio.planner import best_mix, project
    st.title("📈 Money plan")
    c = cfg()
    label, d = pick_niche(c, "plan_n")
    if not label:
        return
    a = load(d / "analysis.json")
    cols = st.columns(3)
    shorts = cols[0].slider("Shorts per week", 0, 21, 7)
    longs = cols[1].slider("Long videos per week", 0, 7, 1)
    hours = cols[2].slider("Your hours per week (for best mix)", 2, 60, 15)
    p = project(a, c, shorts, longs)
    save(d / "plan.json", p)
    st.caption(p["workload_note"])
    m = st.columns(3)
    for col, (n, s) in zip(m, p["scenarios"].items()):
        with col.container(border=True):
            st.markdown(f"**{n.title()}** · {s['views_per_short']:,} views/Short, {s['views_per_long']:,}/long")
            st.metric("Monetized at", f"month {s['ypp_month']}" if s["ypp_month"] else "not within plan")
            st.metric("Ads/month at end", money(s["final_month_ad_rev"]))
            st.metric("Subscribers at end", f"{s['final_subs']:,}")
    chart = pd.DataFrame({n: [t["ad_rev_month"][1] for t in s["timeline"]] for n, s in p["scenarios"].items()})
    chart.index = [f"M{i + 1:02d}" for i in range(len(chart))]
    st.markdown("**Ad income per month (high estimate)**")
    st.line_chart(chart, height=260)
    st.subheader(f"Best weekly mix for {hours} h")
    bm = pd.DataFrame(best_mix(a, c, hours))
    if not bm.empty:
        bm["Ads/month typical"] = bm.pop("ad_rev_month_typical").map(lambda r: money(r, False))
        st.dataframe(bm, hide_index=True, width="stretch")
    with st.expander("Assumptions (edit in Settings → Planner)"):
        st.json(p["assumptions"])
        st.caption("YPP: 1,000 subs + 4,000 watch hours/12 months or 10M Shorts views/90 days; reported to rise to 8,000 h / 20M from 1 Feb 2027.")


def page_ideas():
    from niche_studio.ideas import SCHEMA, build_brief, check_originality, generate_ideas
    from niche_studio.money import markets
    st.title("💡 Ideas")
    c = cfg()
    label, d = pick_niche(c, "idea_n")
    if not label:
        return
    a = load(d / "analysis.json")
    ideas = load(d / "ideas.json") or {"ideas": []}
    mk = markets(c)
    with st.container(border=True):
        cols = st.columns(4)
        n = cols[0].number_input("How many", 1, 15, c.get("ideas", {}).get("count", 6))
        fmt = cols[1].selectbox("Format", ["mix", "short", "long"])
        default_m = label.split("@")[-1] if "@" in label else None
        market = cols[2].selectbox("Market / language", ["(default)"] + list(mk),
                                   index=(list(mk).index(default_m) + 1) if default_m in mk else 0)
        cols[3].write("")
        extra = st.text_input("Extra instructions (optional)", placeholder="e.g. more office humour, no politics")
        if bible_empty(c):
            st.warning("Your series bible (Settings → Channel) is still empty. Without an original character, videos look like template content.")
        provider = c.get("llm", {}).get("provider")
        if provider == "none":
            st.info("The idea writer is off (Settings → Idea writer). Copy the brief below into Claude, then paste the JSON back.")
        elif st.button("Write ideas", type="primary"):
            out = run("Writing ideas", generate_ideas, c, a, n, fmt, None, extra, None if market == "(default)" else market)
            if out:
                save(d / "ideas.json", out)
                st.rerun()
        with st.expander("Brief / paste ideas from Claude"):
            st.code(build_brief(a) + "\n\nReturn JSON:\n" + SCHEMA, language=None)
            pasted = st.text_area("Paste ideas JSON here")
            if st.button("Save pasted ideas") and pasted.strip():
                try:
                    data = json.loads(pasted)
                    data = data if isinstance(data, dict) else {"ideas": data}
                    check_originality(c, data, a)
                    save(d / "ideas.json", data)
                    st.rerun()
                except json.JSONDecodeError as e:
                    st.error(f"Not valid JSON: {e}")

    if not ideas["ideas"]:
        return
    if st.button("Re-check originality"):
        check_originality(c, ideas, a)
        save(d / "ideas.json", ideas)
        st.rerun()
    for i, idea in enumerate(ideas["ideas"]):
        flag = " ⛔" if idea.get("blocked") else ""
        with st.expander(f"**{idea.get('id')}. {idea.get('title', '')}**{flag} · {idea.get('format', '')}"):
            if idea.get("blocked"):
                st.error("Too similar: " + "; ".join(idea.get("originality_flags", [])))
            c1, c2 = st.columns(2)
            idea["title"] = c1.text_input("Title", idea.get("title", ""), key=f"t{i}")
            idea["hook_line"] = c2.text_input("Hook (first 2 s)", idea.get("hook_line", ""), key=f"h{i}")
            st.markdown(f"**Format:** {idea.get('proven_format', '–')} · **Premise:** {idea.get('premise', '–')}")
            st.markdown(f"**What's new:** {idea.get('originality', '–')}  \n**Why:** {idea.get('why', '–')}")
            sc = pd.DataFrame(idea.get("scenes", []))
            if not sc.empty:
                cols = [x for x in ["n", "seconds", "hero", "voiceover", "on_screen_text", "visual_prompt", "camera", "sfx"] if x in sc]
                edited = st.data_editor(sc[cols], key=f"sc{i}", hide_index=True, width="stretch", num_rows="dynamic")
                idea["scenes"] = edited.to_dict("records")
            b = st.columns(3)
            if b[0].button("Save changes", key=f"s{i}"):
                save(d / "ideas.json", ideas)
                st.success("Saved")
            if b[1].button("Delete idea", key=f"del{i}"):
                ideas["ideas"].pop(i)
                save(d / "ideas.json", ideas)
                st.rerun()


def page_studio():
    from niche_studio.produce import produce, project_dir
    st.title("🎞️ Studio")
    c = cfg()
    label, d = pick_niche(c, "st_n")
    if not label:
        return
    ideas = load(d / "ideas.json") or {"ideas": []}
    if not ideas["ideas"]:
        st.info("No ideas for this niche yet. Go to **Ideas**.")
        return
    names = {f"{i['id']}. {i.get('title', '')}": i for i in ideas["ideas"]}
    idea = names[st.selectbox("Video", list(names))]
    proj = project_dir(d, idea)
    scenes = idea.get("scenes", [])

    left, right = st.columns([3, 2])
    with left:
        st.subheader("1 · Shots and voice")
        st.caption("Optional: Google Flow clips for ★ hero shots, and your own voice per scene (beats TTS for retention and monetization).")
        for s in scenes:
            n = int(s.get("n", 0))
            with st.container(border=True):
                st.markdown(f"**Scene {n}** · {s.get('seconds', 5)}s {'★ hero' if s.get('hero') else ''}  \n"
                            f"<span class='small'>{s.get('voiceover', '')}</span>", unsafe_allow_html=True)
                if s.get("hero"):
                    prompt = ". ".join(x for x in [s.get("visual_prompt", ""), f"Camera: {s['camera']}" if s.get("camera") else "",
                                                   c.get("video", {}).get("style_suffix", "")] if x)
                    st.code(prompt, language=None, wrap_lines=True)
                u1, u2 = st.columns(2)
                clip = u1.file_uploader("Flow clip", type=["mp4", "mov", "webm"], key=f"fc{proj.name}{n}")
                if clip:
                    (proj / "flow_inbox" / f"shot_{n:02d}{Path(clip.name).suffix.lower()}").write_bytes(clip.getvalue())
                    u1.success("saved")
                vo = u2.file_uploader("Your voice", type=["m4a", "mp3", "wav", "ogg"], key=f"vo{proj.name}{n}")
                if vo:
                    (proj / "audio" / f"my_vo_{n:02d}{Path(vo.name).suffix.lower()}").write_bytes(vo.getvalue())
                    u2.success("saved")
                have = [p.name for p in (proj / "flow_inbox").glob(f"shot_{n:02d}.*")] + [p.name for p in (proj / "audio").glob(f"my_vo_{n:02d}.*")]
                if have:
                    st.caption("Using: " + ", ".join(have))
        st.subheader("2 · Render")
        no_local = st.checkbox("Don't render on GPU (only Flow clips / placeholders)")
        if idea.get("blocked"):
            st.warning("This idea was flagged as too similar. Rewrite it in Ideas, or render anyway.")
        if st.button("Render video", type="primary"):
            run("Rendering (GPU shots can take a few minutes each)", produce, c, d, idea, print, not no_local)
            st.rerun()

    with right:
        final = proj / "final.mp4"
        st.subheader("3 · Watch")
        if final.exists():
            st.video(str(final))
            rl = load(proj / "render_log.json") or []
            if any("_placeholder" in str(s.get("_clip", "")) for s in rl):
                st.warning("Some shots are placeholder cards. Start ComfyUI or add Flow clips, then render again.")
            st.download_button("Download video", final.read_bytes(), file_name=f"{proj.name}.mp4", mime="video/mp4")
            thumb = proj / "thumbnail.jpg"
            if thumb.exists():
                st.image(str(thumb), caption="Thumbnail")
            page_upload(c, label, d, idea, proj)
        else:
            st.info("Not rendered yet.")


def page_upload(c, label, d, idea, proj):
    st.subheader("4 · Publish")
    st.caption("Or just download it and upload by hand; no setup needed for that.")
    uploaded = load(proj / "uploads.json") or {}
    if uploaded:
        st.success("Already uploaded: " + ", ".join(f"{k}: {v}" for k, v in uploaded.items()))
    with st.form(f"up{proj.name}"):
        title = st.text_input("Title", idea.get("title", "")[:100])
        desc = st.text_area("Description", idea.get("youtube_description", ""), height=100)
        fbcap = st.text_area("Facebook caption", idea.get("facebook_caption", ""), height=70)
        cols = st.columns(2)
        to_yt = cols[0].checkbox("YouTube", value=True)
        to_fb = cols[1].checkbox("Facebook Page", value=bool(c.get("facebook", {}).get("enabled")))
        privacy = st.selectbox("YouTube visibility", ["private", "unlisted", "public"], index=0)
        sched = st.checkbox("Schedule (YouTube)")
        sc = st.columns(2)
        day = sc[0].date_input("Date")
        tm = sc[1].time_input("Time", value=dtime(20, 0))
        go = st.form_submit_button("Upload now", type="primary")
    if go:
        idea = {**idea, "title": title, "youtube_description": desc, "facebook_caption": fbcap}
        video = proj / "final.mp4"
        when = datetime.combine(day, tm).astimezone() if sched else None
        if to_yt:
            from niche_studio.upload_youtube import upload as yt
            vid = run("Uploading to YouTube", yt, c, video, idea, when, privacy)
            if vid:
                uploaded["yt"] = vid
        if to_fb:
            from niche_studio.upload_facebook import upload as fb
            vid = run("Uploading to Facebook", fb, c, video, idea)
            if vid:
                uploaded["fb"] = vid
        save(proj / "uploads.json", uploaded)
        if uploaded:
            from niche_studio.ideas import add_to_history
            add_to_history(c, idea, "uploaded")


def page_facebook():
    from niche_studio.fb_analyze import LOG_COLUMNS, analyze_engagement, analyze_mine, log_frame, watch_frame
    from niche_studio.fb_api import my_page, watch_pages
    st.title("📘 Facebook")
    c = cfg()
    if not c:
        return
    fd = c["_output"] / "facebook"
    fd.mkdir(parents=True, exist_ok=True)
    with st.expander("Facebook money: what matters", expanded=False):
        from niche_studio.fb_report import FACTS
        for t, x, u in FACTS:
            st.markdown(f"- **{t}**: {x} [source]({u})")
    t1, t2, t3 = st.tabs(["My Page", "Log Reels by hand", "Competitor Pages"])
    with t1:
        if st.button("Analyse my Page", type="primary"):
            data = run("Reading your Page", my_page, c)
            if data:
                save(fd / "mine.json", analyze_mine(data, c))
        mine = load(fd / "mine.json")
        if mine and "error" not in mine:
            st.markdown(f"**{mine['page'].get('name')}** · {mine['page'].get('followers_count', 0):,} followers")
            cols = st.columns(max(len(mine["by_type"]), 1))
            for col, (k, v) in zip(cols, mine["by_type"].items()):
                with col.container(border=True):
                    st.markdown(f"**{k.title()}s** ({v['posts']})")
                    m = st.columns(3)
                    m[0].metric("Median plays", f"{v['median_plays']:,}")
                    m[1].metric("Watched", f"{v['median_watched_pct'] or '–'}%")
                    m[2].metric("Follows/1K plays", v["median_follows_per_1k"] or "–")
            if mine["audience_countries"]:
                st.caption("Who watches your long videos: " + ", ".join(f"{a} {b}%" for a, b in mine["audience_countries"]))
            colcfg = {"url": st.column_config.LinkColumn("Link", display_text="open"),
                      "outlier": st.column_config.NumberColumn("vs normal", format="%.1f×"),
                      "watched_pct": st.column_config.NumberColumn("watched", format="%.0f%%")}
            show = ["caption", "type", "plays", "outlier", "watched_pct", "followers_gained", "length_s", "url"]
            for title, key in [("Breakouts", "best"), ("What brings followers", "followers_drivers"), ("Flops", "worst")]:
                st.markdown(f"**{title}**")
                st.dataframe(pd.DataFrame(mine[key])[show], hide_index=True, width="stretch", column_config=colcfg)
            for f in mine["formats"]:
                st.markdown(f"- Topic that keeps working: **{f['concept']}** ({f['breakouts']} breakouts, {f['median_outlier']}×)")
        elif mine:
            st.info(mine["error"])
        else:
            st.caption("Needs your Page token in Settings → Facebook. Facebook's Professional Dashboard shows the raw numbers for free too.")
    with t2:
        st.caption("No access needed. Add Reels you see while scrolling: the hits **and** a few normal ones from the same Pages, so there's a baseline.")
        csv_path = fd / "reels_log.csv"
        df = pd.read_csv(csv_path) if csv_path.exists() else pd.DataFrame(columns=LOG_COLUMNS)
        df = df[~df["url"].astype(str).str.endswith("/reel/123")]  # drop the template's example row
        edited = st.data_editor(df, num_rows="dynamic", width="stretch", key="fblog",
                                column_config={"url": st.column_config.LinkColumn("url")})
        b = st.columns(2)
        if b[0].button("Save"):
            edited.to_csv(csv_path, index=False)
            st.success("Saved")
        if b[1].button("Analyse log", type="primary"):
            edited.to_csv(csv_path, index=False)
            res = run("Analysing", lambda: analyze_engagement(log_frame(csv_path), "log"))
            if res:
                save(fd / "others.json", res)
        show_others(load(fd / "others.json"))
    with t3:
        st.caption("Needs Meta's free 'Page Public Content Access' approval. Meta never shows other Pages' views, so this ranks by reactions + comments + shares.")
        pages = st.text_input("Page usernames or IDs (space separated)", " ".join(c.get("facebook", {}).get("watch_pages", [])))
        if st.button("Analyse competitors", type="primary", disabled=not pages.strip()):
            data = run("Reading Pages", watch_pages, c, pages.split())
            if data:
                res = analyze_engagement(watch_frame(data), "watch")
                save(fd / "others.json", res)
                show_others(res)


def show_others(res):
    if not res:
        return
    if res["posts"] < 10 or res["pages"] < 2:
        st.warning(f"Only {res['posts']} Reels from {res['pages']} Pages. Add at least 10 from 3+ Pages "
                   "(including normal ones) before trusting the results.")
    st.markdown(f"**{res['posts']} posts from {res['pages']} Pages**, ranked by {res['metric']} vs each Page's normal")
    colcfg = {"url": st.column_config.LinkColumn("Link", display_text="open"),
              "outlier": st.column_config.NumberColumn("vs normal", format="%.1f×")}
    if res["breakouts"]:
        st.dataframe(pd.DataFrame(res["breakouts"]), hide_index=True, width="stretch", column_config=colcfg)
    for f in res["formats"]:
        st.markdown(f"- Works on **{f['channels']} Pages**: {f['concept']} ({f['median_outlier']}× normal)")


def page_settings():
    st.title("⚙️ Settings")
    path = ROOT / "config.yaml"
    base = yaml.safe_load((path if path.exists() else ROOT / "config.example.yaml").read_text(encoding="utf-8")) or {}
    for k in ("youtube", "facebook", "llm", "tts", "video", "channel", "planner", "upload", "ideas"):
        base.setdefault(k, {})
    y, f, l, t, v, ch, pl, up = (base[k] for k in ("youtube", "facebook", "llm", "tts", "video", "channel", "planner", "upload"))

    def secret(label, val, help=None):
        val = "" if str(val or "").startswith("YOUR_") else (val or "")
        return st.text_input(label, val, type="password", help=help)

    tabs = st.tabs(["YouTube", "Facebook", "Idea writer", "Voice", "Video", "Channel", "Planner & uploads"])
    with tabs[0]:
        y["api_key"] = secret("YouTube Data API key", y.get("api_key"), "console.cloud.google.com → enable YouTube Data API v3 → Credentials → API key. Free.")
        y["lookback_days"] = st.number_input("Look back days", 7, 365, int(y.get("lookback_days", 90)))
        y["privacy"] = st.selectbox("Default upload visibility", ["private", "unlisted", "public"],
                                    index=["private", "unlisted", "public"].index(y.get("privacy", "private")))
        st.caption("Uploading needs secrets/client_secret.json (OAuth Desktop client). Or skip it and upload by hand.")
    with tabs[1]:
        f["page_id"] = st.text_input("Page ID", "" if str(f.get("page_id", "")).startswith("YOUR_") else f.get("page_id", ""))
        f["page_token"] = secret("Page access token", f.get("page_token"))
        f["enabled"] = st.checkbox("Also post to Facebook by default", bool(f.get("enabled")))
        wp = st.text_input("Competitor Pages to watch (space separated)", " ".join(f.get("watch_pages") or []))
        f["watch_pages"] = wp.split()
    with tabs[2]:
        l["provider"] = st.selectbox("Writer", ["ollama", "gemini", "none"], index=["ollama", "gemini", "none"].index(l.get("provider", "ollama")),
                                     help="ollama = free on your GPU. none = write ideas with Claude and paste them in.")
        l["ollama_model"] = st.text_input("Ollama model", l.get("ollama_model", "qwen3:14b"))
        l["gemini_api_key"] = secret("Gemini API key (optional, free tier)", l.get("gemini_api_key"))
        l["gemini_model"] = st.text_input("Gemini model", l.get("gemini_model", "gemini-2.5-flash"))
    with tabs[3]:
        t["engine"] = st.selectbox("Voice engine", ["edge", "piper", "none"], index=["edge", "piper", "none"].index(t.get("engine", "edge")))
        t["voice"] = st.text_input("Default voice", t.get("voice", "en-US-AndrewMultilingualNeural"),
                                   help="Market ideas pick the right language voice automatically.")
        t["rate"] = st.text_input("Speed", t.get("rate", "+8%"))
    with tabs[4]:
        v["comfy_url"] = st.text_input("ComfyUI address", v.get("comfy_url", "http://127.0.0.1:8188"))
        v["veo_hero_shots_per_video"] = st.number_input("Hero shots for Google Flow per video (0 = GPU only)", 0, 6, int(v.get("veo_hero_shots_per_video", 2)))
        v["caption_font"] = st.text_input("Caption font", v.get("caption_font", "Arial"))
        v["style_suffix"] = st.text_input("Visual style added to every prompt", v.get("style_suffix", ""))
        v["fallback_placeholder"] = st.checkbox("Use placeholder cards for missing shots", bool(v.get("fallback_placeholder", True)))
        wf = st.file_uploader("ComfyUI workflow (API export with placeholders)", type=["json"])
        if wf:
            (ROOT / "workflows").mkdir(exist_ok=True)
            (ROOT / v.get("comfy_workflow", "workflows/t2v_api.json")).write_bytes(wf.getvalue())
            st.success("Workflow saved")
        mu = st.file_uploader("Background music tracks", type=["mp3", "wav", "m4a", "ogg"], accept_multiple_files=True)
        for m in mu or []:
            (ROOT / "music").mkdir(exist_ok=True)
            (ROOT / "music" / m.name).write_bytes(m.getvalue())
    with tabs[5]:
        bible = ROOT / ch.get("bible", "channel/bible.md")
        bible.parent.mkdir(exist_ok=True)
        text = st.text_area("Series bible: your character, world, running jokes, tone", bible.read_text(encoding="utf-8") if bible.exists() else "", height=320)
        img = st.file_uploader("Character reference image", type=["png", "jpg", "jpeg"])
        ci = ROOT / ch.get("character_image", "channel/character.png")
        if img:
            ci.write_bytes(img.getvalue())
        if ci.exists():
            st.image(str(ci), width=180)
    with tabs[6]:
        pl["retention"] = st.slider("Average % of long videos watched", 0.1, 0.8, float(pl.get("retention", 0.35)))
        pl["subs_per_1k_short"] = st.number_input("Subs per 1K Shorts views", 0.0, 20.0, float(pl.get("subs_per_1k_short", 0.5)))
        pl["subs_per_1k_long"] = st.number_input("Subs per 1K long views", 0.0, 50.0, float(pl.get("subs_per_1k_long", 4.0)))
        pl["monthly_improvement"] = st.slider("Monthly improvement", 0.0, 0.2, float(pl.get("monthly_improvement", 0.04)))
        up["max_per_day"] = st.number_input("Max uploads per day (0 = no limit)", 0, 50, int(up.get("max_per_day", 0)))
    if st.button("Save settings", type="primary"):
        path.write_text(yaml.safe_dump(base, sort_keys=False, allow_unicode=True), encoding="utf-8")
        bible.write_text(text, encoding="utf-8")
        st.success("Saved")


def page_setup():
    st.title("Setup status")
    c = cfg()
    if c:
        _home_checks(c)


PAGE_HOME = st.Page(page_home, title="Home", icon=":material/home:", url_path="home", default=True)
PAGE_DISCOVER = st.Page(page_discover, title="Discover trending", icon=":material/local_fire_department:", url_path="discover")
PAGE_CREATE = st.Page(page_create, title="Create", icon=":material/auto_awesome:", url_path="create")
main = [PAGE_HOME, PAGE_DISCOVER, PAGE_CREATE,
        st.Page(page_settings, title="Settings", icon=":material/settings:", url_path="settings")]
more = [st.Page(page_find, title="Niche money check", icon=":material/search:", url_path="find"),
        st.Page(page_report, title="Niche report", icon=":material/insights:", url_path="report"),
        st.Page(page_plan, title="Money plan", icon=":material/payments:", url_path="plan"),
        st.Page(page_ideas, title="Ideas (advanced)", icon=":material/lightbulb:", url_path="ideas"),
        st.Page(page_studio, title="Studio (advanced)", icon=":material/movie:", url_path="studio"),
        st.Page(page_facebook, title="Facebook Page stats", icon=":material/groups:", url_path="facebook"),
        st.Page(page_setup, title="Setup status", icon=":material/checklist:", url_path="setup")]
pages = main + more
st.navigation({"": main, "More tools": more}).run()
