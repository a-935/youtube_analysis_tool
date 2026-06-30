# 🎬 YouTube Niche Research

A local **Streamlit** app that helps a creator decide what to make next — built on one rule: **be honest about what the data can and can't tell you.** Every number is shown with the context that makes it meaningful, and every heuristic says what it rests on.

It bundles three tools behind one landing screen:

| Tool | What it does | Use it to… |
|------|--------------|------------|
| 🔬 **Niche / Genre Analysis** | Pulls recent videos for a topic, splits Shorts vs long-form, and surfaces what's over/under-performing and what the winners do differently. Saves every run to an archive for cross-run **replication** analysis. | Figure out the patterns that actually hold up in a niche over time. |
| 🎬 **Single-Video Teardown** | Deep-dives one video: how it performed **vs the creator's own channel**, an AI "what to steal," the moments the **audience flagged**, a plain-English **summary**, and **Short-ability** ratings for clips. | Learn exactly what to copy from a video — and which parts can become Shorts. |
| 📈 **Trend Discovery** | Pick a broad area (Gaming, Cooking, …) and get the **specific** trending sub-niches inside it, each with its most popular videos and a **breadth** label (many channels vs one viral hit). | Find rising, under-served topics worth jumping on. |

---

## The one idea that makes it trustworthy: age-fair velocity

A brand-new video and a year-old video can't be compared on raw views — the old one had more time. Ranking by raw "views per day" quietly rewards whatever is newest. So every pattern in this app is scored **within age bands**: a video is compared only to others of a *similar age*. Old-vs-new becomes a fair fight, and "what's actually working" stops being "what's just newest."

Two more honesty rules run throughout:
- **Effective-n on every claim.** If a "trend" is really one channel posting ten times, the app says so (Kish effective sample size), instead of pretending it's broad.
- **Heuristics are labelled, never dressed up.** Clip ideas come from transcript *content* (not retention data, which the API doesn't expose). "Risk" reads are advertiser-friendliness *hints* from text, not a copyright oracle. Editing style isn't detected — the app points you to winners to study instead.

---

## Quick start

```bash
# 1. install dependencies
pip install -r requirements.txt

# 2. add your API keys (see .env.example)
#    create a file named  .env  next to app.py:
#    YT_KEY=your_youtube_data_api_key
#    ANTHROPIC_API_KEY=your_anthropic_key

# 3. (optional) confirm the code is healthy — no keys/network needed
python self_check.py

# 4. run it
streamlit run app.py
```

Open the local URL Streamlit prints (usually `http://localhost:8501`).

### Getting the keys
- **`YT_KEY`** — a YouTube Data API v3 key from the [Google Cloud Console](https://console.cloud.google.com/). Free tier is 10,000 units/day (plenty; a typical analysis costs a few hundred).
- **`ANTHROPIC_API_KEY`** — from the [Anthropic Console](https://console.anthropic.com/). Powers the AI summaries, teardowns, and clip nominations.

The app opens and navigates fine without keys — it just can't fetch live data until they're set.

---

## What's tested

```bash
python test_dashboard.py    # core engine
python test_expansion.py    # the three-tool expansion
python self_check.py        # offline health check (imports, DB, pure logic)
```

All the offline logic (age-fair scoring, clustering, replication, transcript parsing, exports) is covered by synthetic tests — no API key required.

---

## Honest limits (by design, not bugs)

- **No copyright/strike prediction.** Advertiser-friendliness reads are *hints* from transcript text.
- **No retention/"most replayed" data.** It isn't in the API. Clip ideas come from content; the closest honest signal is the timestamps the *audience itself* quotes in comments.
- **No editing-style detection.** Can't be done via API; the app shows age-fair winners to study instead.
- **Trend "acceleration" needs history.** A single snapshot shows what's *fast*, not *rising* — save snapshots over time to see real movement.
- **Transcripts** are auto-fetched where possible (YouTube sometimes blocks this); a paste box is always available as a fallback.

---

## Project layout

```
app.py            landing screen + tool routing + shared quota/credit wallet
tool_niche.py     Tool 1 UI + run archive & cross-run meta-analysis
tool_video.py     Tool 2 UI (video teardown)
tool_trends.py    Tool 3 UI (trend discovery)
yt_dashboard.py   the core engine (YouTube fetch, age-fair scoring, AI calls)
storage.py        SQLite: run archive, snapshots, transcript/comment caches
meta_analysis.py  cross-run replication scoreboard & friends
video_tools.py    Tool 2 engine        trends_tools.py  Tool 3 engine
archive.py        builds saved-run records   exports.py   Markdown / CSV export
self_check.py     offline health check
requirements.txt  dependencies
```

---

## Tech

Python · Streamlit · YouTube Data API v3 · Anthropic Claude API · SQLite · pandas

## License

MIT — see `LICENSE`.
