# YouTube Niche Research — v4 (full 3-tool expansion)

A Streamlit app with a landing screen and **three tools**, all sharing one engine
(`yt_dashboard.py`, unchanged) and one SQLite store.

## Files

| File | What it is |
|---|---|
| `app.py` | Shell: landing card grid, tool routing, shared quota/Claude wallet. |
| `tool_niche.py` | **Tool 1** — the original niche analyzer, **unchanged**, plus a run **archive** + cross-run **meta-analysis** panel. |
| `tool_video.py` | **Tool 2** — analyse one video (stats, niche placement, transcript, AI clips, risk hints, comment themes, **manual transcript paste**). |
| `tool_trends.py` | **Tool 3** — trend discovery (snapshot, trend-diff over time, category chart). |
| `yt_dashboard.py` | The engine. **Untouched** — keep your copy. |
| `storage.py` | SQLite: run archive, trend snapshots, transcript/comment caches, kv. |
| `meta_analysis.py` | Cross-run replication scoreboard, niche-over-time, channel watch, cost, diffs, regime-change. |
| `video_tools.py` | Tool 2 engine (pure + live). |
| `trends_tools.py` | Tool 3 engine (pure + live). |
| `archive.py` | Builds the structured run record Tool 1 saves. |
| `exports.py` | Markdown / CSV exporters. |
| `self_check.py` | **Offline** health check (no key/network). Run this first. |
| `test_dashboard.py` | Original engine tests (28). |
| `test_expansion.py` | Expansion tests (81). |
| `requirements.txt` | Dependencies. |

## Install & run (PyCharm terminal, Windows)

```bash
pip install -r requirements.txt
python self_check.py        # offline: confirms code + DB + pure pipelines
python test_dashboard.py    # expect 28 green
python test_expansion.py    # expect 81 green
streamlit run app.py
```

A `yt_store.db` is created next to the scripts on first save.

## What works offline vs needs your keys

**Works without keys/network** (all tested): app navigation, Tool 1 analysis logic,
the whole archive + meta-analysis, every pure pipeline in Tools 2/3 (URL parsing,
description mining, transcript math, risk hints, niche placement, trend clustering,
diffing, exports), and the **manual transcript paste**.

**Needs `YT_KEY`** (YouTube Data API): all live fetches — the video, niche peers,
trend snapshots, category chart.

**Needs `ANTHROPIC_API_KEY`** (Claude): AI clip nomination, comment themes, AI
meta-brief. (Tool 1's existing AI summary/ideas already used this.)

**Needs `youtube-transcript-api` + youtube.com reachable**: auto transcripts.
If unavailable, Tool 2 shows the manual paste box and everything else still runs.
Put keys in a `.env` next to the scripts: `YT_KEY=...` and `ANTHROPIC_API_KEY=...`.

## Honest-by-design (not bugs)

- **No copyright/strike oracle.** Risk reads are advertiser-friendliness *hints*
  from transcript text, with a "not Content ID" disclaimer.
- **No retention-based clipping.** AI nominates clips from transcript *content*,
  labeled as such ("most replayed" isn't in the API).
- **No editing detection.** Replaced with "watch these age-fair winners + text
  patterns."
- **Trend mode needs history.** A single snapshot shows what's *fast*, not *rising*.
  Save 2+ snapshots of a genre on different days, then use Trend mode.

## Reliability principles carried over

Age-fair velocity everywhere (never rank raw views/day across ages), per-format
effective-n (Kish) so a "trend" that's one channel says so, and every heuristic
labeled with what it rests on.
