"""One self-contained HTML dashboard per niche. Order follows the decision: should I do this, how
does it pay, what do I make, what does the audience want."""
from __future__ import annotations

import html
import json
from pathlib import Path

e = html.escape


def _n(x) -> str:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "–"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= div:
            return f"{x / div:.1f}{unit}"
    return f"{x:.0f}"


def _usd(r) -> str:
    if not r:
        return "–"
    lo, hi = r
    f = (lambda v: f"${v:,.2f}") if hi < 10 else (lambda v: f"${v:,.0f}")
    return f"{f(lo)}–{f(hi)}"


def _dur(s) -> str:
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s}s"


def _videos(rows, vel_col=False):
    if not rows:
        return "<p class='muted'>None.</p>"
    head = ("<tr><th>Video</th><th>Type</th><th class='num'>Views</th><th class='num'>vs channel normal</th>"
            f"<th class='num'>{'Views/day (measured)' if vel_col else 'Views/day'}</th><th class='num'>Est. ad $</th></tr>")
    body = []
    for r in rows:
        vpd = r.get("measured_vpd") if vel_col and r.get("measured_vpd") is not None else r.get("lifetime_vpd")
        out = r.get("outlier")
        body.append(
            f"<tr><td><a href='{e(r['url'])}' target='_blank'>{e(r['title'])}</a>"
            f"<div class='muted small'>{e(str(r['channel_title']))} · {_n(r['subscribers'])} subs · {_dur(r['duration_s'])}</div></td>"
            f"<td>{e(r['format'])}</td><td class='num'>{_n(r['views'])}</td>"
            f"<td class='num'><b>{'–' if out is None or out != out else f'{out:.1f}×'}</b></td>"
            f"<td class='num'>{_n(vpd)}</td><td class='num'>{_usd((r.get('rev_low', 0), r.get('rev_high', 0)))}</td></tr>")
    return f"<table>{head}{''.join(body)}</table>"


def _ideas(ideas):
    if not ideas or not ideas.get("ideas"):
        return "<p class='muted'>No plans yet. Run <code>python niche.py ideas \"…\"</code> or <code>/niche-ideas</code>.</p>"
    out = []
    for i in ideas["ideas"]:
        scenes = "".join(
            f"<tr><td>{s.get('n')}</td><td>{s.get('seconds')}s{' ★' if s.get('hero') else ''}</td>"
            f"<td>{e(s.get('voiceover', ''))}<div class='muted small'>{e(s.get('on_screen_text', ''))}</div></td>"
            f"<td class='muted small'>{e(s.get('visual_prompt', ''))}</td></tr>" for s in i.get("scenes", []))
        flags = ("<p class='bad small'>Blocked: " + e("; ".join(i.get("originality_flags", []))) + "</p>") if i.get("blocked") else ""
        out.append(
            f"<details class='card idea'><summary><span class='tag'>{e(str(i.get('format', '')))}</span>"
            f"{' <span class=tag>' + e(i['market']) + '</span>' if i.get('market') else ''} <b>{e(i.get('title', ''))}</b>"
            f"<div class='muted small'>Hook: {e(i.get('hook_line', ''))}</div></summary>{flags}"
            f"<p><b>Format:</b> {e(str(i.get('proven_format', '')))} · <b>Premise:</b> {e(str(i.get('premise', '')))}</p>"
            f"<p><b>What's new:</b> {e(str(i.get('originality', '')))}</p><p><b>Why:</b> {e(i.get('why', ''))}</p>"
            f"<table><tr><th>#</th><th>Len</th><th>Voiceover / text</th><th>Visual prompt</th></tr>{scenes}</table></details>")
    return "\n".join(out)


