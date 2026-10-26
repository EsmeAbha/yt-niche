# Niche Studio

Find a niche that **pays**, in the market that pays most, then make videos that **stay monetized**.

## Start (Windows)

1. Install Python 3.12 and FFmpeg once: `winget install Python.Python.3.12 Gyan.FFmpeg`
2. Double-click **setup.bat** once. It installs everything, all free.
3. Double-click **start.bat**. Niche Studio opens in your browser.
4. In **Settings**, paste your free YouTube API key. That's the only thing you need to start.

The app has a page for each step: Find a niche → Niche report → Money plan → Ideas → Studio (render, add Flow clips or your own voice, watch, upload) → Facebook → Settings. The **Home** page shows what's connected and what's missing.

The command line below does the same things, if you prefer it.

```
python niche.py markets "funny robot sketches" --translate   # same niche in US, UK, DE, JP, FR, BD... ranked by income
python niche.py scan "funny robot sketches" --market us --open
python niche.py plan "funny robot sketches" --market us --hours 15
python niche.py ideas "funny robot sketches" --market us -n 6
python niche.py make "funny robot sketches" --market us --idea 1,2
python niche.py approve "funny robot sketches" --market us --idea 1 --note "Rewrote the ending, recorded my own voice"
python niche.py upload "funny robot sketches" --market us --idea 1 --yt --schedule 2026-11-01T20:00
```

## What it tells you, and how it's calculated

| Question | How it's answered |
|---|---|
| **What will a new channel get?** | Views for videos from channels under 10K subs or under 12 months old (25th/50th/75th percentile). Mega-channels aren't averaged in, because their numbers aren't yours. |
| **Which formats are proven?** | Videos that beat their **own channel's normal by 3×+**. Shorts and long-form are judged against separate baselines. Breakout titles are grouped by concept, and a concept counts only if it broke out on **2+ different channels**. One channel's hit could be luck or an existing fanbase. |
| **Does it pay?** | RPM range for the niche's category, from AIR Media-Tech's 2026 data where available and marked as an assumption where not. It's adjusted for **where the viewers are**, because YouTube pays by viewer country, not by where you live. It also shows which channels show **regular sponsors, affiliate links or their own products**, and a lower-bound **monthly ad income for the top channels**. |
| **Which market?** | `markets` scans the same niche on each country's YouTube in its language (US, UK, AU, DE, Nordics, JP, FR, ES, LatAm, BR, BD). It then ranks them by projected income for a new channel. You can make English or German videos from Bangladesh, and the edge-tts voices cover every market. |
| **When do I get paid?** | `plan` runs a week-by-week projection: subs, watch hours and 90-day Shorts views against the YPP thresholds, including the rise on 1 Feb 2027. It gives slow, typical and good cases, then ad income per month. `--hours 15` finds the best mix of Shorts and long videos for your time. |
| **Is it allowed?** | Flags the July 2026 YPP problem areas: distress or rescue bait, AI personas giving finance, legal or medical advice, made-for-kids content, and reused clips. |
| **What's actually trending?** | `track` re-reads the videos it already found, costing about 1 quota unit per 50 videos with no search, and measures **real views/day between scans** plus acceleration. Run it daily. |

Every verdict line says *why*. There is no blended "virality score" with hidden weights.

## How the videos stay monetizable

Since July 2026, YouTube doesn't monetize "generic, repetitive or template-based" AI videos. The production side is built around that rule:

1. **Series bible** (`channel/bible.md`): your original character, world and running jokes. Every plan follows it, which keeps videos consistent and recognisably yours.
2. **Character image** (`channel/character.png`): with an image-to-video workflow (`{{IMAGE}}` placeholder), the character looks the same in every shot and every video.
3. **Proven format, new premise.** Plans must name the format they use and what's new about them.
4. **Originality guard.** An idea is blocked if it's too close to your past uploads (repetitive), a one-word swap of someone else's title (a copy), or a near-duplicate of another idea in the same batch.
5. **Your voice.** Drop `audio/my_vo_01.m4a` (one per scene) into a project and it replaces TTS. This is the strongest "human contribution" signal there is.
6. **Approval gate.** `upload` refuses anything you haven't `approve`d with a note of what you checked or changed. Your notes become your record if YPP review asks.
7. **Daily cap.** At most 3 uploads a day by default. Placeholder shots can never be uploaded.

## Facebook

Meta only gives full data for **your own Page**, so the Facebook side works from three sources:

| Command | Data | Access needed |
|---|---|---|
| `python niche.py fb-mine` | Every Reel and video on your Page: plays, % watched, followers gained, views by country (long videos), all against your own normal. Shows your breakouts, flops, and what brings followers. | Your Page token (free) |
| `python niche.py fb-watch --pages Page1 Page2` | Competitor Pages' public posts, ranked by reactions + comments + shares against each Page's normal. Shows proven formats across Pages and which posts get shared most. | "Page Public Content Access" (free, but Meta must approve your app) |
| `python niche.py fb-log reels.csv` | Reels you note down while scrolling: link, Page, followers, views, reactions, comments, shares. Same analysis. `fb-log --template` gives you the sheet. | Nothing |

Everything lands in `output/facebook/report.html`, together with the money facts that matter:
- Facebook Content Monetization is **invite-only** (one program since 31 Aug 2025), and Bangladeshi Pages are in it.
- Set up payouts as soon as you're invited; one Bangladeshi Page couldn't withdraw its earnings.
- Reposts and stitched clips lose monetization.
- There is **no official per-view rate**, so the tool doesn't invent one.

Publishing to your Page (Reels or videos) works through `upload --fb`.

Meta doesn't expose other Pages' view counts through any official API, so there is no Facebook equivalent of the YouTube niche scan. YouTube's breakouts are the best free signal for what will travel to Facebook. Run `scan` on YouTube, then test the top formats on your Page and let `fb-mine` tell you what worked.

## Cost: $0

| Part | Free option used |
|---|---|
| YouTube research and uploads | YouTube Data API (free quota: 10,000 units/day) |
| Facebook analytics and uploads | Graph API (free) |
| Idea writing | Ollama + Qwen3 14B on your GPU (Gemini API is optional) |
| Video shots | ComfyUI + Wan 2.2 (open weights) on your GPU |
| Hero shots | Google Flow, which you already pay for; set `veo_hero_shots_per_video: 0` to skip it |
| Voice | edge-tts (free, online) or Piper (free, offline), or your own voice |
| Editing, captions, thumbnails | FFmpeg + Pillow |
| Music | Your own tracks, or free libraries (YouTube Audio Library, Facebook Sound Collection); check each track's licence for the other platform |
| Scheduling | Windows Task Scheduler |

The only real cost is electricity for the GPU.

## Setup (Windows)

1. Install tools:
   ```
   winget install Python.Python.3.12 Gyan.FFmpeg
   python -m venv .venv && .venv\Scripts\activate
   pip install -r requirements.txt
   copy config.example.yaml config.yaml
   ```
2. **YouTube API key**: in console.cloud.google.com, enable *YouTube Data API v3*, create an API key and put it in `config.yaml`. You get 10,000 units a day; one scan costs about 300–500, and `track` costs almost nothing.
3. **Ideas**: install Ollama and run `ollama pull qwen3:14b`. Or set `llm.provider: none` and use `/niche-ideas` in Claude Code.
4. **ComfyUI** (local renders on the RTX 5080):
   - Load the Wan 2.2 5B template, either text-to-video or image-to-video for character consistency.
   - Use **Export (API)** and save the result as `workflows/t2v_api.json`.
   - Replace the values with placeholders: `{{PROMPT}}`, `{{NEGATIVE}}`, `{{SEED}}`, `{{WIDTH}}`, `{{HEIGHT}}`, `{{FRAMES}}`, `{{PREFIX}}`, and optionally `{{IMAGE}}`.
5. **Google Flow (Veo)**: each project's `flow_prompts.md` lists its 2 hero shots. Make them in Flow and save them as `flow_inbox/shot_XX.mp4`, then re-run `make`. Google AI Pro has no API, so this one step is manual.
6. **Uploads**:
   - YouTube needs an OAuth Desktop client saved as `secrets/client_secret.json`. Uploads made through the API stay private until Google audits your project.
   - Facebook needs a Page token with `pages_manage_posts` and `publish_video`.

## Honest limits

- **RPMs and audience multipliers are estimates.** Once you have your own YouTube Studio numbers, put them in `config.yaml` (`money.rpm`, `money.geo_multiplier`, `planner`) and every projection becomes yours.
- **Audience geography of other people's videos isn't public.** It's inferred from the market searched, or from the title script and language.
- **Ad income for top channels counts only their last 30 days of uploads**, so it's a floor.
- **Facebook niche data has no public API.** Facebook is publish-only.
- **In most niches, Shorts pay cents per 1,000 views.** The plan will usually tell you that long-form, sponsors or a product is where the money is. Believe it.
