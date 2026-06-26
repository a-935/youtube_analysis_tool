"""
YouTube Niche Research — GUI (Streamlit)
========================================
The clickable web front end. It imports the engine (yt_dashboard.py) and turns
the check-mark menu into a real webpage: pick a topic, dates, tier, tick the
tools you want, hit Run, and read the results with CLICKABLE video titles.

HOW TO RUN (in the PyCharm Terminal, from your project folder):
    streamlit run app.py

It opens in your browser at http://localhost:8501
"""

import os
from datetime import date

# --- load the API key from a .env file into the environment BEFORE importing engine ---
def _load_env():
    """Read a simple .env file (KEY=value lines) into os.environ."""
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
import yt_dashboard as engine   # our tested engine

st.set_page_config(page_title="Niche Research", page_icon="🎮", layout="wide")


# ----------------------------------------------------------------------
# Helper: render a list of videos as clickable links
# ----------------------------------------------------------------------
def render_video_list(videos, limit=10):
    """Show videos as clickable markdown links. Uses the engine's url field."""
    for v in videos[:limit]:
        title = v.get("title", "untitled")
        url = v.get("url", "#")
        views = v.get("views")
        extra = f" — {views:,} views" if isinstance(views, int) else ""
        st.markdown(f"- [{title}]({url}){extra}")


# ----------------------------------------------------------------------
# SIDEBAR — all the inputs
# ----------------------------------------------------------------------
st.sidebar.title("🎮 Niche Research")

if not os.environ.get("YT_KEY"):
    st.sidebar.error("No API key found. Create a `.env` file with YT_KEY=your_key")

topic = st.sidebar.text_input("Topic / genre", value="rocket league")

col1, col2 = st.sidebar.columns(2)
after = col1.date_input("From", value=date(2025, 1, 1))
before = col2.date_input("To (optional)", value=None)

tier = st.sidebar.selectbox(
    "Channel size", ["all", "small", "medium", "large"],
    help="small <100k subs · medium 100k–1M · large >1M")

max_age = st.sidebar.number_input("Max video age (days, 0 = no limit)",
                                  min_value=0, value=180, step=30)

balanced = st.sidebar.checkbox("Balanced fetch (Shorts + long-form)", value=True,
                               help="Two searches = 200 quota units, but covers both formats")

st.sidebar.markdown("---")
st.sidebar.subheader("Tools to run")

# Build checkboxes grouped by category, straight from the engine's registry
selected = []
cats = {}
for key, spec in engine.TOOLS.items():
    cats.setdefault(spec["cat"], []).append((key, spec))

for cat, items in cats.items():
    st.sidebar.markdown(f"**{cat}**")
    for key, spec in items:
        label = spec["label"]
        if spec["needs_channel_stats"]:
            label += " ⚙️"
        if st.sidebar.checkbox(label, key=f"chk_{key}"):
            selected.append(key)

st.sidebar.markdown("---")
run = st.sidebar.button("▶ Run analysis", type="primary", use_container_width=True)


# ----------------------------------------------------------------------
# MAIN AREA
# ----------------------------------------------------------------------
st.title("YouTube Niche Research Dashboard")

# Cost meter (estimate before running)
est = engine.estimate_cost(balanced=balanced)
needs_cs = any(engine.TOOLS[k]["needs_channel_stats"] for k in selected)
cost_note = f"~{est} quota units" + (" + channel-stats fetch" if needs_cs else "")
mcol1, mcol2, mcol3 = st.columns(3)
mcol1.metric("Quota wallet", f"{engine.WALLET['quota']:,} / 10,000")
mcol2.metric("Est. cost this run", cost_note)
mcol3.metric("Claude credit", f"${engine.WALLET['claude_usd']:.2f}")

if not run:
    st.info("Pick a topic, tick some tools in the sidebar, then hit **Run analysis**.")
    st.stop()

if not selected:
    st.warning("No tools selected — tick at least one in the sidebar.")
    st.stop()

# --- fetch ---
with st.spinner(f"Fetching '{topic}'…"):
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

# channel-stats fetch if needed
if needs_cs:
    with st.spinner("Fetching channel stats…"):
        engine.fetch_channel_stats(ds)

# tier filter
if tier != "all":
    ds = {**ds, "videos": engine.by_tier(ds["videos"], tier)}

# update wallet
engine.WALLET["quota"] -= ds["cost"]

# --- header stats ---
n = len(ds["videos"])
n_short = sum(v["is_short"] for v in ds["videos"])
src = "♻️ cached (free)" if ds["from_cache"] else f"{ds['cost']} units spent"
st.success(f"{n} videos ({n_short} Shorts, {n - n_short} long-form) · {src} · "
           f"quota left {engine.WALLET['quota']:,}")

if n == 0:
    st.warning("No videos matched. Try widening the dates or tier.")
    st.stop()

# --- run each selected tool ---
for key in selected:
    spec = engine.TOOLS[key]
    out = spec["func"](ds)

    with st.container(border=True):
        st.subheader(out["name"])
        st.caption(out["summary"])

        result = out["result"]

        # Special, nicer rendering for a few tools; generic for the rest.
        if key == "outliers":
            for fmt in ("shorts", "long"):
                block = result.get(fmt, {})
                st.markdown(f"**{fmt.title()} — winners**")
                render_video_list(block.get("winners", []))
                if block.get("losers"):
                    st.markdown(f"**{fmt.title()} — underperformers**")
                    render_video_list(block.get("losers", []))

        elif key == "channels":
            for fmt in ("shorts", "long"):
                rows = result.get(fmt, [])
                if not rows:
                    continue
                st.markdown(f"**{fmt.title()}**")
                for r in rows[:10]:
                    with st.expander(
                        f"{r['channel']} — avg {r['avg_views']:,} "
                        f"over {r['n']} videos · {r['above_count']} beat their avg"):
                        render_video_list(r["above_videos"])

        elif key == "breakouts":
            for fmt in ("shorts", "long"):
                vids = result.get(fmt, {}).get("top", [])
                if vids:
                    st.markdown(f"**{fmt.title()}**")
                    for v in vids[:8]:
                        st.markdown(f"- [{v['title']}]({v['url']}) — "
                                    f"{v['views_per_sub']}x subs, {v['views']:,} views")

        else:
            # Generic: list every clickable title this tool surfaced
            links = engine.linkable_titles(result)
            seen, uniq = set(), []
            for t, u, vw in links:
                if u not in seen:
                    seen.add(u)
                    uniq.append((t, u, vw))
            if uniq:
                with st.expander(f"See {len(uniq)} related videos"):
                    for t, u, vw in uniq[:15]:
                        extra = f" — {vw:,} views" if isinstance(vw, int) else ""
                        st.markdown(f"- [{t}]({u}){extra}")
            else:
                st.write("(no individual videos for this tool)")

st.caption(f"Claude credit (separate wallet): ${engine.WALLET['claude_usd']:.2f} unused")
