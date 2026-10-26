"""Command line: python niche.py <command> "<niche>" [options]"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

from .config import load_config, niche_dir


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _save(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def _label(a):
    from .collect import scan_label
    return scan_label(a.niche, getattr(a, "market", None))


def _usd(r):
    return f"${r[0]:,.0f}-${r[1]:,.0f}"


def _print_verdict(res):
    icon = {"pass": "+", "warn": "!", "fail": "x"}
    for v in res["verdict"]:
        print(f"  [{icon[v['level']]}] {v['area']}: {v['text']}")


def cmd_scan(cfg, a):
    from .analyze import analyze
    from .collect import scan_niche
    from .report import render_report
    label = _label(a)
    d = niche_dir(cfg, label)
    raw = scan_niche(cfg, a.niche, a.days, market=getattr(a, "market", None), query=getattr(a, "query", None))
    res = analyze(raw, cfg)
    if "error" in res:
        sys.exit(res["error"])
    _save(d / "analysis.json", res)
    rep = render_report(res, _load(d / "ideas.json"), d / "report.html", _load(d / "plan.json"))
    print(f"\n{label}")
    for f, s in res["formats"].items():
        if s:
            print(f"  {f}: a new channel typically gets {s['new_channel_median'] or '?'} views "
                  f"(top 10% of all videos: {s['p90_views']:,}, max {s['max_views']:,})")
    _print_verdict(res)
    print(f"  report: {rep}")
    if getattr(a, "open", False):
        webbrowser.open(rep.resolve().as_uri())
    return res


def cmd_markets(cfg, a):
    """Same niche, different countries/languages, ranked by what a new channel would earn."""
    from .analyze import analyze
    from .collect import scan_niche
    from .money import markets
    from .planner import project
    keys = a.markets.split(",") if a.markets else cfg.get("money", {}).get("default_markets", ["us", "uk", "de", "jp", "fr", "bd"])
    queries = dict(q.split("=", 1) for q in (a.query or []))
    if a.translate and cfg.get("llm", {}).get("provider") != "none":
        from .llm import chat_json
        langs = {k: markets(cfg)[k]["language"] for k in keys if k not in queries}
        tr = chat_json(cfg, "You translate YouTube search phrases the way locals would actually type them. JSON only.",
                       f"Niche: {a.niche}\nGive the natural YouTube search phrase for each market as "
                       f"{{\"market\": \"phrase\"}} for: {json.dumps(langs, ensure_ascii=False)}", 0.2)
        queries = {**{k: v for k, v in tr.items() if k in keys}, **queries}
    rows = []
    for k in keys:
        label = f"{a.niche} @{k}"
        d = niche_dir(cfg, label)
        res = _load(d / "analysis.json")
        if not res or a.refresh:
            q = queries.get(k)
            if not q and markets(cfg)[k]["lang"] != "en":
                print(f"  note: no translated query for {k}; searching in English (use --translate or --query {k}=...)")
            res = analyze(scan_niche(cfg, a.niche, market=k, query=q), cfg)
            _save(d / "analysis.json", res)
        if "error" in res:
            print(f"  {k}: {res['error']}")
            continue
        p = project(res, cfg, a.shorts, a.longs)
        t, g = p["scenarios"]["typical"], p["scenarios"]["good"]
        rows.append({"market": k, "geo": res["money"]["geo_multiplier"], "ypp_month": t["ypp_month"],
                     "rev": t["final_month_ad_rev"], "ypp_good": g["ypp_month"], "rev_good": g["final_month_ad_rev"], "young_hits": res["entry"]["young_channel_hits"],
                     "formats": len(res["proven_formats"]), "sponsors": res["money"]["channels_with_sponsors_pct"],
                     "fails": sum(v["level"] == "fail" for v in res["verdict"])})
    rows.sort(key=lambda r: (r["fails"], -r["rev"][1], -r["rev_good"][1]))
    print(f"\n{a.niche}: {a.shorts:g} Shorts + {a.longs:g} long/week, ad income at month {cfg.get('planner', {}).get('months', 18)}")
    print(f"{'market':9} {'ad rate':>8} {'YPP typical':>12} {'ads typical':>14} {'YPP good':>9} {'ads good':>14} {'young hits':>10} {'formats':>8} {'sponsors':>9}")
    for r in rows:
        print(f"{r['market']:9} {r['geo'] * 100:7.0f}% {str(r['ypp_month'] or 'never'):>12} {_usd(r['rev']):>14} "
              f"{str(r['ypp_good'] or 'never'):>9} {_usd(r['rev_good']):>14} {r['young_hits']:>10} {r['formats']:>8} {r['sponsors']:>8}%")
    print("typical/good = a new channel performing at the 50th/75th percentile of small channels in that market.")
    _save(cfg["_output"] / f"markets-{niche_dir(cfg, a.niche).name}.json", rows)
    if rows:
        print(f"\nBest bet: {rows[0]['market']}. Next: python niche.py ideas \"{a.niche}\" --market {rows[0]['market']}")


def cmd_plan(cfg, a):
    from .planner import best_mix, project
    from .report import render_report
    d = niche_dir(cfg, _label(a))
    res = _load(d / "analysis.json") or sys.exit("Run scan first.")
    if a.hours:
        print(f"Best weekly mix for {a.hours:g} h/week:")
        for r in best_mix(res, cfg, a.hours):
            print(f"  {r['shorts_per_week']:>2} Shorts + {r['longs_per_week']} long -> YPP month {r['ypp_month_typical'] or 'never'}"
                  f" (slow case: {r['ypp_month_slow'] or 'never'}), ads/month after: {_usd(r['ad_rev_month_typical'])}")
        return
    p = project(res, cfg, a.shorts, a.longs)
    _save(d / "plan.json", p)
    render_report(res, _load(d / "ideas.json"), d / "report.html", p)
    print(p["workload_note"])
    for name, s in p["scenarios"].items():
        print(f"  {name:8} {s['views_per_short']:>7,} views/Short, {s['views_per_long']:>7,}/long video -> "
              f"YPP {'month ' + str(s['ypp_month']) if s['ypp_month'] else 'not reached'}; "
              f"ads at month {len(s['timeline'])}: {_usd(s['final_month_ad_rev'])}/month, {s['final_subs']:,} subs")
    print("  Ads are the floor. Sponsors, affiliates and your own product usually pay more; see the report's money section.")


def cmd_track(cfg, a):
    from .analyze import analyze
    from .report import render_report
    from .tracker import refresh
    label = _label(a)
    refresh(cfg, label)
    d = niche_dir(cfg, label)
    raw = _load(d / "raw.json")
    if raw:
        res = analyze(raw, cfg)
        _save(d / "analysis.json", res)
        render_report(res, _load(d / "ideas.json"), d / "report.html", _load(d / "plan.json"))
        for r in res["trending"][:8]:
            acc = f" (x{r['acceleration']} vs before)" if r.get("acceleration") else ""
            print(f"  {int(r['measured_vpd'] or r['lifetime_vpd']):>9,}/day{acc}  {r['title'][:70]}")


def cmd_ideas(cfg, a):
    from .ideas import generate_ideas
    from .report import render_report
    d = niche_dir(cfg, _label(a))
    res = _load(d / "analysis.json")
    if not res:
        res = cmd_scan(cfg, argparse.Namespace(niche=a.niche, days=None, open=False, market=a.market, query=None))
    print(f"Writing {a.n or cfg.get('ideas', {}).get('count', 6)} plans with {cfg.get('llm', {}).get('provider')}...")
    ideas = generate_ideas(cfg, res, a.n, a.format, a.lang, a.extra or "", market=a.market)
    _save(d / "ideas.json", ideas)
    render_report(res, ideas, d / "report.html", _load(d / "plan.json"))
    for i in ideas.get("ideas", []):
        flag = "  BLOCKED: " + "; ".join(i["originality_flags"]) if i.get("blocked") else ""
        print(f"  [{i['id']}] ({i.get('format')}) {i.get('title')}\n      hook: {i.get('hook_line')}{flag}")
    print(f"  saved {d / 'ideas.json'}")
    return ideas


def _pick(ideas: dict, which: str | None):
    items = ideas.get("ideas", [])
    if not which or which == "all":
        return items
    ids = {int(x) for x in which.split(",")}
    return [i for i in items if int(i.get("id", 0)) in ids]


def cmd_make(cfg, a):
    from .produce import produce
    d = niche_dir(cfg, _label(a))
    ideas = _load(d / "ideas.json") or sys.exit("No ideas.json yet. Run: niche ideas \"<niche>\"")
    outs = []
    for idea in _pick(ideas, a.idea):
        if idea.get("blocked") and not a.force:
            print(f"  [{idea['id']}] skipped, too similar: {'; '.join(idea['originality_flags'])} (--force to override)")
            continue
        outs.append(produce(cfg, d, idea, render_local=not a.no_local))
    return outs


def cmd_approve(cfg, a):
    """Human review gate. You watch the video and write what you changed or added. This is your
    record of human contribution if YPP review ever asks."""
    from .produce import project_dir
    d = niche_dir(cfg, _label(a))
    ideas = _load(d / "ideas.json") or sys.exit("No ideas.json")
    for idea in _pick(ideas, a.idea):
        proj = project_dir(d, idea)
        if not (proj / "final.mp4").exists():
            print(f"  [{idea['id']}] no final.mp4 yet")
            continue
        if len((a.note or "").strip()) < 15:
            sys.exit("Write a real --note about what you reviewed, changed or added (15+ characters).")
        _save(proj / "approved.json", {"at": datetime.now().isoformat(timespec="seconds"), "note": a.note})
        print(f"  [{idea['id']}] approved")


def cmd_upload(cfg, a):
    from .ideas import add_to_history
    from .produce import project_dir
    d = niche_dir(cfg, _label(a))
    ideas = _load(d / "ideas.json") or sys.exit("No ideas.json")
    when = datetime.fromisoformat(a.schedule) if a.schedule else None
    targets = (["yt"] if a.yt else []) + (["fb"] if a.fb else [])
    if not targets:
        targets = ["yt"] + (["fb"] if cfg.get("facebook", {}).get("enabled") else [])
    uc = cfg.get("upload", {})
    cap = uc.get("max_per_day", 0)                 # 0 = no limit
    need_approval = uc.get("require_approval", False)
    hist = cfg["_output"] / "upload_log.json"
    log_all = _load(hist) or []
    today = str(date.today())
    for idea in _pick(ideas, a.idea):
        proj = project_dir(d, idea)
        video = proj / "final.mp4"
        if not video.exists():
            print(f"  [{idea['id']}] no final.mp4, run `make` first")
            continue
        rl = _load(proj / "render_log.json") or []
        if any("_placeholder" in str(s.get("_clip", "")) for s in rl) and not a.force:
            print(f"  [{idea['id']}] contains placeholder test cards, not real shots (use --force if you really mean it)")
            continue
        if need_approval and not (proj / "approved.json").exists():
            print(f"  [{idea['id']}] not approved. Watch it, then: niche approve \"{a.niche}\" --idea {idea['id']} --note \"...\"")
            continue
        if cap and sum(1 for x in log_all if x["day"] == today) >= cap and not a.force:
            print(f"  daily cap of {cap} uploads reached (upload.max_per_day). Bursts of AI uploads get flagged.")
            break
        log = _load(proj / "uploads.json") or {}
        for t in targets:
            if log.get(t) and not a.force:
                print(f"  [{idea['id']}] already on {t}: {log[t]}")
                continue
            if t == "yt":
                from .upload_youtube import upload
                log["yt"] = upload(cfg, video, idea, when, a.privacy)
            else:
                from .upload_facebook import upload
                log["fb"] = upload(cfg, video, idea)
            _save(proj / "uploads.json", log)
        log_all.append({"day": today, "niche": _label(a), "id": idea["id"], "title": idea.get("title")})
        _save(hist, log_all)
        add_to_history(cfg, idea, "uploaded")


def cmd_run(cfg, a):
    cmd_scan(cfg, argparse.Namespace(niche=a.niche, days=a.days, open=False, market=a.market, query=a.query))
    cmd_ideas(cfg, argparse.Namespace(niche=a.niche, n=a.n, format=a.format, lang=a.lang, extra=a.extra, market=a.market))
    cmd_make(cfg, argparse.Namespace(niche=a.niche, idea="all", no_local=a.no_local, market=a.market, force=False))
    print(f"\nRendered. Review each video, then `approve` and `upload`. Report: {niche_dir(cfg, _label(a)) / 'report.html'}")


def cmd_compare(cfg, a):
    from .analyze import analyze
    from .collect import scan_niche
    from .planner import project
    rows = []
    for n in a.niches:
        d = niche_dir(cfg, n)
        res = _load(d / "analysis.json")
        if not res or a.refresh:
            res = analyze(scan_niche(cfg, n), cfg)
            _save(d / "analysis.json", res)
        if "error" in res:
            continue
        t = project(res, cfg, a.shorts, a.longs)["scenarios"]["typical"]
        rows.append((n, t["ypp_month"], t["final_month_ad_rev"], res["entry"]["young_channel_hits"],
                     len(res["proven_formats"]), res["money"]["channels_with_sponsors_pct"],
                     sum(v["level"] == "fail" for v in res["verdict"])))
    rows.sort(key=lambda r: (r[6], -r[2][1]))
    print(f"\n{'niche':30} {'YPP at':>7} {'ads/month':>16} {'young hits':>10} {'formats':>8} {'sponsors':>9} {'fails':>6}")
    for r in rows:
        print(f"{r[0][:30]:30} {str(r[1] or 'never'):>7} {_usd(r[2]):>16} {r[3]:>10} {r[4]:>8} {r[5]:>8}% {r[6]:>6}")


def cmd_report(cfg, a):
    from .report import render_report
    d = niche_dir(cfg, _label(a))
    res = _load(d / "analysis.json") or sys.exit("Run scan first.")
    p = render_report(res, _load(d / "ideas.json"), d / "report.html", _load(d / "plan.json"))
    print(p)
    if not a.no_open:
        webbrowser.open(p.resolve().as_uri())


# ---------------- Facebook ----------------

def _fb_dir(cfg):
    d = cfg["_output"] / "facebook"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fb_render(cfg, open_it=False):
    from .fb_report import render_fb
    d = _fb_dir(cfg)
    p = render_fb(_load(d / "mine.json"), _load(d / "others.json"), d / "report.html")
    print(f"  report: {p}")
    if open_it:
        webbrowser.open(p.resolve().as_uri())


def cmd_fb_mine(cfg, a):
    from .fb_analyze import analyze_mine
    from .fb_api import my_page
    data = my_page(cfg)
    res = analyze_mine(data, cfg)
    _save(_fb_dir(cfg) / "mine.json", res)
    if "error" in res:
        sys.exit(res["error"])
    for k, v in res["by_type"].items():
        print(f"  {k}: {v['posts']} posts, median {v['median_plays']:,} plays, watched {v['median_watched_pct']}%, "
              f"{v['median_follows_per_1k']} follows/1K plays")
    if res["audience_countries"]:
        print("  audience: " + ", ".join(f"{c} {p}%" for c, p in res["audience_countries"][:5]))
    for r in res["best"][:5]:
        print(f"  {r['outlier'] or 0:5.1f}x  {r['plays']:>9,} plays  {(r['caption'] or '').splitlines()[0][:60] if r['caption'] else '(no caption)'}")
    _fb_render(cfg, a.open)


def cmd_fb_watch(cfg, a):
    from .fb_analyze import analyze_engagement, watch_frame
    from .fb_api import watch_pages
    pages = a.pages or cfg.get("facebook", {}).get("watch_pages") or []
    if not pages:
        sys.exit("List competitor Pages: --pages PageName1 PageName2, or facebook.watch_pages in config.yaml")
    res = analyze_engagement(watch_frame(watch_pages(cfg, pages)), "watch")
    _save(_fb_dir(cfg) / "others.json", res)
    _print_fb_others(res)
    _fb_render(cfg, a.open)


def cmd_fb_log(cfg, a):
    from .fb_analyze import analyze_engagement, log_frame, log_template
    if a.template or not a.csv:
        t = log_template(_fb_dir(cfg) / "reels_log.csv")
        print(f"Template: {t}\nAdd one row per Reel you see doing well (and some normal ones from the same Pages for a baseline), "
              f"then run: python niche.py fb-log {t}")
        return
    res = analyze_engagement(log_frame(Path(a.csv)), "log")
    _save(_fb_dir(cfg) / "others.json", res)
    _print_fb_others(res)
    _fb_render(cfg, a.open)


def _print_fb_others(res):
    print(f"  {res['posts']} posts from {res['pages']} Pages, ranked by {res['metric']}")
    for t, v in res["by_type"].items():
        print(f"  {t}: {v['posts']} posts, {v['median_outlier'] or '-'}x normal")
    for r in res["breakouts"][:6]:
        print(f"  {r['outlier']:5.1f}x  {str(r.get('page'))[:20]:20} {str(r.get('caption') or '').splitlines()[0][:60] if r.get('caption') else ''}")
    for f in res["formats"][:3]:
        print(f"  format on {f['channels']} Pages: {f['concept']}")


def cmd_fb_report(cfg, a):
    _fb_render(cfg, not a.no_open)


def main(argv=None):
    p = argparse.ArgumentParser(prog="niche", description="Niche research -> money plan -> video plans -> videos -> uploads")
    p.add_argument("--config", help="path to config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    def mk(x):
        x.add_argument("--market", help="target market key: us, uk, au, de, nordics, fr, jp, es, latam_es, br, bd")

    s = sub.add_parser("scan", help="analyse a niche"); s.add_argument("niche"); mk(s)
    s.add_argument("--query", help="search phrase to use instead of the niche name (e.g. translated)")
    s.add_argument("--days", type=int); s.add_argument("--open", action="store_true")

    s = sub.add_parser("markets", help="scan one niche across countries/languages and rank by income")
    s.add_argument("niche"); s.add_argument("--markets", help="comma list, e.g. us,uk,de,jp")
    s.add_argument("--query", action="append", help="per-market phrase, e.g. --query de=\"lustige KI Videos\"")
    s.add_argument("--translate", action="store_true", help="let the LLM translate the niche per market")
    s.add_argument("--shorts", type=float, default=7); s.add_argument("--longs", type=float, default=1)
    s.add_argument("--refresh", action="store_true")

    s = sub.add_parser("plan", help="months to monetization and income projection"); s.add_argument("niche"); mk(s)
    s.add_argument("--shorts", type=float, default=7); s.add_argument("--longs", type=float, default=1)
    s.add_argument("--hours", type=float, help="find the best mix for this many hours a week")

    s = sub.add_parser("track", help="cheap daily refresh -> measured trend velocity"); s.add_argument("niche"); mk(s)

    def idea_opts(x):
        x.add_argument("-n", type=int, help="number of ideas")
        x.add_argument("--format", choices=["short", "long", "mix"], default="mix")
        x.add_argument("--lang", help="override voiceover language")
        x.add_argument("--extra", help="extra instructions for the writer")
        mk(x)

    s = sub.add_parser("ideas", help="write video plans"); s.add_argument("niche"); idea_opts(s)
    s = sub.add_parser("make", help="render videos"); s.add_argument("niche"); mk(s)
    s.add_argument("--idea", default="all"); s.add_argument("--no-local", action="store_true")
    s.add_argument("--force", action="store_true", help="render ideas blocked by the originality check")
    s = sub.add_parser("approve", help="mark videos reviewed (required before upload)"); s.add_argument("niche"); mk(s)
    s.add_argument("--idea", required=True); s.add_argument("--note", required=True, help="what you reviewed/changed/added")
    s = sub.add_parser("upload", help="upload approved videos"); s.add_argument("niche"); mk(s)
    s.add_argument("--idea", default="all"); s.add_argument("--yt", action="store_true"); s.add_argument("--fb", action="store_true")
    s.add_argument("--schedule", help="YYYY-MM-DDTHH:MM local time"); s.add_argument("--force", action="store_true")
    s.add_argument("--privacy", choices=["private", "unlisted", "public"])
    s = sub.add_parser("run", help="scan + ideas + make (no upload)"); s.add_argument("niche"); idea_opts(s)
    s.add_argument("--days", type=int); s.add_argument("--query"); s.add_argument("--no-local", action="store_true")
    s = sub.add_parser("compare", help="rank niches by projected income"); s.add_argument("niches", nargs="+")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--shorts", type=float, default=7); s.add_argument("--longs", type=float, default=1)
    s = sub.add_parser("report", help="re-render and open the report"); s.add_argument("niche"); mk(s)
    s.add_argument("--no-open", action="store_true")

    s = sub.add_parser("fb-mine", help="analyse your own Facebook Page's Reels and videos")
    s.add_argument("--open", action="store_true")
    s = sub.add_parser("fb-watch", help="analyse competitor Pages (needs Page Public Content Access)")
    s.add_argument("--pages", nargs="+"); s.add_argument("--open", action="store_true")
    s = sub.add_parser("fb-log", help="analyse Reels you logged by hand in a CSV (no API access needed)")
    s.add_argument("csv", nargs="?"); s.add_argument("--template", action="store_true"); s.add_argument("--open", action="store_true")
    s = sub.add_parser("fb-report", help="re-render and open the Facebook report"); s.add_argument("--no-open", action="store_true")

    a = p.parse_args(argv)
    from .comfy import ComfyError
    from .fb_api import GraphError
    from .llm import LLMError
    from .youtube_api import QuotaExceeded
    try:
        cfg = load_config(a.config)
        {"scan": cmd_scan, "markets": cmd_markets, "plan": cmd_plan, "track": cmd_track, "ideas": cmd_ideas,
         "make": cmd_make, "approve": cmd_approve, "upload": cmd_upload, "run": cmd_run, "compare": cmd_compare,
         "report": cmd_report, "fb-mine": cmd_fb_mine, "fb-watch": cmd_fb_watch, "fb-log": cmd_fb_log,
         "fb-report": cmd_fb_report}[a.cmd](cfg, a)
    except (LLMError, QuotaExceeded, ComfyError, GraphError, ValueError, FileNotFoundError, KeyError) as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
