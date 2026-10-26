"""Will this niche pay me, and when? A week-by-week projection from what NEW channels actually get.

Inputs come from the scan, not wishful thinking: views per video for small or young channels
(25th / 50th / 75th percentile = slow / typical / good), the niche's RPM for that audience, and your
posting cadence. Assumptions you should replace with your own Studio data once you have it live in
config.yaml under `planner:`.
"""
from __future__ import annotations

from datetime import date, timedelta

DEFAULTS = {
    "retention": 0.35,            # avg % of a long video watched (YouTube typical 30-45%)
    "subs_per_1k_short": 0.5,     # Shorts viewers rarely subscribe
    "subs_per_1k_long": 4.0,
    "monthly_improvement": 0.04,  # you get better every month (thumbnails, hooks); 0 = flat
    "months": 18,
}


def _assumptions(cfg):
    return {**DEFAULTS, **(cfg.get("planner") or {})}


def project(a: dict, cfg: dict, shorts_per_week: float, longs_per_week: float, start: date | None = None) -> dict:
    from .money import ypp_rules
    ass = _assumptions(cfg)
    rules = ypp_rules(cfg)
    start = start or date.today()
    pf = a["money"]["per_format"]
    fs, fl = a["formats"].get("Shorts") or {}, a["formats"].get("Long-form") or {}
    long_dur = fl.get("median_duration_s", 600)
    scen = {}
    for name, key in (("slow", "new_channel_p25"), ("typical", "new_channel_median"), ("good", "new_channel_p75")):
        vs = fs.get(key) or fs.get("new_channel_p25") or 0
        vl = fl.get(key) or fl.get("new_channel_p25") or 0
        weeks = int(ass["months"] * 4.345)
        subs, monetized_week = 0.0, None
        short_hist, long_hours_hist, monthly = [], [], []
        week_rev = []
        for w in range(weeks):
            today = start + timedelta(weeks=w)
            boost = (1 + ass["monthly_improvement"]) ** (w / 4.345)
            s_views = shorts_per_week * vs * boost
            l_views = longs_per_week * vl * boost
            subs += s_views / 1000 * ass["subs_per_1k_short"] + l_views / 1000 * ass["subs_per_1k_long"]
            short_hist.append(s_views)
            long_hours_hist.append(l_views * long_dur * ass["retention"] / 3600)
            sv90 = sum(short_hist[-13:])
            wh12 = sum(long_hours_hist[-52:])
            new_rules = today >= date(2027, 2, 1) and monetized_week is None
            need_wh = rules["from_2027_02_01"]["watch_hours_12m"] if new_rules else rules["watch_hours_12m"]
            need_sv = rules["from_2027_02_01"]["shorts_views_90d"] if new_rules else rules["shorts_views_90d"]
            if monetized_week is None and subs >= rules["subs"] and (wh12 >= need_wh or sv90 >= need_sv):
                monetized_week = w
            if monetized_week is not None:
                lo = s_views / 1000 * pf.get("Shorts", {}).get("rpm_low", 0) + l_views / 1000 * pf.get("Long-form", {}).get("rpm_low", 0)
                hi = s_views / 1000 * pf.get("Shorts", {}).get("rpm_high", 0) + l_views / 1000 * pf.get("Long-form", {}).get("rpm_high", 0)
                week_rev.append((lo, hi))
            else:
                week_rev.append((0, 0))
            if int((w + 1) / 4.345) > len(monthly) or w == weeks - 1:
                monthly.append({"month": len(monthly) + 1, "subs": int(subs), "watch_hours_12m": int(wh12),
                                "shorts_views_90d": int(sv90), "monetized": monetized_week is not None,
                                "ad_rev_month": [round(sum(r[0] for r in week_rev[-4:])), round(sum(r[1] for r in week_rev[-4:]))]})
        scen[name] = {
            "views_per_short": int(vs), "views_per_long": int(vl),
            "ypp_month": round(monetized_week / 4.345, 1) if monetized_week is not None else None,
            "final_month_ad_rev": monthly[-1]["ad_rev_month"] if monthly else [0, 0],
            "final_subs": int(subs), "timeline": monthly,
        }
    return {"shorts_per_week": shorts_per_week, "longs_per_week": longs_per_week, "assumptions": ass,
            "rules": rules, "scenarios": scen,
            "workload_note": f"{shorts_per_week:g} Shorts + {longs_per_week:g} long videos a week, about "
                             f"{shorts_per_week * 0.75 + longs_per_week * 5:.0f} hours of your time if each Short "
                             "takes about 45 min and each long video about 5 h including review."}


def best_mix(a: dict, cfg: dict, hours_per_week: float = 15) -> list[dict]:
    """Try cadences that fit your weekly hours and rank them by typical-case income at the end of the plan."""
    out = []
    for longs in (0, 1, 2, 3):
        left = hours_per_week - longs * 5
        if left < 0:
            continue
        shorts = min(int(left / 0.75), 14)
        p = project(a, cfg, shorts, longs)
        t = p["scenarios"]["typical"]
        out.append({"shorts_per_week": shorts, "longs_per_week": longs, "ypp_month_typical": t["ypp_month"],
                    "ad_rev_month_typical": t["final_month_ad_rev"], "ypp_month_slow": p["scenarios"]["slow"]["ypp_month"]})
    return sorted(out, key=lambda r: -(r["ad_rev_month_typical"][1]))