def _plan(plan):
    if not plan:
        return ("<p class='muted'>Run <code>python niche.py plan \"…\" --shorts 7 --longs 1</code> "
                "to see when you'd hit YPP and what it would pay.</p>")
    rows = "".join(
        f"<tr><td><b>{n}</b></td><td class='num'>{_n(s['views_per_short'])}</td><td class='num'>{_n(s['views_per_long'])}</td>"
        f"<td class='num'>{('month ' + str(s['ypp_month'])) if s['ypp_month'] else '<span class=bad>not reached</span>'}</td>"
        f"<td class='num'>{_n(s['final_subs'])}</td><td class='num'><b>{_usd(s['final_month_ad_rev'])}</b>/mo</td></tr>"
        for n, s in plan["scenarios"].items())
    return (f"<p>{e(plan['workload_note'])}</p><table><tr><th>Case</th><th class='num'>Views/Short</th>"
            f"<th class='num'>Views/long</th><th class='num'>YPP</th><th class='num'>Subs</th><th class='num'>Ads at end</th></tr>{rows}</table>"
            "<canvas id='planChart'></canvas>"
            f"<p class='small muted'>Slow, typical and good = 25th, 50th and 75th percentile of what small or young channels get here. "
            f"Assumes {round(plan['assumptions']['retention'] * 100)}% retention and {round(plan['assumptions']['monthly_improvement'] * 100)}% "
            "monthly improvement. YPP ad tier (AIR, 2026): 1,000 subs + 4,000 watch hours or 10M Shorts views in 90 days, "
            "rising to 8,000 h / 20M from 1 Feb 2027.</p>")


