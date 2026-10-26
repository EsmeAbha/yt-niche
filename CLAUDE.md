# Niche Studio

Goal: income, not views, at zero cost (free APIs + local GPU). Flow: markets -> scan -> plan -> ideas -> make -> upload.
CLI: `python niche.py <markets|scan|plan|track|ideas|make|approve|upload|run|compare|report> "<niche>" [--market us]`.
Facebook: `fb-mine` (own Page), `fb-watch` (competitor Pages), `fb-log <csv>` (hand-logged Reels), `fb-report`.
Outputs in output/<slug>/ and output/facebook/. Skills: /niche-scan, /niche-ideas, /niche-produce, /niche-fb.
Rules: upload only when the user says so; upload limits and approval are the user's choice (config `upload:`);
keep API keys in config.yaml or env vars; never add a paid service as a default.
