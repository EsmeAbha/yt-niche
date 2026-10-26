"""Facebook dashboard: your Page, competitors/logged Reels, proven formats, and the monetization facts."""
from __future__ import annotations

import html
from pathlib import Path

from .report import _n

e = html.escape

FACTS = [
    ("Invite-only", "Since 31 Aug 2025, in-stream ads, Reels ads and the performance bonus are one program, "
     "Facebook Content Monetization. You can only express interest; Meta invites. Bangladeshi Pages are already in it.",
     "https://bangla.bdnews24.com/bangladesh/9snd7h0s72"),
    ("Payout in Bangladesh", "One Bangladeshi Page reported earnings it couldn't withdraw because no payment method was set up. "
     "Set up payouts the day you're invited.", "https://bangla.bdnews24.com/bangladesh/9snd7h0s72"),
    ("Unoriginal content", "Reposting others' videos, stitching clips together or just adding a watermark loses monetization and reach. "
     "Reactions and your own take are allowed.", "https://techcrunch.com/2025/07/14/following-youtube-meta-announces-crackdown-on-unoriginal-facebook-content"),
    ("No official rate", "Meta publishes no per-view rate; creator reports vary widely. Use your Professional Dashboard's "
     "earnings estimate once invited, not internet calculators.", "https://www.socialchamp.com/blog/facebook-monetization/"),
    ("Creator Fast Track", "Meta reported guaranteed monthly payments for creators with 100K+ followers elsewhere who post "
     "15 Reels on 10 days a month. Country availability wasn't stated.", "https://bangla.bdnews24.com/tech/2ece9452e870"),
]


def _mine_rows(rows):
    if not rows:
        return "<p class='muted'>None.</p>"
    head = ("<tr><th>Post</th><th>Type</th><th class='num'>Plays</th><th class='num'>vs your normal</th>"
            "<th class='num'>Watched</th><th class='num'>New followers</th></tr>")
    body = "".join(
        f"<tr><td><a href='{e(str(r.get('url', '')))}' target='_blank'>{e((str(r.get('caption') or '(no caption)')).splitlines()[0][:110])}</a>"
        f"<div class='muted small'>{int(r.get('length_s') or 0)}s · {e(str(r.get('created', ''))[:10])}</div></td>"
        f"<td>{e(str(r.get('type', '')))}</td><td class='num'>{_n(r.get('plays'))}</td>"
        f"<td class='num'><b>{'–' if r.get('outlier') is None or r.get('outlier') != r.get('outlier') else str(round(r['outlier'], 1)) + '×'}</b></td>"
        f"<td class='num'>{'–' if r.get('watched_pct') is None or r.get('watched_pct') != r.get('watched_pct') else str(r['watched_pct']) + '%'}</td>"
        f"<td class='num'>{_n(r.get('followers_gained'))}</td></tr>" for r in rows)
    return f"<table>{head}{body}</table>"


def _rows(rows, metric):
    if not rows:
        return "<p class='muted'>None.</p>"
    head = (f"<tr><th>Post</th><th>Type</th><th class='num'>{e(metric)}</th><th class='num'>vs page normal</th>"
            "<th class='num'>Shares</th></tr>")
    body = "".join(
        f"<tr><td><a href='{e(str(r.get('url', '')))}' target='_blank'>{e((str(r.get('caption') or '(no caption)')).splitlines()[0][:110])}</a>"
        f"<div class='muted small'>{e(str(r.get('page', '')))} · {_n(r.get('followers'))} followers</div></td>"
        f"<td>{e(str(r.get('type', '')))}</td><td class='num'>{_n(r.get(metric))}</td>"
        f"<td class='num'><b>{'–' if r.get('outlier') is None or r.get('outlier') != r.get('outlier') else str(round(r['outlier'], 1)) + '×'}</b></td>"
        f"<td class='num'>{_n(r.get('shares'))}</td></tr>" for r in rows)
    return f"<table>{head}{body}</table>"


def _formats(fs):
    return "".join(
        f"<div class='card'><h3>{e(f['concept'])}</h3><p class='muted small'>Broke out on <b>{f['channels']} Pages</b>, "
        f"median {f['median_outlier']}× their normal</p><ul>"
        + "".join(f"<li><a href='{e(x['url'])}' target='_blank'>{e(x['title'][:100])}</a> <span class='muted small'>{e(str(x['channel_title']))} · {x['outlier']}×</span></li>"
                  for x in f["examples"]) + "</ul></div>" for f in fs[:6]) or "<p class='muted'>No format broke out on 2+ Pages yet.</p>"


