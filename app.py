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
.block-container{padding-top:1.6rem;max-width:1250px}
div[data-testid="stMetricValue"]{font-size:1.45rem}
.v{padding:.55rem .8rem;border-radius:8px;margin:.3rem 0;border-left:4px solid;background:rgba(127,127,127,.07)}
.v.pass{border-color:#2e9e5b}.v.warn{border-color:#d49a12}.v.fail{border-color:#d2453b}
.small{font-size:.85rem;opacity:.75}
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
def page_home():
    st.title("🎬 Niche Studio")
    st.caption("Find niches that pay, in the market that pays most, then make and publish videos. Everything runs on your PC for free.")
    c = cfg()
    if not c:
        st.warning("No config yet. Open **Settings** and save once to create it.")
        return
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

    st.subheader("How to use it")
    st.markdown("""
1. **Find a niche**: type a niche, compare countries or several niches.
2. **Niche report**: what new channels get, proven formats, money, the verdict.
3. **Money plan**: when you'd hit monetization and what it pays.
4. **Ideas**: video plans built on the proven formats.
5. **Studio**: render, add Flow clips or your own voice, watch, upload.
6. **Facebook**: your Page's stats, competitors, or Reels you log by hand.
""")
    opts = scanned(c)
    if opts:
        st.subheader("Your niches")
        rows = []
        for label, d in opts.items():
            a = load(d / "analysis.json")
            lv = [v["level"] for v in a.get("verdict", [])]
            rows.append({"Niche": label, "Scanned": a["scanned_at"][:16].replace("T", " "),
                         "✅": lv.count("pass"), "⚠️": lv.count("warn"), "❌": lv.count("fail"),
                         "Proven formats": len(a.get("proven_formats", [])),
                         "Ideas": len((load(d / "ideas.json") or {}).get("ideas", []))})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def page_find():
    from niche_studio.analyze import analyze
    from niche_studio.collect import scan_label, scan_niche
    from niche_studio.money import markets
    from niche_studio.planner import project
    st.title("🔎 Find a niche")
    c = cfg()
    if not c:
        st.warning("Save Settings first.")
        return
    mode = st.segmented_control("Mode", ["One niche, many countries", "Many niches, one country", "Single scan"],
                                default="One niche, many countries")
    mk = markets(c)
    with st.container(border=True):
        col1, col2, col3 = st.columns([3, 1, 1])
        shorts = col2.number_input("Shorts / week", 0, 30, 7)
        longs = col3.number_input("Long videos / week", 0, 7, 1)
        days = st.slider("Look back (days)", 14, 180, c.get("youtube", {}).get("lookback_days", 90))
        refresh = st.checkbox("Rescan even if scanned recently (uses API quota)")

        if mode == "One niche, many countries":
            niche = col1.text_input("Niche", placeholder="e.g. funny robot sketches")
            chosen = st.multiselect("Countries", list(mk), default=c.get("money", {}).get("default_markets", ["us", "uk", "de", "jp", "bd"]),
                                    format_func=lambda k: f"{k} · {mk[k]['language']}")
            local = [k for k in chosen if mk[k]["lang"] != "en"]
            auto = st.checkbox("Translate the niche for each country automatically (uses the idea writer)",
                               value=c.get("llm", {}).get("provider") != "none", disabled=c.get("llm", {}).get("provider") == "none")
            queries = {}
            if local:
                st.caption("Search phrase per country, typed the way locals search (leave blank to auto-translate or use English):")
                qcols = st.columns(4)
                queries = {k: qcols[i % 4].text_input(f"{k} · {mk[k]['language']}", key=f"q_{k}") for i, k in enumerate(local)}
            go = st.button("Scan and rank countries", type="primary", disabled=not niche)
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


pages = [st.Page(page_home, title="Home", icon="🏠", default=True),
         st.Page(page_find, title="Find a niche", icon="🔎", url_path="find"),
         st.Page(page_report, title="Niche report", icon="📊", url_path="report"),
         st.Page(page_plan, title="Money plan", icon="📈", url_path="plan"),
         st.Page(page_ideas, title="Ideas", icon="💡", url_path="ideas"),
         st.Page(page_studio, title="Studio", icon="🎞️", url_path="studio"),
         st.Page(page_facebook, title="Facebook", icon="📘", url_path="facebook"),
         st.Page(page_settings, title="Settings", icon="⚙️", url_path="settings")]
st.navigation(pages).run()
