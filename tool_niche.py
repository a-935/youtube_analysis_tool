"""
Tool 1 — Niche / Genre Analysis  (was the whole app in v3)
=========================================================
The original single-tool niche-research UI, lifted verbatim into a render()
function so the app shell (app.py) can mount it in its own tab. Nothing about the
analysis itself changed — same sidebar controls, same engine calls, same tables.

Phase-1 relocations (app-wide concerns that now live in app.py, the shell):
  - st.set_page_config(...)        -> shell (must be the first Streamlit call, once)
  - quota / claude wallet session   -> shell (shared across all tools)
"""

import os
import html
from datetime import date, timedelta

import streamlit as st
import yt_dashboard as engine
import storage
import archive
import meta_analysis as meta_an
import exports

try:
    import pandas as pd
except Exception:
    pd = None


def fmt_views(n):
    return f"{n:,}" if isinstance(n, int) else "-"


def _title_cell(c):
    # escape pipes/newlines so titles don't break the markdown table
    t = str(c["title"]).replace("|", "\\|").replace("\n", " ").strip()
    return f"[{t}]({c['url']})"


def _chan_cell(c):
    # plain channel name, pipe/newline-escaped for markdown tables
    return str(c.get("channel") or "").replace("|", "\\|").replace("\n", " ").strip()


def _date_cell(c):
    # YYYY-MM-DD release date from the ISO 'published' timestamp
    return str(c.get("published") or "")[:10]