def render_fb(mine: dict | None, others: dict | None, path: Path, title: str = "Facebook") -> Path:
    facts = "".join(f"<li class='warn'><b>{e(t)}</b> {e(x)} <a href='{e(u)}' target='_blank'>source</a></li>" for t, x, u in FACTS)
    mine_html = "<p class='muted'>Not connected. Run <code>python niche.py fb-mine</code> once your Page token is in config.yaml.</p>"
    if mine and "error" not in mine:
        bt = "".join(f"<div><span>{_n(v['median_plays'])}</span>median plays per {k} ({v['posts']})</div>"
                     f"<div><span>{v['median_watched_pct'] or '–'}%</span>avg watched ({k})</div>"
                     f"<div><span>{v['median_follows_per_1k'] or '–'}</span>follows per 1K plays ({k})</div>"
                     for k, v in mine["by_type"].items())
        countries = ", ".join(f"{c} {p}%" for c, p in mine["audience_countries"]) or "not available (Reels don't report country)"
        lens = "".join(f"<tr><td>{x['length']}</td><td class='num'>{x['posts']}</td><td class='num'>{_n(x['median'])}</td>"
                       f"<td class='num'>{x['median_outlier'] or '–'}×</td></tr>" for x in mine["lengths"])
        mine_html = (f"<div class='card'><h3>{e(mine['page'].get('name', ''))} · {_n(mine['page'].get('followers_count'))} followers</h3>"
                     f"<div class='kpis'>{bt}</div><p class='small'><b>Who watches (long videos):</b> {e(countries)}</p></div>"
                     f"<h3 style='margin-top:18px'>Your breakouts</h3><div class='card'>{_mine_rows(mine['best'])}</div>"
                     f"<h3 style='margin-top:18px'>What brings followers</h3><div class='card'>{_mine_rows(mine['followers_drivers'])}</div>"
                     f"<h3 style='margin-top:18px'>Your flops</h3><div class='card'>{_mine_rows(mine['worst'])}</div>"
                     + (f"<h3 style='margin-top:18px'>Length</h3><div class='card'><table><tr><th>Length</th><th class='num'>Posts</th>"
                        f"<th class='num'>Median plays</th><th class='num'>vs normal</th></tr>{lens}</table></div>" if lens else "")
                     + f"<h3 style='margin-top:18px'>Your topics that keep beating your normal</h3><div class='grid'>{_formats(mine['formats'])}</div>")
    oth_html = ("<p class='muted'>No competitor data. Either list Pages under <code>facebook.watch_pages</code> "
                "(needs Page Public Content Access) and run <code>fb-watch</code>, or log Reels by hand with <code>fb-log</code>.</p>")
    if others:
        bt = " · ".join(f"{k}: {v['posts']} posts, median {_n(list(v.values())[1])}, {v['median_outlier'] or '–'}× normal"
                        for k, v in others["by_type"].items())
        oth_html = (f"<p class='muted small'>{others['posts']} posts from {others['pages']} Pages · {e(others['note'])}</p>"
                    f"<p class='small'><b>By type:</b> {e(bt)}</p>"
                    f"<div class='card'>{_rows(others['breakouts'], others['metric'])}</div>"
                    f"<h3 style='margin-top:18px'>Most shared (shares as % of engagement)</h3><div class='card'>{_rows(others['most_shared'], others['metric'])}</div>"
                    f"<h3 style='margin-top:18px'>Formats that broke out on 2+ Pages</h3><div class='grid'>{_formats(others['formats'])}</div>")

    css = Path(__file__).with_name("report.py").read_text(encoding="utf-8")
    style = css[css.index("<style>"): css.index("</style>") + 8].replace("{{", "{").replace("}}", "}")
    page = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)} · Facebook</title>{style}</head><body><main><h1>{e(title)}</h1>"
            f"<h2>Facebook money: the facts that matter</h2><ul class='verdict'>{facts}</ul>"
            f"<h2>Your Page</h2>{mine_html}<h2>Competitors and logged Reels</h2>{oth_html}</main></body></html>")
    path.write_text(page, encoding="utf-8")
    return path
