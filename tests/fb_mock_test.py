"""Exercise the Facebook analysis + report with fake Graph API responses (no token needed)."""
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from niche_studio.config import load_config  # noqa: E402
from niche_studio.fb_analyze import analyze_engagement, analyze_mine, watch_frame  # noqa: E402
from niche_studio.fb_report import render_fb  # noqa: E402

random.seed(3)
now = datetime.now(timezone.utc)
caps = ["When the landlord finds out about the new tenant", "Bengali mom vs AI robot", "AI robot tries to bargain at the bazaar",
        "Load shedding but the robot is the lamp", "Rickshaw robot takes a shortcut", "Robot at a Bengali wedding"]
items = []
for i in range(40):
    reel = random.random() < 0.8
    plays = int(8000 * 10 ** random.gauss(0, 0.5)) * (4 if "wedding" in caps[i % 6] else 1)
    length = random.randint(12, 55) if reel else random.randint(120, 600)
    ins = ({"fb_reels_total_plays": plays, "post_video_avg_time_watched": int(length * random.uniform(0.3, 0.8) * 1000),
            "post_video_followers": int(plays / 1000 * random.uniform(0.5, 6)),
            "post_video_social_actions": {"REACTION": plays // 40, "COMMENT": plays // 400, "SHARE": plays // 300}}
           if reel else {"total_video_views": plays, "total_video_avg_time_watched": int(length * 0.25 * 1000),
                         "total_video_views_by_country_id": {"BD": plays * 0.6, "IN": plays * 0.2, "US": plays * 0.1, "SA": plays * 0.1}})
    items.append({"id": f"m{i}", "kind": "reel" if reel else "video", "description": caps[i % 6] + f" part {i}",
                  "created_time": (now - timedelta(days=i * 2)).isoformat(), "length": length,
                  "permalink_url": f"https://facebook.com/reel/m{i}", "insights": ins})
mine = {"page": {"id": "P1", "name": "My Robot Page", "followers_count": 12000}, "items": items}

watch = {}
for p in range(5):
    posts = []
    for j in range(30):
        c = random.choice(caps)
        eng = int(2000 * 10 ** random.gauss(0, 0.4)) * (5 if ("wedding" in c or "bazaar" in c) else 1)
        posts.append({"id": f"{p}_{j}", "created_time": (now - timedelta(days=j)).isoformat(), "message": c,
                      "permalink_url": f"https://facebook.com/{p}/posts/{j}", "shares": {"count": eng // 20},
                      "attachments": {"data": [{"media_type": random.choice(["video", "video", "photo"])}]},
                      "reactions": {"summary": {"total_count": eng}}, "comments": {"summary": {"total_count": eng // 15}}})
    watch[f"C{p}"] = {"page": {"id": f"C{p}", "name": f"Competitor {p}", "followers_count": 10 ** random.uniform(4, 6.3)},
                      "posts": posts}

cfg = load_config()
m = analyze_mine(mine, cfg)
o = analyze_engagement(watch_frame(watch), "watch")
print("mine types:", m["by_type"])
print("countries:", m["audience_countries"])
print("best:", [(r["caption"][:30], r["outlier"]) for r in m["best"][:3]])
print("formats mine:", [(f["concept"], f["channels"]) for f in m["formats"]])
print("others:", o["metric"], o["by_type"], [(f["concept"], f["channels"]) for f in o["formats"][:3]])
out = cfg["_output"] / "facebook"
out.mkdir(parents=True, exist_ok=True)
json.dump(m, open(out / "mine.json", "w"), default=str)
json.dump(o, open(out / "others.json", "w"), default=str)
print(render_fb(m, o, out / "report.html"))
