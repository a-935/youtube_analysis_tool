"""
YouTube Niche Research - GUI (Streamlit)  v3
============================================
New in v3:
- AI summary tool (Claude): strategy brief + per-signal read + reliability verdict
  + developer notes. Charged to a separate Claude wallet (cents per run).
- Videos-per-format control with live quota-cost estimate (fewer, bigger searches).
- Claude wallet tracked in session_state alongside quota.

RUN:  streamlit run app.py
"""

import os
import html
from datetime import date


def _load_env():
    path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()

import streamlit as st
import yt_dashboard as engine

try:
    import pandas as pd
except Exception:
    pd = None

st.set_page_config(page_title="Niche Research", layout="wide")

for k, default in [("quota_used", 0), ("claude_used", 0.0),
                   ("charged_keys", set()), ("results", None)]:
    if k not in st.session_state:
        st.session_state[k] = default


def fmt_views(n):
    return f"{n:,}" if isinstance(n, int) else "-"


def _title_cell(c):
    # escape pipes/newlines so titles don't break the markdown table
    t = str(c["title"]).replace("|", "\\|").replace("\n", " ").strip()
    return f"[{t}]({c['url']})"


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
    cols = [("Video", _title_cell),
            (value_header, lambda c: str(c.get("value", ""))),
            ("Views", lambda c: fmt_views(c["views"]))]
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
                        f"{(vpd or 0):,.0f} views/day  ÷  niche median {base:,} views/day  =  {vsb}×")
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
            f"<td style='padding:4px 8px'><a href='{url}' target='_blank'>{title}</a></td>"
            f"<td style='padding:4px 8px;text-align:right'>{c.get('views', 0):,}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{niche}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{niche_chan}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{c.get('age_days', '—')}d</td>"
            "</tr>"
        )

    header = (
        "<table style='width:100%;border-collapse:collapse;font-size:0.9em'>"
        "<thead><tr style='border-bottom:1px solid #ccc'>"
        "<th style='padding:4px 8px;text-align:left'>Video</th>"
        "<th style='padding:4px 8px;text-align:right'>Views</th>"
        "<th style='padding:4px 8px;text-align:right'>× niche median</th>"
        "<th style='padding:4px 8px;text-align:right'>× channel typical</th>"
        "<th style='padding:4px 8px;text-align:right'>Age</th>"
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
            f"<td style='padding:4px 8px'><a href='{url}' target='_blank'>{title}</a></td>"
            f"<td style='padding:4px 8px;text-align:right'>{subs_cell}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{v.get('views', 0):,}</td>"
            "</tr>"
        )
    header = (
        "<table style='width:100%;border-collapse:collapse;font-size:0.9em'>"
        "<thead><tr style='border-bottom:1px solid #ccc'>"
        "<th style='padding:4px 8px;text-align:left'>Video</th>"
        "<th style='padding:4px 8px;text-align:right'>× subs</th>"
        "<th style='padding:4px 8px;text-align:right'>Views</th>"
        "</tr></thead><tbody>"
    )
    return header + "".join(rows) + "</tbody></table>"

if not os.environ.get("YT_KEY"):
    st.sidebar.error("No YouTube key. Add YT_KEY=... to your .env")
if not os.environ.get("ANTHROPIC_API_KEY"):
    st.sidebar.warning("No Claude key yet. Add ANTHROPIC_API_KEY=... to .env for AI summary.")

topic = st.sidebar.text_input("Topic / genre", value="rocket league")

c1, c2 = st.sidebar.columns(2)
after = c1.date_input("From", value=date(2025, 1, 1))
before = c2.date_input("To (optional)", value=None)

tier = st.sidebar.selectbox(
    "Channel size", ["all", "small", "medium", "large"],
    help="Subscriber-based tiers: small <100k . medium 100k-1M . large >1M. "
         "Note: these are FIXED thresholds, not relative to the niche yet.")

max_age = st.sidebar.number_input(
    "Max video age (days, 0 = no limit)", min_value=0, value=0, step=30,
    help="0 keeps all videos. Raising the sample = leave at 0 + widen the From date.")

per_format = st.sidebar.slider(
    "Videos per format", min_value=50, max_value=250, value=50, step=50,
    help="How many Shorts AND how many long-form to pull. More = better stats but "
         "more quota. Each 50 per format = 100 units.")

balanced = st.sidebar.checkbox("Balanced fetch (Shorts + long-form)", value=True)
drop_official = st.sidebar.checkbox(
    "Exclude official/brand channel", value=True,
    help="Drops the game's own channel (e.g. 'Call of Duty') so trailers don't skew results.")

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
    "outliers": "Ranks videos by views-per-day vs the niche median. Shows fastest/slowest per format.",
    "title_len": "Compares title length (characters) of faster vs slower videos.",
    "emoji": "Whether faster videos use emoji more than slower ones.",
    "question": "Whether faster videos use question-style titles.",
    "numbers": "Whether faster videos use numbers or $ in the title.",
    "caps": "ALL-CAPS word count in faster vs slower titles.",
    "hook": "Most common opening words among the fastest videos.",
    "duration": "Video length (seconds) of faster vs slower videos.",
    "timing": "Which weekday the fastest videos tend to post on.",
    "like_rate": "Likes-per-view of faster vs slower videos.",
    "comment_rate": "Comments-per-view of faster vs slower videos.",
    "breakouts": "Videos that beat their channel's subscriber count the most (views/subs).",
    "chan_outlier": "Each video vs its OWN channel average (needs channel-stats fetch).",
    "cadence": "Upload frequency vs total reach per channel (needs channel-stats fetch).",
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
                max_age_days=max_age or None,
                videos_per_format=per_format,
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

    charge_key = f"{topic}|{after}|{before}|{balanced}|{max_age}|{per_format}|{needs_cs}"
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


# ---------------- HEADER + WALLET ----------------
st.title("YouTube Niche Research")

with st.expander("📖 How to read this (plain-language guide)"):
    st.markdown("""
**Velocity (views/day)** — how *fast* a video gathers views, not its total.
A video with 1,000 views in 2 days (500/day) is hotter right now than one with
5,000 views over 100 days (50/day). We rank by this so today's trends rise to the top.

**Niche median** — the *typical* video in your search. Everything is compared to it.
"2× niche median" means twice as fast as the typical video here.

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


for key, out in R["outputs"]:
    with st.container(border=True):
        st.subheader(out["name"])
        st.caption(out["summary"])
        warn = engine.data_warning(key, out)
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
                        "Title": v.get("title"),
                        "Link": v.get("url", f"https://www.youtube.com/watch?v={v.get('id', '')}"),
                        "Channel": v.get("channel"),
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
                st.markdown(f"**{fmt.title()}** — median {b.get('baseline', 0):,} views/day "
                            f"(the reference all multipliers compare to)")
                if b.get("fastest"):
                    st.markdown("Fastest (2×+ the median):")
                    st.markdown(outlier_table(b["fastest"][:8]), unsafe_allow_html=True)
                if b.get("slowest"):
                    st.markdown("Slowest (below 0.5× median) — a 'slow' video may still "
                                "beat its own channel (see × channel typical):")
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
                    else:
                        head = (f"{r['channel']} — median {r['typical_views']:,} over "
                                f"{r['n']} videos . {r['above_count']} above their median")
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