def render_report(a: dict, ideas: dict | None, path: Path, plan: dict | None = None) -> Path:
    m = a["money"]
    ent = a["entry"]
    c = a.get("comments", {})
    verdict = "".join(f"<li class='{v['level']}'><b>{e(v['area'])}</b> {e(v['text'])}</li>" for v in a["verdict"])

    fmt_cards = ""
    for f, s in a["formats"].items():
        if not s:
            continue
        pf = m["per_format"].get(f, {})
        fmt_cards += (f"<div class='card'><h3>{f}</h3><div class='kpis'>"
                      f"<div><span>{_n(s.get('new_channel_median'))}</span>new channel typical</div>"
                      f"<div><span>{_n(s.get('new_channel_p75'))}</span>new channel good</div>"
                      f"<div><span>{_n(s['p90_views'])}</span>top 10%</div>"
                      f"<div><span>{_n(s['max_views'])}</span>max</div>"
                      f"<div><span>{_usd((pf.get('rpm_low', 0), pf.get('rpm_high', 0)))}</span>per 1K views</div>"
                      f"<div><span>{_usd(pf.get('typical_new_video_usd'))}</span>ads per typical video</div></div>"
                      f"<p class='muted small'>{s['videos']} videos · {s['channels']} channels · median {_dur(s['median_duration_s'])}. "
                      f"“New channel” = under 10K subs or under 12 months old ({s['new_channel_sample']} videos).</p></div>")

    pf_rows = "".join(
        f"<div class='card'><h3>{e(f['concept'])}</h3><p class='muted small'>Broke out on <b>{f['channels']} channels</b> "
        f"({f['breakouts']} videos), median {f['median_outlier']}× their normal, {_n(f['median_views'])} views · "
        f"{e(', '.join(f'{k} {v}' for k, v in f['formats'].items()))}</p><ul>"
        + "".join(f"<li><a href='{e(x['url'])}' target='_blank'>{e(x['title'])}</a> <span class='muted small'>"
                  f"{e(str(x['channel_title']))} ({_n(x['subscribers'])} subs) · {_n(x['views'])} · {x['outlier']}×</span></li>"
                  for x in f["examples"]) + "</ul></div>"
        for f in a["proven_formats"][:8]) or "<p class='muted'>No format broke out on 2+ channels.</p>"

    econ = "".join(
        f"<tr><td>{e(r['channel'])}</td><td class='num'>{_n(r['subscribers'])}</td><td class='num'>{r['age_months'] or '–'} mo</td>"
        f"<td class='num'>{r['uploads_per_week']}</td><td class='num'>{_n(r['median_short'])}</td><td class='num'>{_n(r['median_long'])}</td>"
        f"<td class='num'><b>{_usd((r['ad_rev_month_low'], r['ad_rev_month_high']))}</b></td>"
        f"<td>{' '.join(t for t, ok in (('sponsors', r['sponsors']), ('affiliate', r['affiliate']), ('product', r['own_product'])) if ok) or '–'}</td></tr>"
        for r in m["channel_economics"])
    mix = " · ".join(f"{k} {round(v * 100)}%" for k, v in m.get("audience_mix", {}).items())

    young = "".join(f"<li><a href='{e(x['url'])}' target='_blank'>{e(x['title'])}</a> <span class='muted small'>· "
                    f"{e(str(x['channel_title']))}, {int(x['channel_age_days'] or 0)} days old, {_n(x['subscribers'])} subs → {_n(x['views'])} views</span></li>"
                    for x in ent["young_hit_examples"]) or "<li class='muted'>None.</li>"

    def lst(key, n=8):
        return "".join(f"<li>{e(x['text'])} <span class='muted small'>· {_n(x['likes'])} likes</span></li>"
                       for x in c.get(key, [])[:n]) or "<li class='muted'>None.</li>"

    durs = "".join(
        f"<div class='card'><h3>{k} length</h3><table><tr><th>Length</th><th class='num'>Videos</th><th class='num'>vs normal</th></tr>"
        + "".join(f"<tr><td>{b['bucket']}</td><td class='num'>{b['videos']}</td><td class='num'>{b['median_outlier']}×</td></tr>" for b in v)
        + "</table></div>" for k, v in a["duration"].items() if v)

    plan_js = json.dumps({n: [t["ad_rev_month"][1] for t in s["timeline"]] for n, s in (plan or {}).get("scenarios", {}).items()})

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(a['niche'])} · niche report</title>
<style>
:root{{--bg:#f6f5f1;--card:#fff;--ink:#1c1c1a;--muted:#6b6a64;--line:#e3e1d9;--accent:#b8502a;--good:#2e7a4c;--warn:#a86b00;--bad:#b3261e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141413;--card:#1e1e1c;--ink:#ecebe5;--muted:#9a988e;--line:#33322d;--accent:#e07a50;--good:#5cbf86;--warn:#e0a63c;--bad:#ef6f66}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1150px;margin:0 auto;padding:24px 16px 60px}}h1{{font-size:28px;margin:0}}h2{{margin:38px 0 12px;font-size:19px}}h3{{margin:0 0 8px;font-size:15px}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}.muted{{color:var(--muted)}}.small{{font-size:13px}}.bad{{color:var(--bad)}}
.grid{{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;overflow:auto}}
.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.kpis div{{font-size:12px;color:var(--muted)}}.kpis span{{display:block;font-size:19px;font-weight:650;color:var(--ink)}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}}th{{font-size:12px;color:var(--muted);font-weight:600}}
.num{{text-align:right;white-space:nowrap}}.tag{{display:inline-block;padding:1px 9px;margin:1px;border-radius:99px;background:var(--line);font-size:12px}}
ul{{padding-left:18px;margin:6px 0}}li{{margin:5px 0}}.verdict{{list-style:none;padding:0}}.verdict li{{padding:8px 12px;border-left:4px solid;border-radius:6px;background:var(--card);margin:6px 0}}
.verdict .pass{{border-color:var(--good)}}.verdict .warn{{border-color:var(--warn)}}.verdict .fail{{border-color:var(--bad)}}
details.idea{{margin:10px 0}}summary{{cursor:pointer}}code{{background:var(--line);padding:1px 5px;border-radius:4px}}canvas{{max-height:240px;margin-top:10px}}
</style></head><body><main>
<h1>{e(a['niche'])}</h1>
<p class="muted">YouTube · last {a['lookback_days']} days · {a['overall']['videos']} videos · {a['overall']['channels']} channels · scanned {e(a['scanned_at'][:16].replace('T', ' '))} UTC · channel baselines for {a['baseline_coverage_pct']}% of videos</p>

<h2>Verdict</h2><ul class="verdict">{verdict}</ul>

<h2>What a new channel gets</h2><div class="grid">{fmt_cards}</div>

<h2>Money</h2>
<div class="grid">
 <div class="card"><h3>Ad rates</h3><p>Category <b>{e(m['category'])}</b> · audience {e(mix)} → <b>{round(m['geo_multiplier'] * 100)}%</b> of US ad rates.</p>
 <p class="muted small">RPM source: {e(m['rpm_source'])}. Ad rates depend on where viewers are, not where you live; compare markets with <code>niche markets</code>.</p></div>
 <div class="card"><h3>Other income already in this niche</h3><div class="kpis">
  <div><span>{m['channels_with_sponsors_pct']}%</span>channels with regular sponsors</div>
  <div><span>{m['channels_with_affiliate_pct']}%</span>use affiliate links</div>
  <div><span>{m['channels_selling_own_product_pct']}%</span>sell their own product</div></div>
  <p class="muted small">Counted from each channel's last 30 uploads; occasional one-offs are ignored.</p></div>
</div>
<div class="card" style="margin-top:14px"><h3>What channels here earn from ads (lower bound)</h3>
<table><tr><th>Channel</th><th class="num">Subs</th><th class="num">Age</th><th class="num">Uploads/wk</th><th class="num">Median Short</th><th class="num">Median long</th><th class="num">Ads/month</th><th>Also earns from</th></tr>{econ}</table>
<p class="muted small">{e(m['note'])}</p></div>

<h2>Your path to monetization</h2><div class="card">{_plan(plan)}</div>

<h2>Proven formats</h2><p class="muted small">Title concepts that beat the channel's own normal by 3× or more, on at least 2 different channels. Use the format with a new premise; don't copy the title.</p>
<div class="grid">{pf_rows}</div>

<h2>Young channels that made it</h2><div class="card"><p class="muted small">{e(ent['hit_threshold'])}. Top 5 channels hold {ent['top5_view_share_pct']}% of views.</p><ul>{young}</ul></div>

<h2>Video plans</h2>{_ideas(ideas)}

<h2>Biggest breakouts</h2><div class="card">{_videos(a['breakouts'][:15])}</div>
<h2>Trending</h2><p class="muted small">Ranked by {e(a['trend_basis'])}</p><div class="card">{_videos(a['trending'], True)}</div>

<h2>Length that over-performs</h2><div class="grid">{durs or "<p class='muted'>Not enough data.</p>"}</div>

<h2>What the audience asks for</h2>
<div class="grid"><div class="card"><h3>Requests</h3><ul>{lst('top_requests')}</ul></div>
<div class="card"><h3>Questions</h3><ul>{lst('top_questions')}</ul></div>
<div class="card"><h3>Complaints</h3><ul>{lst('top_complaints', 6)}</ul></div></div>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const P={plan_js};
if(!window.Chart){{const c=document.getElementById('planChart');if(c)c.style.display='none';}}
if(window.Chart && document.getElementById('planChart') && Object.keys(P).length){{
 const css=getComputedStyle(document.documentElement);Chart.defaults.color=css.getPropertyValue('--muted').trim();
 const col={{slow:css.getPropertyValue('--warn').trim(),typical:css.getPropertyValue('--accent').trim(),good:css.getPropertyValue('--good').trim()}};
 const n=Math.max(...Object.values(P).map(v=>v.length));
 new Chart(planChart,{{type:'line',data:{{labels:[...Array(n).keys()].map(i=>'M'+(i+1)),
  datasets:Object.entries(P).map(([k,v])=>({{label:k+' (ads/month, high)',data:v,borderColor:col[k],tension:.3,pointRadius:0}}))}},
  options:{{scales:{{y:{{ticks:{{callback:v=>'$'+v}}}}}}}}}});
}}
</script></body></html>"""
    path.write_text(page, encoding="utf-8")
    return path
