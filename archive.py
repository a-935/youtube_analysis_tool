"""
archive.py — turn a Tool-1 run into the structured record the archive stores
============================================================================
The meta-analysis replicates signals across runs, so each run must persist its
per-signal *verdicts* and a few headline metrics in a stable shape. This module
extracts that from the live tool outputs. Pure (engine only for medians/clustering).
"""

import statistics

import yt_dashboard as engine

# pattern/title/engagement tools whose verdicts we replicate across runs
_SIGNAL_KEYS = ["title_len", "emoji", "question", "numbers", "caps",
                "duration", "like_rate", "comment_rate"]


def _verdict_from_summary(summary):
    s = (summary or "").lower()
    if s.startswith("diagnostic"):
        return "diagnostic"
    for phrase in ("no clear difference", "winners higher", "winners lower"):
        if phrase in s:
            return phrase
    return None


def extract_signals(outputs):
    """outputs = list of (key, out). Returns {key: {verdict, top, bottom}} for the
    replicable signals present."""
    by_key = dict(outputs)
    signals = {}
    for key in _SIGNAL_KEYS:
        out = by_key.get(key)
        if not out:
            continue
        verdict = _verdict_from_summary(out.get("summary"))
        shorts = (out.get("result") or {}).get("shorts") or {}
        signals[key] = {"verdict": verdict,
                        "top": shorts.get("top"), "bottom": shorts.get("bottom")}
    return signals


def _median_velocity(videos):
    vals = [v.get("views_per_day", 0) for v in videos if v.get("views_per_day", 0) > 0]
    return round(statistics.median(vals)) if vals else 0


def compute_metrics(ds):
    vids = ds["videos"]
    shorts = [v for v in vids if v.get("is_short")]
    longf = [v for v in vids if not v.get("is_short")]
    ages = [v.get("age_days", 0) for v in vids if v.get("age_days")]
    return {
        "n_videos": len(vids),
        "n_shorts": len(shorts),
        "median_velocity_short": _median_velocity(shorts),
        "median_velocity_long": _median_velocity(longf),
        "effective_n_short": engine.channel_clustering(shorts)["effective_n"],
        "effective_n_long": engine.channel_clustering(longf)["effective_n"],
        "freshness_days": int(statistics.median(ages)) if ages else 0,
    }


def extract_top_outliers(outputs, ds, k=8):
    """Prefer the outliers tool's fastest cards; fall back to raw velocity top."""
    by_key = dict(outputs)
    out = by_key.get("outliers")
    rows = []
    if out:
        res = out.get("result") or {}
        for fmt in ("shorts", "long"):
            for card in (res.get(fmt) or {}).get("fastest", [])[:k]:
                rows.append({"channel": card.get("channel"),
                             "title": card.get("title"),
                             "score": card.get("vs_baseline")})
    if not rows:
        top = sorted([v for v in ds["videos"] if v.get("views_per_day", 0) > 0],
                     key=lambda v: -v["views_per_day"])[:k]
        rows = [{"channel": v.get("channel"), "title": v.get("title"),
                 "score": None} for v in top]
    return rows[:k]


def build_run_record(topic, region, controls, ds, outputs,
                     ai_brief="", quota_spent=0, claude_cost=0.0):
    """Assemble the dict handed to storage.save_run()."""
    return {
        "topic": topic,
        "region": region,
        "after": controls.get("after"),
        "before": controls.get("before"),
        "age_days": controls.get("age_days"),
        "tier": controls.get("tier"),
        "per_format": controls.get("per_format"),
        "n_videos": len(ds["videos"]),
        "n_shorts": sum(v.get("is_short", 0) for v in ds["videos"]),
        "quota_spent": quota_spent,
        "claude_cost": round(claude_cost or 0, 4),
        "signals": extract_signals(outputs),
        "metrics": compute_metrics(ds),
        "top_outliers": extract_top_outliers(outputs, ds),
        "ai_brief": ai_brief or "",
    }
