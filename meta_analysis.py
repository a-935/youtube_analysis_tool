"""
meta_analysis.py — cross-run analysis over the archive (Expansion Plan §2b)
===========================================================================
The single highest-value addition: replication. A signal that points the same
way in 9/10 runs is real; one that flips every run is noise. That is the validity
test the user was doing by hand — here it's automatic.

Everything in this module is PURE: it takes a list of stored run dicts (from
storage.list_runs) and computes stats. No DB, no engine, no network — so it's
trivially unit-testable with synthetic runs.

Expected shape of each run dict (Tool 1 fills these in when it saves):
  {
    "ts": iso, "topic": str, "region": str,
    "signals": { signal_key: {"verdict": "winners higher" | "winners lower" |
                              "no clear difference" | "diagnostic", "top":?, "bottom":?} },
    "metrics": {"median_velocity_short":?, "median_velocity_long":?,
                "effective_n_short":?, "effective_n_long":?,
                "freshness_days":?, "n_videos":?, "n_shorts":?},
    "top_outliers": [{"channel":?, "title":?, "score":?}, ...],
    "quota_spent":?, "claude_cost":?,
  }
Missing fields are tolerated everywhere.
"""

from collections import Counter, defaultdict

# Map a tool's plain-English verdict to a direction token.
_DIRECTION = {
    "winners higher": "higher",
    "winners lower": "lower",
    "no clear difference": "none",
}


def _direction(verdict):
    if not verdict:
        return None
    v = str(verdict).strip().lower()
    if v == "diagnostic":
        return None          # reach artifacts aren't directional signals
    return _DIRECTION.get(v, None)


def replication_scoreboard(runs):
    """For each signal, how consistently does it point the same way across runs?

    Returns a list (sorted strongest-first) of:
      {signal, runs_seen, higher, lower, none, dominant, agreement, classification}
    where agreement is the share of *directional* runs that agree with the dominant
    direction, and classification is ROBUST / MIXED / NOISE / THIN.
    """
    tally = defaultdict(lambda: Counter())
    for run in runs:
        for key, sig in (run.get("signals") or {}).items():
            d = _direction(sig.get("verdict") if isinstance(sig, dict) else sig)
            if d is None:
                tally[key]["none"] += 1 if (isinstance(sig, dict) and
                                            str(sig.get("verdict", "")).lower()
                                            == "no clear difference") else 0
                # diagnostics / unknown: don't count as a directional observation
                continue
            tally[key][d] += 1

    out = []
    for key, c in tally.items():
        higher, lower, none = c["higher"], c["lower"], c["none"]
        runs_seen = higher + lower + none
        directional = higher + lower
        if higher >= lower:
            dominant, dom_n = ("winners higher", higher)
        else:
            dominant, dom_n = ("winners lower", lower)
        agreement = (dom_n / directional) if directional else 0.0

        if runs_seen < 3:
            cls = "THIN"
        elif directional == 0:
            cls = "NOISE"           # always "no clear difference"
        elif agreement >= 0.8 and directional >= 3:
            cls = "ROBUST"
        elif agreement >= 0.6:
            cls = "MIXED"
        else:
            cls = "NOISE"

        out.append({
            "signal": key, "runs_seen": runs_seen,
            "higher": higher, "lower": lower, "none": none,
            "dominant": dominant if directional else "no clear difference",
            "agreement": round(agreement, 2),
            "classification": cls,
        })

    rank = {"ROBUST": 0, "MIXED": 1, "NOISE": 2, "THIN": 3}
    out.sort(key=lambda r: (rank[r["classification"]], -r["agreement"], -r["runs_seen"]))
    return out


def niche_over_time(runs, topic=None):
    """Time series for one topic: how the niche's headline metrics move run to run,
    plus how many *new* outlier channels appear vs the previous run."""
    sel = [r for r in runs if (topic is None or r.get("topic") == topic)]
    sel.sort(key=lambda r: r.get("ts", ""))
    series, prev_channels = [], set()
    for r in sel:
        m = r.get("metrics") or {}
        chans = {o.get("channel") for o in (r.get("top_outliers") or []) if o.get("channel")}
        new_ch = sorted(chans - prev_channels) if prev_channels else []
        series.append({
            "ts": r.get("ts"),
            "topic": r.get("topic"),
            "median_velocity_short": m.get("median_velocity_short"),
            "median_velocity_long": m.get("median_velocity_long"),
            "effective_n_short": m.get("effective_n_short"),
            "effective_n_long": m.get("effective_n_long"),
            "freshness_days": m.get("freshness_days"),
            "n_videos": m.get("n_videos"),
            "new_channels": new_ch,
        })
        prev_channels = chans
    return series


def cross_niche_universals(runs):
    """Which signals win EVERYWHERE vs only in one niche.

    For each signal, look at its dominant direction within each topic, then see how
    many distinct topics agree. universal = same direction in >=2 topics and no
    contradicting topic; niche_specific = topics disagree.
    """
    by_topic_signal = defaultdict(lambda: defaultdict(Counter))
    for run in runs:
        topic = run.get("topic") or "(unknown)"
        for key, sig in (run.get("signals") or {}).items():
            d = _direction(sig.get("verdict") if isinstance(sig, dict) else sig)
            if d:
                by_topic_signal[key][topic][d] += 1

    out = []
    for key, topics in by_topic_signal.items():
        dirs = {}
        for topic, c in topics.items():
            dirs[topic] = "higher" if c["higher"] >= c["lower"] else "lower"
        distinct = set(dirs.values())
        n_topics = len(dirs)
        if n_topics >= 2 and len(distinct) == 1:
            verdict = f"universal ({next(iter(distinct))} everywhere)"
        elif len(distinct) > 1:
            verdict = "niche-specific (direction differs by topic)"
        else:
            verdict = "single-niche only"
        out.append({"signal": key, "topics": n_topics,
                    "by_topic": dirs, "verdict": verdict})
    out.sort(key=lambda r: -r["topics"])
    return out


