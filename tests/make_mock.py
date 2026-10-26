"""Generate a realistic fake raw.json so analysis and report can be tested without an API key.
Usage: python tests/make_mock.py output/<slug>/raw.json"""
import json
import random
import sys
from datetime import datetime, timedelta, timezone

random.seed(7)
now = datetime.now(timezone.utc)
concepts = [
    "AI {x} takes over a Dhaka rickshaw", "What if AI ran a {x} shop?", "AI {x} vs angry auntie",
    "I let AI plan my {x} for 7 days", "AI {x} tries Bangladeshi street food", "{x} explained by AI cats",
    "Grandma reacts to AI {x}", "AI {x} at a Bengali wedding", "Why AI {x} keeps failing",
]
fill = ["robot", "chef", "teacher", "uncle", "barber", "doctor", "cricket team", "landlord"]


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


channels = {}
for i in range(30):
    cid = f"UC{i:04d}"
    subs = int(10 ** random.uniform(2.5, 6.3))
    created = now - timedelta(days=random.uniform(60, 3000) if i % 4 else random.uniform(40, 300))
    ups = []
    base_s, base_l = subs * random.uniform(0.05, 0.5), subs * random.uniform(0.02, 0.3)
    for j in range(30):
        short = random.random() < 0.65
        pub = now - timedelta(days=j * random.uniform(1, 4) + random.random())
        ups.append({"video_id": f"r{i}_{j}", "published_at": iso(pub), "duration_s": random.randint(15, 58) if short else random.randint(300, 1500),
                    "is_short": short, "views": int((base_s if short else base_l) * 10 ** random.gauss(0, 0.35)) + 30,
                    "category_id": "23", "has_sponsor": random.random() < (0.3 if i % 3 == 0 else 0.02),
                    "has_affiliate": random.random() < 0.1, "has_merch_or_product": random.random() < 0.05})
    channels[cid] = {"channel_id": cid, "title": f"Channel {i}", "subscribers": subs, "channel_views": subs * 80,
                     "video_count": random.randint(20, 900), "uploads_playlist": f"UU{i:04d}", "created_at": iso(created),
                     "country": random.choice(["BD", "US", None]), "hidden_subs": False, "recent_uploads": ups}

videos = []
for i in range(170):
    cid = random.choice(list(channels))
    c = channels[cid]
    short = random.random() < 0.6
    ups = [u for u in c["recent_uploads"] if u["is_short"] == short]
    base = sorted(u["views"] for u in ups)[len(ups) // 2] if ups else 1000
    concept = random.choice(concepts)
    t = concept.format(x=random.choice(fill))
    if random.random() < 0.25:
        t = "এআই রোবট যখন রিকশা চালায় 😂"
    views = int(base * 10 ** random.gauss(0.15 + (0.5 if "rickshaw" in concept or "wedding" in concept else 0), 0.45)) + 50
    pub = now - timedelta(days=random.uniform(0.5, 90))
    videos.append({"video_id": f"v{i}", "url": f"https://www.youtube.com/watch?v=v{i}", "title": t, "description": "",
                   "tags": [], "channel_id": cid, "channel_title": c["title"], "published_at": iso(pub), "thumbnail": None,
                   "duration_s": random.randint(12, 58) if short else random.randint(300, 1500), "is_short": short,
                   "views": views, "likes": int(views * random.uniform(0.01, 0.06)),
                   "comments": int(views * random.uniform(0.0005, 0.004)), "language": random.choice(["en", None, "bn"]),
                   "category_id": random.choice(["23", "24", "22"]), "has_sponsor": False, "has_affiliate": False,
                   "has_merch_or_product": False})
ctext = ["please make part 2 with the landlord 😂", "how did you make this? what app?", "this is literally me lol",
         "clickbait", "can you do one on cricket?", "AI slop again", "which tool do you use for the voice?",
         "more of the rickshaw series please", "too long, boring middle part", "the auntie at the end 💀💀"]
comments = [{"video_id": random.choice(videos)["video_id"], "text": random.choice(ctext), "likes": int(10 ** random.uniform(0, 4)),
             "replies": random.randint(0, 40)} for _ in range(400)]
raw = {"niche": "funny ai shorts", "scanned_at": now.isoformat(), "lookback_days": 90, "quota_units_used": 0,
       "videos": videos, "channels": channels, "comments": comments}
json.dump(raw, open(sys.argv[1], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("wrote", sys.argv[1])
