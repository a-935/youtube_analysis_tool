"""
exports.py — turn results into downloadable Markdown / CSV (Plan §5 'export to report')
=======================================================================================
All pure string-builders. No DB, no engine — trivially testable.
"""

import csv
import io


def videos_to_csv(videos):
    """Every field we have, one row per video. Returns a CSV string."""
    cols = ["id", "title", "channel", "published", "views", "likes", "comments",
            "like_rate", "comment_rate", "views_per_day", "duration_sec",
            "age_days", "is_short", "subs", "views_per_sub", "url"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for v in videos:
        w.writerow({c: v.get(c, "") for c in cols})
    return buf.getvalue()


def run_to_markdown(run):
    """A saved niche run -> a readable report."""
    L = [f"# Niche run — {run.get('topic', '(unknown)')}",
         f"_{run.get('ts', '')}_  ·  region: {run.get('region', '—')}  ·  "
         f"{run.get('n_videos', 0)} videos ({run.get('n_shorts', 0)} Shorts)",
         ""]
    if run.get("note"):
        L += [f"> {run['note']}", ""]

    m = run.get("metrics") or {}
    if m:
        L += ["## Headline metrics",
              f"- Median velocity — Shorts {m.get('median_velocity_short', 0):,}/day, "
              f"long-form {m.get('median_velocity_long', 0):,}/day",
              f"- Effective-n — Shorts {m.get('effective_n_short', '—')}, "
              f"long-form {m.get('effective_n_long', '—')}",
              f"- Freshness (median age): {m.get('freshness_days', '—')} days", ""]

    sig = run.get("signals") or {}
    if sig:
        L += ["## Signal verdicts"]
        for k, s in sig.items():
            L.append(f"- **{k}**: {s.get('verdict') or '—'} "
                     f"(top {s.get('top')} vs bottom {s.get('bottom')})")
        L.append("")

    outs = run.get("top_outliers") or []
    if outs:
        L += ["## Top outliers"]
        for o in outs:
            sc = f" ({o['score']}×)" if o.get("score") else ""
            L.append(f"- {o.get('channel', '—')} — {o.get('title', '')}{sc}")
        L.append("")

    if run.get("ai_brief"):
        L += ["## AI brief", run["ai_brief"], ""]
    return "\n".join(L)


def scoreboard_to_markdown(scoreboard):
    """The replication scoreboard -> markdown table."""
    L = ["# Signal replication scoreboard", "",
         "| Signal | Verdict | Direction | Agreement | Runs | ↑ | ↓ | ~ |",
         "|---|---|---|---:|---:|---:|---:|---:|"]
    for s in scoreboard:
        L.append(f"| {s['signal']} | {s['classification']} | {s['dominant']} | "
                 f"{s['agreement']:.0%} | {s['runs_seen']} | {s['higher']} | "
                 f"{s['lower']} | {s['none']} |")
    return "\n".join(L)


def trends_to_markdown(snapshot):
    """A trend snapshot -> markdown."""
    L = [f"# Trend snapshot — {snapshot.get('topic', '(genre)')}",
         f"_{snapshot.get('ts', '')}_  ·  {snapshot.get('n_trends', 0)} trends from "
         f"{snapshot.get('n_videos', 0)} videos", ""]
    for t in snapshot.get("trends", []):
        L += [f"## {t['trend']}  ·  {t['stage']}",
              f"- {t['n_videos']} videos · {t['channels']} channels · "
              f"effective-n {t['effective_n']}",
              f"- median {t['median_views']:,} views · heat {t['heat']} · "
              f"opportunity {t['opportunity']}",
              f"- freshness: {t['median_age_days']} days"]
        for ex in t.get("examples", []):
            L.append(f"  - [{ex['title']}]({ex['url']}) — {ex['views']:,} views "
                     f"({ex['score']}×)")
        L.append("")
    return "\n".join(L)