def channel_watch(runs, min_appearances=2):
    """Channels that keep showing up as outliers across runs — rising stars to watch."""
    appear = Counter()
    topics = defaultdict(set)
    for run in runs:
        topic = run.get("topic")
        seen = set()
        for o in (run.get("top_outliers") or []):
            ch = o.get("channel")
            if ch and ch not in seen:
                seen.add(ch)
                appear[ch] += 1
                if topic:
                    topics[ch].add(topic)
    rows = [{"channel": ch, "appearances": n,
             "niches": sorted(topics[ch])}
            for ch, n in appear.most_common() if n >= min_appearances]
    return rows


def cost_summary(runs):
    """Spend over time + cost per run, for the quota/cost dashboard."""
    total_quota = sum((r.get("quota_spent") or 0) for r in runs)
    total_claude = sum((r.get("claude_cost") or 0) for r in runs)
    return {
        "runs": len(runs),
        "total_quota": total_quota,
        "total_claude_usd": round(total_claude, 4),
        "avg_quota_per_run": round(total_quota / len(runs), 1) if runs else 0,
        "avg_claude_per_run": round(total_claude / len(runs), 4) if runs else 0,
    }


def diff_runs(run_a, run_b):
    """'What changed' between two runs of the same niche (a = older, b = newer).
    Reports signals that flipped direction and headline-metric deltas."""
    sa, sb = run_a.get("signals") or {}, run_b.get("signals") or {}
    flips = []
    for key in sorted(set(sa) | set(sb)):
        va = sa.get(key, {}).get("verdict") if isinstance(sa.get(key), dict) else sa.get(key)
        vb = sb.get(key, {}).get("verdict") if isinstance(sb.get(key), dict) else sb.get(key)
        if va != vb:
            flips.append({"signal": key, "was": va or "—", "now": vb or "—"})

    ma, mb = run_a.get("metrics") or {}, run_b.get("metrics") or {}
    deltas = {}
    for k in ("median_velocity_short", "median_velocity_long",
              "effective_n_short", "effective_n_long", "freshness_days", "n_videos"):
        if ma.get(k) is not None and mb.get(k) is not None:
            deltas[k] = round(mb[k] - ma[k], 2)
    return {"flips": flips, "deltas": deltas,
            "from_ts": run_a.get("ts"), "to_ts": run_b.get("ts")}


def regime_change_flags(runs):
    """Auto-flag signals that were robust historically but have started flipping in
    the most recent runs (Plan §2 'auto-flag regime change')."""
    if len(runs) < 6:
        return []
    ordered = sorted(runs, key=lambda r: r.get("ts", ""))
    older, recent = ordered[:-3], ordered[-3:]
    old_board = {r["signal"]: r for r in replication_scoreboard(older)}
    new_board = {r["signal"]: r for r in replication_scoreboard(recent)}
    flags = []
    for sig, old in old_board.items():
        new = new_board.get(sig)
        if old["classification"] == "ROBUST" and new and new["classification"] in ("NOISE", "MIXED"):
            flags.append({"signal": sig,
                          "was": old["dominant"], "now": new["dominant"],
                          "note": "was robust, now unstable in recent runs"})
    return flags


def build_meta_prompt(runs, scoreboard):
    """Prompt for the holistic, cross-run AI read. Feeds the *replication* stats so the
    AI reasons about what holds up, not a single run. Numbers are precomputed here; the
    AI judges/explains, it does not invent figures (Plan §6.4)."""
    topics = Counter(r.get("topic") for r in runs)
    lines = [f"Archive of {len(runs)} saved niche-research runs across "
             f"{len(topics)} topics: " +
             ", ".join(f"{t}×{n}" for t, n in topics.most_common()) + "."]
    lines.append("\nSignal replication scoreboard (the validity test — share of "
                 "directional runs that agreed on the dominant direction):")
    for s in scoreboard:
        lines.append(f"- {s['signal']}: {s['classification']} · {s['dominant']} · "
                     f"agreement {s['agreement']:.0%} over {s['runs_seen']} runs "
                     f"(↑{s['higher']} ↓{s['lower']} ~{s['none']})")
    body = "\n".join(lines)
    return f"""You are a blunt research analyst. Below is a replication scoreboard built \
from many saved runs of an automated YouTube niche-research tool. Replication across runs \
is the validity test: a signal that points the same way in most runs is real; one that \
flips is noise.

{body}

Do NOT invent numbers — reason only from the scoreboard above. Respond in markdown with:

## What's robust (trust these)
The signals that replicate. One line each on what to actually DO about them.

## What's noise (ignore these)
Signals that flip across runs — say plainly they're not actionable yet.

## Thin / needs more runs
Signals seen in too few runs to judge, and roughly how many more runs would settle them.

## Bottom line
2-3 sentences: the durable strategy this archive supports."""