def md_table(cards, cols):
    """Build a markdown table. cols = list of (header, fn(card)->str)."""
    if not cards:
        return ""
    head = "| " + " | ".join(h for h, _ in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    rows = ["| " + " | ".join(fn(c) for _, fn in cols) + " |" for c in cards]
    return "\n".join([head, sep] + rows)


# value-column header per pattern tool
VALUE_LABEL = {
    "title_len": "Chars", "emoji": "Emoji?", "question": "Question?",
    "numbers": "Number/$?", "caps": "ALL-CAPS", "duration": "Seconds",
    "like_rate": "Like %", "comment_rate": "Comment %",
}


def pattern_table(cards, value_header):
    cols = [("Channel", _chan_cell),
            ("Video", _title_cell),
            (value_header, lambda c: str(c.get("value", ""))),
            ("Views", lambda c: fmt_views(c["views"])),
            ("Released", _date_cell)]
    return md_table(cards, cols)


def outlier_table(cards):
    """HTML table whose × multipliers reveal the raw numbers on hover:
    × niche median  -> this video's views/day vs the niche median
    × channel avg   -> channel name + this video vs the channel's typical (median) views
    Rendered with unsafe_allow_html=True."""
    if not cards:
        return ""

    def tip(text, tip_text):
        return f'<span title="{html.escape(tip_text, quote=True)}">{text}</span>'

    rows = []
    for c in cards:
        title = html.escape(str(c.get("title", "")))
        url = html.escape(c.get("url", ""), quote=True)

        vsb, base, vpd = c.get("vs_baseline"), c.get("baseline"), c.get("views_per_day")
        if vsb is not None and base:
            niche = tip(f"{vsb}×",
                        f"{(vpd or 0):,.0f} views/day  ÷  similar-age median {base:,} views/day  =  {vsb}×")
        else:
            niche = "—"

        vca, avg, chan = c.get("vs_channel_avg"), c.get("channel_avg_views"), c.get("channel")
        if vca is not None and avg:
            chan_label = html.escape(str(chan or "this channel"))
            niche_chan = tip(f"{vca}×",
                             f"{chan_label} — this video {c.get('views', 0):,} views  vs  "
                             f"channel typical {avg:,} views (recent uploads)  =  {vca}×")
        else:
            niche_chan = "—"

        rows.append(
            "<tr>"
            f"<td style='padding:4px 8px'>{html.escape(str(c.get('channel') or ''))}</td>"
            f"<td style='padding:4px 8px'><a href='{url}' target='_blank'>{title}</a></td>"
            f"<td style='padding:4px 8px;text-align:right'>{c.get('views', 0):,}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{niche}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{niche_chan}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{str(c.get('published') or '')[:10]}</td>"
            "</tr>"
        )

    header = (
        "<table style='width:100%;border-collapse:collapse;font-size:0.9em'>"
        "<thead><tr style='border-bottom:1px solid #ccc'>"
        "<th style='padding:4px 8px;text-align:left'>Channel</th>"
        "<th style='padding:4px 8px;text-align:left'>Video</th>"
        "<th style='padding:4px 8px;text-align:right'>Views</th>"
        "<th style='padding:4px 8px;text-align:right'>× similar-age median</th>"
        "<th style='padding:4px 8px;text-align:right'>× channel typical</th>"
        "<th style='padding:4px 8px;text-align:right'>Released</th>"
        "</tr></thead><tbody>"
    )
    return header + "".join(rows) + "</tbody></table>"


def breakout_table(vids):
    """HTML table whose '× subs' value reveals the raw math on hover:
    channel name, the video's views, and the channel's subscriber count.
    Rendered with unsafe_allow_html=True."""
    if not vids:
        return ""

    def tip(text, tip_text):
        return f'<span title="{html.escape(tip_text, quote=True)}">{text}</span>'

    rows = []
    for v in vids:
        title = html.escape(str(v.get("title", "")))
        url = html.escape(v.get("url", f"https://www.youtube.com/watch?v={v.get('id', '')}"),
                          quote=True)
        vps = v.get("views_per_sub")
        subs = v.get("subs")
        chan = html.escape(str(v.get("channel", "this channel")))
        if vps is not None and subs:
            subs_cell = tip(f"{vps}×",
                            f"{chan} — {v.get('views', 0):,} views  ÷  {subs:,} subscribers  =  {vps}×")
        else:
            subs_cell = f"{vps}×" if vps is not None else "—"
        rows.append(
            "<tr>"
            f"<td style='padding:4px 8px'>{html.escape(str(v.get('channel') or ''))}</td>"
            f"<td style='padding:4px 8px'><a href='{url}' target='_blank'>{title}</a></td>"
            f"<td style='padding:4px 8px;text-align:right'>{subs_cell}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{v.get('views', 0):,}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{str(v.get('published') or '')[:10]}</td>"
            "</tr>"
        )
    header = (
        "<table style='width:100%;border-collapse:collapse;font-size:0.9em'>"
        "<thead><tr style='border-bottom:1px solid #ccc'>"
        "<th style='padding:4px 8px;text-align:left'>Channel</th>"
        "<th style='padding:4px 8px;text-align:left'>Video</th>"
        "<th style='padding:4px 8px;text-align:right'>× subs</th>"
        "<th style='padding:4px 8px;text-align:right'>Views</th>"
        "<th style='padding:4px 8px;text-align:right'>Released</th>"
        "</tr></thead><tbody>"
    )
    return header + "".join(rows) + "</tbody></table>"


def render_pattern(result, value_header):
    for fmt in ("shorts", "long"):
        block = result.get(fmt, {})
        top, bot = block.get("top_items", []), block.get("bottom_items", [])
        if not top and not bot:
            continue
        st.markdown(f"**{fmt.title()}** — faster videos")
        st.markdown(pattern_table(top[:6], value_header))
        if bot:
            st.markdown(f"**{fmt.title()}** — slower videos")
            st.markdown(pattern_table(bot[:6], value_header))


def render_archive_panel():
    """The Summary Archive + cross-run meta-analysis (Expansion Plan §2b).
    Cross-run replication is the validity test: a signal that points the same way
    across many runs is real; one that flips is noise."""
    try:
        runs = storage.list_runs(limit=500)
    except Exception as ex:
        st.caption(f"Archive unavailable: {ex}")
        return

    with st.expander(f"📚 Archive & cross-run meta-analysis ({len(runs)} saved runs)"):
        if not runs:
            st.info("No saved runs yet. Run an analysis with 'Save run to archive' "
                    "ticked, a few times across days/niches, then come back — "
                    "replication across runs is the cleanest validity test.")
            return

        topics = storage.distinct_topics()
        st.caption("Saved runs by topic: " +
                   ", ".join(f"{t}×{c}" for t, c in topics))

        # ---- Signal replication scoreboard (the headline) ----
        board = meta_an.replication_scoreboard(runs)
        st.markdown("**Signal replication scoreboard** — does each signal point the "
                    "same way across runs? ROBUST = holds up; NOISE = flips; "
                    "THIN = too few runs yet.")
        if board:
            rows = [{"Signal": s["signal"], "Verdict": s["classification"],
                     "Direction": s["dominant"], "Agreement": f"{s['agreement']:.0%}",
                     "Runs": s["runs_seen"], "↑": s["higher"], "↓": s["lower"],
                     "~": s["none"]} for s in board]
            if pd is not None:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            else:
                st.markdown(exports.scoreboard_to_markdown(board))
        else:
            st.caption("No directional signals stored yet.")

        # ---- Regime-change flags ----
        flags = meta_an.regime_change_flags(runs)
        if flags:
            st.warning("⚠ Regime change — these were robust but are now flipping in "
                       "recent runs: " +
                       "; ".join(f"{f['signal']} ({f['was']} → {f['now']})" for f in flags))

        # ---- Niche-over-time ----
        topic_list = [t for t, _ in topics]
        pick = st.selectbox("Track one niche over time", topic_list, key="meta_topic")
        series = meta_an.niche_over_time(runs, topic=pick)
        if pd is not None and len(series) >= 2:
            df = pd.DataFrame([{
                "run": s["ts"][:10],
                "median velocity (Shorts)": s["median_velocity_short"],
                "median velocity (long)": s["median_velocity_long"],
                "effective-n (Shorts)": s["effective_n_short"],
            } for s in series]).set_index("run")
            st.line_chart(df)
            newest = series[-1]
            if newest["new_channels"]:
                st.caption("New outlier channels in the latest run: " +
                           ", ".join(newest["new_channels"][:8]))
        else:
            st.caption("Need ≥2 runs of this niche for a trend line.")

        # ---- Channel watch + cost ----
        watch = meta_an.channel_watch(runs)
        if watch:
            st.markdown("**Channel watch** — recurring outlier channels (rising stars):")
            st.markdown("\n".join(
                f"- {w['channel']} — {w['appearances']} runs "
                f"({', '.join(w['niches'][:4])})" for w in watch[:10]))

        cost = meta_an.cost_summary(runs)
        st.caption(f"💰 Across {cost['runs']} runs: {cost['total_quota']:,} quota units, "
                   f"${cost['total_claude_usd']:.4f} Claude. "
                   f"Avg/run: {cost['avg_quota_per_run']:.0f} units, "
                   f"${cost['avg_claude_per_run']:.4f}.")

        # ---- Cross-niche universals ----
        uni = meta_an.cross_niche_universals(runs)
        multi = [u for u in uni if u["topics"] >= 2]
        if multi:
            st.markdown("**Cross-niche** — what holds everywhere vs one game:")
            st.markdown("\n".join(f"- {u['signal']}: {u['verdict']}" for u in multi[:8]))

        # ---- Saved-runs browser (view / note / export / delete) ----
        st.markdown("---")
        st.markdown("**Saved runs**")
        labels = {f"#{r['id']} · {r.get('topic','?')} · {str(r.get('ts',''))[:16]} · "
                  f"{r.get('n_videos','?')} vids": r for r in runs}
        pick_run = st.selectbox("Open a saved run", list(labels.keys()), key="run_browse")
        chosen = labels.get(pick_run)
        if chosen:
            note = st.text_input("Note", value=chosen.get("note", ""), key="run_note")
            b1, b2, b3 = st.columns(3)
            if b1.button("Save note", use_container_width=True):
                storage.set_run_note(chosen["id"], note)
                st.success("Note saved.")
            b2.download_button("⬇ This run (Markdown)",
                               exports.run_to_markdown(chosen),
                               file_name=f"run_{chosen['id']}.md",
                               use_container_width=True)
            if b3.button("🗑 Delete run", use_container_width=True):
                storage.delete_run(chosen["id"])
                st.warning(f"Deleted run #{chosen['id']}. Reopen the panel to refresh.")
            if chosen.get("ai_brief"):
                with st.expander("AI brief from that run"):
                    st.markdown(chosen["ai_brief"])

        # ---- Compare two runs of the same niche (diff_runs) ----
        same_topic = [r for r in runs if r.get("topic") == (chosen or {}).get("topic")]
        if len(same_topic) >= 2:
            st.markdown(f"**Compare two '{chosen['topic']}' runs** — what changed:")
            opts = {f"#{r['id']} · {str(r.get('ts',''))[:16]}": r for r in same_topic}
            ok_ = list(opts.keys())
            cc1, cc2 = st.columns(2)
            older = cc1.selectbox("Older", ok_, index=min(1, len(ok_) - 1), key="diff_old")
            newer = cc2.selectbox("Newer", ok_, index=0, key="diff_new")
            if st.button("Compare runs"):
                d = meta_an.diff_runs(opts[older], opts[newer])
                if d["flips"]:
                    st.markdown("Signals that flipped:")
                    for f in d["flips"]:
                        st.markdown(f"- **{f['signal']}**: {f['was']} → {f['now']}")
                else:
                    st.caption("No signal verdicts changed.")
                if d["deltas"]:
                    st.markdown("Metric deltas (newer − older): " +
                                ", ".join(f"{k} {v:+}" for k, v in d["deltas"].items()))

        # ---- Exports + AI meta-brief ----
        c1, c2 = st.columns(2)
        c1.download_button("⬇ Scoreboard (Markdown)",
                           exports.scoreboard_to_markdown(board),
                           file_name="replication_scoreboard.md",
                           use_container_width=True, disabled=not board)
        if c2.button("🧠 AI meta-brief (Claude)", use_container_width=True,
                     help="Feeds the replication scoreboard to Claude for a holistic, "
                          "cross-run read. Costs a little Claude credit."):
            with st.spinner("Asking Claude for the cross-run read..."):
                try:
                    prompt = meta_an.build_meta_prompt(runs, board)
                    res = engine._call_claude(prompt, max_tokens=1200)
                    st.session_state.claude_used += res.get("cost_usd", 0) or 0
                    st.session_state.meta_brief = res["text"]
                except Exception as ex:
                    st.session_state.meta_brief = f"Claude call failed: {ex}"
        if st.session_state.get("meta_brief"):
            st.markdown(st.session_state.meta_brief)


def render():
    if not os.environ.get("YT_KEY"):
        st.sidebar.error("No YouTube key. Add YT_KEY=... to your .env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.sidebar.warning("No Claude key yet. Add ANTHROPIC_API_KEY=... to .env for AI summary.")

    topic = st.sidebar.text_input("Topic / genre", value="rocket league")

    region_label = st.sidebar.selectbox(
        "Region / language", list(engine.REGIONS.keys()),
        help="Bias the search toward one country/language. 'All regions' (default) searches "
             "worldwide — handy, but it mixes Spanish/French/Arabic/etc. into the data. Pick "
             "your language to get a cleaner read for your audience.")

    _today = date.today()

    # From date and Age are two views of ONE window. Editing either updates the other,
    # so they can never point at different start dates. They sync only when To = today
    # (the normal case); a custom past To date turns the age readout off rather than
    # showing a number that lies (age is always measured from today).
    if "from_date" not in st.session_state:
        st.session_state.from_date = _today - timedelta(days=30)
    if "age_days" not in st.session_state:
        st.session_state.age_days = 30
    if "to_date" not in st.session_state:
        st.session_state.to_date = None


    def _sync_age_from_date():
        # user edited From (or To): recompute age from today, if To is today/empty
        to_d = st.session_state.get("to_date")
        if to_d in (None, _today):
            st.session_state.age_days = max((_today - st.session_state.from_date).days, 0)


    def _sync_date_from_age():
        # user edited Age: move From to (today - age). Programmatic set does NOT
        # re-fire the date callback, so there's no sync loop.
        st.session_state.from_date = _today - timedelta(days=int(st.session_state.age_days))


    c1, c2 = st.sidebar.columns(2)
    after = c1.date_input("From", key="from_date", on_change=_sync_age_from_date)
    before = c2.date_input("To (optional)", value=None, key="to_date",
                           on_change=_sync_age_from_date)

    to_is_today = before in (None, _today)
    age = st.sidebar.number_input(
        "Video age (days back from today)", min_value=0, step=1,
        key="age_days", on_change=_sync_date_from_age, disabled=not to_is_today,
        help="Same window as the From date, just counted in days. Change either one and "
             "the other follows. Disabled when you pick a custom 'To' date, since age is "
             "always measured from today.")

    # live readout so there's never any guessing about the actual window
    _end = "today" if to_is_today else before.isoformat()
    if to_is_today:
        st.sidebar.caption(f"🔎 Searching {after.isoformat()} → {_end}  ·  {age} days")
    else:
        _span = (before - after).days
        st.sidebar.caption(f"🔎 Searching {after.isoformat()} → {_end}  ·  {_span}-day window "
                           f"(age off — custom end date)")

    tier = st.sidebar.selectbox(
        "Channel size", ["all", "small", "medium", "large"],
        help="Subscriber-based tiers: small <100k . medium 100k-1M . large >1M. "
             "Note: these are FIXED thresholds, not relative to the niche yet.")

    per_format = st.sidebar.slider(
        "Videos per format", min_value=50, max_value=250, value=50, step=50,
        help="How many Shorts AND how many long-form to pull. More = better stats but "
             "more quota. Each 50 per format = 100 units.")

    balanced = st.sidebar.checkbox("Balanced fetch (Shorts + long-form)", value=True)
    drop_official = st.sidebar.checkbox(
        "Exclude official/brand channel", value=True,
        help="Drops the game's own channel (e.g. 'Call of Duty') so trailers don't skew results.")

    save_to_archive = st.sidebar.checkbox(
        "Save run to archive", value=True,
        help="Persists this run (signals, metrics, AI brief) so cross-run "
             "meta-analysis can tell real signals from noise over time.")

    # live cost estimate
    pages = max(1, (per_format + 49) // 50)
    est_units = 100 * pages * (2 if balanced else 1) + pages + 1
    st.sidebar.caption(f"Est. fetch cost: ~{est_units} quota units "
                       f"(~{round(est_units / (per_format * (2 if balanced else 1)), 1)} units/video). "
                       f"Daily free quota is 10,000.")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Tools to run")

    # Select all / Clear all. (Select all skips the paid AI tool so you don't
    # spend Claude credit by accident — tick that one yourself.)
    sa, ca = st.sidebar.columns(2)
    if sa.button("Select all", use_container_width=True):
        for k in engine.TOOLS:
            st.session_state[f"chk_{k}"] = (engine.TOOLS[k]["cat"] != "AI")
    if ca.button("Clear all", use_container_width=True):
        for k in engine.TOOLS:
            st.session_state[f"chk_{k}"] = False
    st.sidebar.caption("'Select all' skips the paid AI tools — tick those yourself.")

    TOOL_HELP = {
        "outliers": "Ranks videos by views-per-day vs the median of videos of SIMILAR AGE (age-adjusted, since raw views/day favours brand-new videos). Shows fastest/slowest per format.",
        "title_len": "Compares title length (characters) of faster vs slower videos.",
        "emoji": "Whether faster videos use emoji more than slower ones.",
        "question": "Whether faster videos use question-style titles.",
        "numbers": "Whether faster videos use numbers or $ in the title.",
        "caps": "ALL-CAPS word count in faster vs slower titles.",
        "hook": "Most common opening words among the fastest videos.",
        "duration": "Video length (seconds) of faster vs slower videos.",
        "timing": "Which weekday the fastest videos tend to post on.",
        "like_rate": "Likes-per-view of faster vs slower videos. Reach artifact — slower/smaller videos draw MORE likes per view, so it's diagnostic, not a target to optimize.",
        "comment_rate": "Comments-per-view of faster vs slower videos. Reach artifact like like-rate — slower videos draw more comments per view. Diagnostic, not a target.",
        "breakouts": "Videos that beat their channel's subscriber count the most (views/subs). Auto '- Topic' channels are filtered out; tiny-sub denominators get a warning.",
        "chan_outlier": "Each video vs its OWN channel average (needs channel-stats fetch).",
        "cadence": "Upload frequency vs reach per channel (needs channel-stats fetch). Reach is within this search, so a channel that floods results will top it — labeled accordingly.",
        "channels": "Each channel's average views in this niche + how many of its videos beat that average.",
        "ai_summary": "Sends all the signals to Claude for a strategy brief, reliability check, and dev notes. Costs Claude credit.",
        "ai_ideas": "Asks Claude to pitch 5 ready-to-film video ideas built from what's winning in THIS niche. Costs Claude credit.",
        "all_videos": "A full sortable table of every video in the search — thumbnail, channel, views, likes, comments, release date, velocity, subs, everything. Download as CSV.",
        "freshness": "Trend-spike check: how OLD the niche's videos are. Mostly days/weeks old = exploding now (ride it fast); spread out = durable lane. Run with Max-age at 0 for an honest read.",
    }

    selected = []
    cats = {}
    for key, spec in engine.TOOLS.items():
        cats.setdefault(spec["cat"], []).append((key, spec))
    for cat, items in cats.items():
        st.sidebar.markdown(f"**{cat}**")
        for key, spec in items:
            label = spec["label"] + (" (needs ch-stats)" if spec["needs_channel_stats"] else "")
            if st.sidebar.checkbox(label, key=f"chk_{key}", help=TOOL_HELP.get(key)):
                selected.append(key)

    st.sidebar.markdown("---")
    run = st.sidebar.button("Run analysis", type="primary", use_container_width=True)


    # ---------------- RUN ----------------
    if run:
        if not selected:
            st.warning("Tick at least one tool first.")
            st.stop()
        with st.spinner(f"Fetching '{topic}'..."):
            try:
                ds = engine.fetch_dataset(
                    topic,
                    after=after.isoformat() if after else None,
                    before=before.isoformat() if before else None,
                    balanced=balanced,
                    videos_per_format=per_format,
                    region_label=region_label,
                )
            except Exception as ex:
                st.error(f"Fetch failed: {ex}")
                st.stop()

        needs_cs = any(engine.TOOLS[k]["needs_channel_stats"] for k in selected)
        cs_cost = 0
        if needs_cs:
            with st.spinner("Fetching channel stats..."):
                cs_cost = engine.fetch_channel_stats(ds) or 0

        vids = ds["videos"]
        if drop_official:
            vids = engine.exclude_official(vids, topic)
        if tier != "all":
            vids = engine.by_tier(vids, tier)
        ds = {**ds, "videos": vids}

        charge_key = f"{topic}|{region_label}|{after}|{before}|{balanced}|{per_format}|{needs_cs}"
        spent = (ds["cost"] + cs_cost) if not ds["from_cache"] else 0
        if spent and charge_key not in st.session_state.charged_keys:
            st.session_state.quota_used += spent
            st.session_state.charged_keys.add(charge_key)

        outputs = []
        for k in selected:
            if engine.TOOLS[k]["cat"] == "AI":
                with st.spinner("Asking Claude..."):
                    out = engine.TOOLS[k]["func"](ds)
                st.session_state.claude_used += out.get("claude_cost_usd", 0) or 0
            else:
                out = engine.TOOLS[k]["func"](ds)
            outputs.append((k, out))

        # Render order: everything else first, charts next, then the AI tools last,
        # so you read the data/visuals before Claude's interpretation of them.
        rank = {"charts": 1, "ai_summary": 2, "ai_ideas": 3}
        outputs.sort(key=lambda ko: rank.get(ko[0], 0))

        st.session_state.results = {
            "topic": topic,
            "ds_meta": {"n": len(ds["videos"]),
                        "n_short": sum(v["is_short"] for v in ds["videos"]),
                        "from_cache": ds["from_cache"], "spent": spent},
            "outputs": outputs,
        }

        # ---- Archive the run (Expansion Plan §2a) ----
        # Persist signals/metrics/AI brief so cross-run replication can run later.
        st.session_state.last_saved_run = None
        if save_to_archive:
            try:
                ai_brief = next((o.get("result", {}).get("text", "")
                                 for k, o in outputs if k == "ai_summary"), "")
                claude_cost = sum((o.get("claude_cost_usd", 0) or 0) for _, o in outputs)
                rec = archive.build_run_record(
                    topic, region_label,
                    {"after": after.isoformat() if after else None,
                     "before": before.isoformat() if before else None,
                     "age_days": int(age) if to_is_today else None,
                     "tier": tier, "per_format": per_format},
                    ds, outputs, ai_brief=ai_brief,
                    quota_spent=spent, claude_cost=claude_cost)
                st.session_state.last_saved_run = storage.save_run(rec)
            except Exception as ex:
                st.session_state.archive_error = str(ex)


    # ---------------- HEADER + WALLET ----------------
    st.title("YouTube Niche Research")

    with st.expander("📖 How to read this (plain-language guide)"):
        st.markdown("""
    **Velocity (views/day)** — how *fast* a video gathers views, not its total.
    A video with 1,000 views in 2 days (500/day) is hotter right now than one with
    5,000 views over 100 days (50/day). We rank by this so today's trends rise to the top.

    **Similar-age median** — the *typical* video of about the same age as the one you're
    looking at. Velocity (views/day) naturally favours brand-new videos — a 1-day-old video
    is caught at its peak, while an old video's views/day is averaged across a long quiet
    tail. So instead of comparing every video to one niche-wide median, we compare each one
    to videos of *similar age*, which is a fair fight. "2× similar-age median" means twice as
    fast as the typical video of its age here.

    **× channel typical** — how much a video beat *its own channel's* normal (the channel's
    median views across its recent uploads). A video can be slow for the whole niche but
    still 6× its own channel — that means the idea worked
    *for them*, even if the niche is bigger.

    **Shorts vs long-form** — always analysed separately. Shorts gather views much faster,
    so mixing them would make Shorts always "win" unfairly.

    **Faster vs slower videos** — for each pattern (emoji, length, etc.) we compare the
    top third of videos against the bottom third, to see what the winners do differently.

    **"No clear difference"** — the top and bottom groups are basically the same on that
    trait, so it's *not* what separates hits from flops here. Useful to know what *doesn't*
    matter.

    **Small-channel breakout (× subs)** — views divided by subscribers. 100× subs means a
    video got 100 times the channel's subscriber count in views — a sign the *idea* carried
    it, not the existing audience.

    ⚠️ **Sample size matters.** With few videos, small differences are just luck. Trust
    patterns more when each group has 30+ videos, and treat single-video findings as hints,
    not facts.
    """)

    m1, m2 = st.columns(2)
    m1.metric("Quota used (this session)", f"{st.session_state.quota_used:,} units")
    m2.metric("Claude credit used (this session)", f"${st.session_state.claude_used:.4f}")

    if st.session_state.get("last_saved_run"):
        st.caption(f"💾 Saved this run to the archive (#{st.session_state.last_saved_run}).")
    render_archive_panel()

    R = st.session_state.results
    if not R:
        st.info("Pick a topic and tools in the sidebar, then hit Run analysis.")
        st.stop()

    meta = R["ds_meta"]
    n, ns = meta["n"], meta["n_short"]
    src = "cached (free)" if meta["from_cache"] else f"{meta['spent']} units spent"
    st.success(f"**{R['topic']}** - {n} videos ({ns} Shorts, {n - ns} long-form) . {src}")

    if n < 20:
        st.warning(f"Only {n} videos - small sample, treat patterns as rough hints. "
                   f"Raise 'Videos per format', widen the From date, or set Channel size to 'all'.")

    start_expanded = st.checkbox(
        "Expand all tools", value=False,
        help="Off = each tool starts collapsed (less scrolling); click a tool's header to "
             "open it. The one-line summary shows in the header either way.")

    for key, out in R["outputs"]:
        warn = engine.data_warning(key, out)
        flag = "⚠ " if warn else ""
        header = f"{flag}{out['name']} — {out['summary']}"
        with st.expander(header, expanded=start_expanded):
            if warn:
                st.warning(warn)
            result = out["result"]

            if key == "charts":
                if pd is None:
                    st.info("pandas not available for charts.")
                for fmt in ("shorts", "long"):
                    block = result.get(fmt, {})
                    if not block.get("n"):
                        continue
                    st.markdown(f"**{fmt.title()}** ({block['n']} videos)")

                    dh = block["duration_hist"]
                    if dh["labels"]:
                        st.caption("Video length distribution (seconds) — where the lengths cluster")
                        st.bar_chart(pd.DataFrame({"videos": dh["counts"]}, index=dh["labels"]))

                    vh = block["vpd_hist"]
                    if vh["labels"]:
                        st.caption("Views-per-day distribution — where most videos land, and the outlier tail")
                        st.bar_chart(pd.DataFrame({"videos": vh["counts"]}, index=vh["labels"]))

                    if block["scatter"]:
                        st.caption("Views vs like-rate — if dots slope down, low like% just tracks high views")
                        st.scatter_chart(pd.DataFrame(block["scatter"]),
                                         x="views", y="like_rate_pct")

            elif key in ("ai_summary", "ai_ideas"):
                if result.get("text"):
                    st.markdown(result["text"])
                else:
                    st.error(result.get("error", "No response."))

            elif key == "all_videos":
                vids = result.get("videos", [])
                if pd is None:
                    st.info("pandas is needed for the full table.")
                elif not vids:
                    st.info("No videos to show.")
                else:
                    rows = []
                    for v in vids:
                        rows.append({
                            "Thumb": v.get("thumbnail"),
                            "Channel": v.get("channel"),
                            "Title": v.get("title"),
                            "Link": v.get("url", f"https://www.youtube.com/watch?v={v.get('id', '')}"),
                            "Format": "Short" if v.get("is_short") else "Long",
                            "Views": v.get("views"),
                            "Likes": v.get("likes"),
                            "Comments": v.get("comments"),
                            "Like %": round((v.get("like_rate") or 0) * 100, 3),
                            "Comment %": round((v.get("comment_rate") or 0) * 100, 3),
                            "Views/day": v.get("views_per_day"),
                            "Duration (s)": v.get("duration_sec"),
                            "Age (days)": v.get("age_days"),
                            "Released": (v.get("published") or "")[:10],
                            "Weekday": v.get("weekday"),
                            "Subs": v.get("subs"),
                            "Views/sub": v.get("views_per_sub"),
                            "Channel typical": v.get("channel_avg_views"),
                        })
                    df = pd.DataFrame(rows)
                    try:
                        st.dataframe(
                            df, use_container_width=True, hide_index=True,
                            column_config={
                                "Thumb": st.column_config.ImageColumn("Thumb", width="small"),
                                "Link": st.column_config.LinkColumn("Link", display_text="open"),
                                "Views": st.column_config.NumberColumn(format="%d"),
                                "Likes": st.column_config.NumberColumn(format="%d"),
                                "Comments": st.column_config.NumberColumn(format="%d"),
                                "Views/day": st.column_config.NumberColumn(format="%d"),
                                "Subs": st.column_config.NumberColumn(format="%d"),
                                "Channel typical": st.column_config.NumberColumn(format="%d"),
                            },
                        )
                    except Exception:
                        st.dataframe(df, use_container_width=True, hide_index=True)
                    st.caption("Click any column header to sort. Hover the table and use its "
                               "top-right toolbar to search or download everything as CSV.")

            elif key == "outliers":
                for fmt in ("shorts", "long"):
                    b = result.get(fmt, {})
                    bands = b.get("bands", [])
                    st.markdown(f"**{fmt.title()}** — age-adjusted: each video is compared to "
                                f"the typical video of *similar age*, not one niche median "
                                f"(raw views/day unfairly favours brand-new videos). "
                                f"Overall ~{b.get('baseline', 0):,} views/day.")
                    if len(bands) > 1:
                        band_txt = " · ".join(
                            f"{bd['min_age']}–{bd['max_age']}d: {round(bd['median']):,}/day "
                            f"(n={bd['n']})" for bd in bands)
                        st.caption(f"Age bands (the bar each multiplier uses): {band_txt}")
                    if b.get("fastest"):
                        st.markdown("Fastest (2×+ their similar-age median):")
                        st.markdown(outlier_table(b["fastest"][:8]), unsafe_allow_html=True)
                    if b.get("slowest"):
                        st.markdown("Slowest (below 0.5× their similar-age median) — a 'slow' "
                                    "video may still beat its own channel (see × channel typical):")
                        st.markdown(outlier_table(b["slowest"][:8]), unsafe_allow_html=True)

            elif key == "channels":
                for fmt in ("shorts", "long"):
                    rows = result.get(fmt, [])
                    if not rows:
                        continue
                    st.markdown(f"**{fmt.title()}**")
                    vcols = [("Video", _title_cell),
                             ("Views", lambda c: fmt_views(c["views"]))]
                    for r in rows[:12]:
                        if r["single_video"]:
                            head = (f"{r['channel']} — 1 video here: "
                                    f"{fmt_views(r['typical_views'])} views (single data point)")
                            with st.expander(head):
                                st.markdown(md_table(r["all_videos"], vcols))
                        elif r.get("above_count") is None:
                            # no channel-stats fetch -> we can't compare to the all-time
                            # median, so we DON'T show a tautological "X above" count
                            head = (f"{r['channel']} — median {r['typical_views']:,} here over "
                                    f"{r['n']} videos (run channel stats for a consistency read)")
                            with st.expander(head):
                                st.markdown(md_table(r["all_videos"], vcols))
                        else:
                            head = (f"{r['channel']} — median {r['typical_views']:,} here over "
                                    f"{r['n']} videos . {r['above_count']} of {r['n']} beat "
                                    f"their all-time median ({r['alltime_median']:,})")
                            with st.expander(head):
                                st.markdown(md_table(r["above_videos"], vcols))

            elif key == "breakouts":
                for fmt in ("shorts", "long"):
                    vids = result.get(fmt, {}).get("top", [])
                    if vids:
                        st.markdown(f"**{fmt.title()}**")
                        st.markdown(breakout_table(vids[:8]), unsafe_allow_html=True)

            elif key in ("title_len", "emoji", "question", "numbers", "caps",
                         "duration", "like_rate", "comment_rate"):
                render_pattern(result, VALUE_LABEL.get(key, "Value"))

            else:
                links = engine.linkable_titles(result)
                seen, uniq = set(), []
                for t, u, vw in links:
                    if u not in seen:
                        seen.add(u)
                        uniq.append((t, u, vw))
                if uniq:
                    with st.expander(f"See {len(uniq)} related videos"):
                        for t, u, vw in uniq[:15]:
                            st.markdown(f"- [{t}]({u}) - {fmt_views(vw)} views")
