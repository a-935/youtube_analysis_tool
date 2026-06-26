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

st.set_page_config(page_title="Niche Research", layout="wide")

for k, default in [("quota_used", 0), ("claude_used", 0.0),
                   ("charged_keys", set()), ("results", None)]:
    if k not in st.session_state:
        st.session_state[k] = default


def fmt_views(n):
    return f"{n:,}" if isinstance(n, int) else "-"


def vid_line(card):
    bits = []
    if card.get("value") is not None:
        bits.append(f"**{card['value']}**")
    if card.get("views") is not None:
        bits.append(f"{fmt_views(card['views'])} views")
    if card.get("vs_baseline") is not None:
        bits.append(f"{card['vs_baseline']}x the niche median velocity")
    if card.get("vs_channel_avg") is not None:
        bits.append(f"{card['vs_channel_avg']}x its own channel avg")
    if card.get("age_days") is not None:
        bits.append(f"{card['age_days']}d old")
    st.markdown(f"- [{card['title']}]({card['url']}) - " + " . ".join(bits))


# ---------------- SIDEBAR ----------------
st.sidebar.title("Niche Research")

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
        if k == "ai_summary":
            with st.spinner("Asking Claude..."):
                out = engine.TOOLS[k]["func"](ds)
            st.session_state.claude_used += out.get("claude_cost_usd", 0) or 0
        else:
            out = engine.TOOLS[k]["func"](ds)
        outputs.append((k, out))

    st.session_state.results = {
        "topic": topic,
        "ds_meta": {"n": len(ds["videos"]),
                    "n_short": sum(v["is_short"] for v in ds["videos"]),
                    "from_cache": ds["from_cache"], "spent": spent},
        "outputs": outputs,
    }


# ---------------- HEADER + WALLET ----------------
st.title("YouTube Niche Research")

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


def render_pattern(result):
    for fmt in ("shorts", "long"):
        block = result.get(fmt, {})
        top, bot = block.get("top_items", []), block.get("bottom_items", [])
        if not top and not bot:
            continue
        st.markdown(f"**{fmt.title()}** - faster videos")
        for c in top[:6]:
            vid_line(c)
        if bot:
            st.markdown(f"**{fmt.title()}** - slower videos")
            for c in bot[:6]:
                vid_line(c)


for key, out in R["outputs"]:
    with st.container(border=True):
        st.subheader(out["name"])
        st.caption(out["summary"])
        result = out["result"]

        if key == "ai_summary":
            if result.get("text"):
                st.markdown(result["text"])
            else:
                st.error(result.get("error", "No response."))

        elif key == "outliers":
            for fmt in ("shorts", "long"):
                b = result.get(fmt, {})
                st.markdown(f"**{fmt.title()}** - median {b.get('baseline', 0):,} views/day "
                            f"(this is the reference all multipliers below compare to)")
                if b.get("fastest"):
                    st.markdown("Fastest (2x+ the median views/day):")
                    for c in b["fastest"][:8]:
                        vid_line(c)
                if b.get("slowest"):
                    st.markdown("Slowest (below 0.5x the median views/day) - "
                                "check the channel-avg column, a 'slow' video may still beat its channel:")
                    for c in b["slowest"][:8]:
                        vid_line(c)

        elif key == "channels":
            for fmt in ("shorts", "long"):
                rows = result.get(fmt, [])
                if not rows:
                    continue
                st.markdown(f"**{fmt.title()}**")
                for r in rows[:12]:
                    low = " . (low sample)" if r["n"] < 3 else ""
                    head = (f"{r['channel']} - avg {r['avg_views']:,} over "
                            f"{r['n']} videos . {r['above_count']} beat avg{low}")
                    with st.expander(head):
                        for v in r["above_videos"]:
                            st.markdown(f"- [{v['title']}]({v['url']}) - {fmt_views(v['views'])} views")

        elif key == "breakouts":
            for fmt in ("shorts", "long"):
                vids = result.get(fmt, {}).get("top", [])
                if vids:
                    st.markdown(f"**{fmt.title()}**")
                    for v in vids[:8]:
                        st.markdown(f"- [{v['title']}]({v['url']}) - "
                                    f"{v['views_per_sub']}x its subscriber count, {fmt_views(v['views'])} views")

        elif key in ("title_len", "emoji", "question", "numbers", "caps",
                     "duration", "like_rate", "comment_rate"):
            render_pattern(result)

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