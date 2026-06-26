"""
YouTube Niche Research — GUI (Streamlit)  v2
============================================
Fixes over v1:
- Wallet shows units USED this session (honest), not a fake used/total that
  resets to "full" on restart. Charged once per real fetch, never double-counted.
- Every score shows its baseline/average for context.
- Pattern tools show each video's MEASURED value (chars, emoji yes/no, etc.)
  split into faster vs slower groups — no more repeated identical lists.
- Channels with too few videos are flagged as low-sample.
- Option to exclude the game's official/brand channel.
- Results persist across reruns (stored in session_state).

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

st.set_page_config(page_title="Niche Research", page_icon="game_die", layout="wide")

if "quota_used" not in st.session_state:
    st.session_state.quota_used = 0
if "charged_keys" not in st.session_state:
    st.session_state.charged_keys = set()
if "results" not in st.session_state:
    st.session_state.results = None


def fmt_views(n):
    return f"{n:,}" if isinstance(n, int) else "-"


def vid_line(card):
    bits = []
    if card.get("value") is not None:
        bits.append(f"**{card['value']}**")
    if card.get("views") is not None:
        bits.append(f"{fmt_views(card['views'])} views")
    if card.get("vs_baseline") is not None:
        bits.append(f"{card['vs_baseline']}x niche median")
    if card.get("vs_channel_avg") is not None:
        bits.append(f"{card['vs_channel_avg']}x channel avg")
    if card.get("age_days") is not None:
        bits.append(f"{card['age_days']}d old")
    meta = " . ".join(bits)
    st.markdown(f"- [{card['title']}]({card['url']}) - {meta}")


# ---------------- SIDEBAR ----------------
st.sidebar.title("Niche Research")

if not os.environ.get("YT_KEY"):
    st.sidebar.error("No API key. Make a .env file with YT_KEY=your_key")

topic = st.sidebar.text_input("Topic / genre", value="rocket league")

c1, c2 = st.sidebar.columns(2)
after = c1.date_input("From", value=date(2025, 1, 1))
before = c2.date_input("To (optional)", value=None)

tier = st.sidebar.selectbox("Channel size", ["all", "small", "medium", "large"],
                            help="small <100k . medium 100k-1M . large >1M")

max_age = st.sidebar.number_input("Max video age (days, 0 = no limit)",
                                  min_value=0, value=0, step=30,
                                  help="0 = keep all. Leave at 0 for a bigger sample.")

balanced = st.sidebar.checkbox("Balanced fetch (Shorts + long-form)", value=True,
                               help="Two searches = 200 units, covers both formats")

drop_official = st.sidebar.checkbox("Exclude official/brand channel", value=True,
                                    help="Drops e.g. the 'Call of Duty' channel itself")

st.sidebar.markdown("---")
st.sidebar.subheader("Tools to run")

selected = []
cats = {}
for key, spec in engine.TOOLS.items():
    cats.setdefault(spec["cat"], []).append((key, spec))
for cat, items in cats.items():
    st.sidebar.markdown(f"**{cat}**")
    for key, spec in items:
        label = spec["label"] + (" (gear)" if spec["needs_channel_stats"] else "")
        if st.sidebar.checkbox(label, key=f"chk_{key}"):
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
            )
        except Exception as e:
            st.error(f"Fetch failed: {e}")
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

    charge_key = f"{topic}|{after}|{before}|{balanced}|{max_age}|{needs_cs}"
    spent = (ds["cost"] + cs_cost) if not ds["from_cache"] else 0
    if spent and charge_key not in st.session_state.charged_keys:
        st.session_state.quota_used += spent
        st.session_state.charged_keys.add(charge_key)

    outputs = [(k, engine.TOOLS[k]["func"](ds)) for k in selected]
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
m2.metric("Claude credit", f"${engine.WALLET['claude_usd']:.2f}")

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
               f"Widen the dates or set Max age to 0.")


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

        if key == "outliers":
            for fmt in ("shorts", "long"):
                b = result.get(fmt, {})
                st.markdown(f"**{fmt.title()}** - median {b.get('baseline', 0):,}/day")
                if b.get("fastest"):
                    st.markdown("Fastest (above 2x median):")
                    for c in b["fastest"][:8]:
                        vid_line(c)
                if b.get("slowest"):
                    st.markdown("Slowest (below 0.5x median) - note channel-avg:")
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
                            st.markdown(f"- [{v['title']}]({v['url']}) - "
                                        f"{fmt_views(v['views'])} views")

        elif key == "breakouts":
            for fmt in ("shorts", "long"):
                vids = result.get(fmt, {}).get("top", [])
                if vids:
                    st.markdown(f"**{fmt.title()}**")
                    for v in vids[:8]:
                        st.markdown(f"- [{v['title']}]({v['url']}) - "
                                    f"{v['views_per_sub']}x subs, {fmt_views(v['views'])} views")

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

st.caption(f"Claude credit (separate wallet): ${engine.WALLET['claude_usd']:.2f} unused")