"""
YouTube Niche Research — App shell  (v4)
========================================
Phase 1 of the 3-tool expansion (see Niche_Research_Expansion_Plan.md).

What changed in v4: the app is now a *shell* with a landing screen and three
tools. The original niche-research tool is untouched — it just moved into
tool_niche.render() and now opens as "Analyse a Niche / Genre". Two more tools
(specific-video deep-dive, trend discovery) are scaffolded as honest "not built
yet" placeholders so the structure is real and navigable.

  app.py          <- this shell: landing grid + tool routing + app-wide wallet
  tool_niche.py   <- Tool 1: the existing niche tool, verbatim
  tool_video.py   <- Tool 2: specific-video analysis (scaffold)
  tool_trends.py  <- Tool 3: trend discovery (scaffold)
  yt_dashboard.py <- the engine, unchanged and shared by all tools

RUN:  streamlit run app.py
"""

import os
from datetime import date, timedelta  # noqa: F401  (kept for parity with tools)


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

# set_page_config must be the first Streamlit call, and run exactly once for the
# whole app — so it lives here in the shell, not inside any tool.
st.set_page_config(page_title="Niche Research", layout="wide")

# App-wide session state. The quota / Claude wallets are shared across every tool
# (one budget for the whole app), so they're initialised here, once.
for k, default in [("quota_used", 0), ("claude_used", 0.0),
                   ("charged_keys", set()), ("results", None),
                   ("active_tool", None)]:
    if k not in st.session_state:
        st.session_state[k] = default

# Import tools AFTER set_page_config / env load. These modules define a render()
# and do no Streamlit work at import time.
import tool_niche
import tool_video
import tool_trends

# id -> (icon, title, one-line blurb, render fn, ready?)
TOOLS = [
    ("niche", "🔬", "Analyse a Niche / Genre",
     "Fetch videos for a topic, split Shorts vs long-form, and surface what's "
     "over/under-performing and what the winners do differently. (The original tool.)",
     tool_niche.render, True),
    ("video", "🎬", "Analyse a Specific Video",
     "Deep-dive one video: age-fair stats vs its niche, transcript, AI-nominated "
     "Short clips, and advertiser-friendliness hints.",
     tool_video.render, True),
    ("trends", "📈", "Trend Discovery",
     "What's rising across genres right now — velocity-ranked emerging topics, "
     "clustered into trends, with saturation and opportunity reads.",
     tool_trends.render, True),
]
TOOLS_BY_ID = {t[0]: t for t in TOOLS}


def _go(tool_id):
    st.session_state.active_tool = tool_id


def _home():
    st.session_state.active_tool = None


def render_landing():
    st.title("YouTube Niche Research")
    st.caption("Pick a tool to start. One wallet (quota + Claude credit) is shared "
               "across all three.")

    # app-wide wallet, visible on the landing screen
    m1, m2 = st.columns(2)
    m1.metric("Quota used (this session)", f"{st.session_state.quota_used:,} units")
    m2.metric("Claude credit used (this session)", f"${st.session_state.claude_used:.4f}")
    st.markdown("---")

    cols = st.columns(len(TOOLS))
    for col, (tid, icon, title, blurb, _fn, ready) in zip(cols, TOOLS):
        with col:
            with st.container(border=True):
                st.markdown(f"### {icon} {title}")
                st.write(blurb)
                if ready:
                    st.button("Open  →", key=f"open_{tid}",
                              type="primary", use_container_width=True,
                              on_click=_go, args=(tid,))
                else:
                    st.button("Coming soon", key=f"open_{tid}",
                              use_container_width=True,
                              on_click=_go, args=(tid,),
                              help="Scaffolded — open it to see what it will do "
                                   "and what's honestly possible.")

    st.markdown("---")
    st.caption("v4 · all three tools live. Tool 1 saves runs to the archive; "
               "cross-run meta-analysis tells real signals from noise over time.")


def render_tool(tool_id):
    icon, title = TOOLS_BY_ID[tool_id][1], TOOLS_BY_ID[tool_id][2]
    # Nav is rendered BEFORE the tool, because a tool's render() may call
    # st.stop() (e.g. the niche tool stops when there are no results yet),
    # which would otherwise swallow anything placed after it.
    top = st.columns([1, 6])
    top[0].button("←  All tools", on_click=_home, use_container_width=True)
    top[1].markdown(f"#### {icon} {title}")
    st.markdown("---")
    TOOLS_BY_ID[tool_id][4]()  # the tool's render()


active = st.session_state.active_tool
if active in TOOLS_BY_ID:
    render_tool(active)
else:
    render_landing()
