"""
Tool 3 — Trend Discovery  (SCAFFOLD)
====================================
Not built yet. Honest placeholder for the trend-discovery tool described in
Niche_Research_Expansion_Plan.md §4. The real engine here is velocity +
clustering over time, reusing everything from Tool 1 (_age_banded_baseline,
channel_clustering).

The key honesty point lives here: a single snapshot can only show what's
currently FAST, not what's RISING. True "rising over time" needs stored history
(the §2 archive) to accumulate first.
"""

import streamlit as st


def render():
    st.info("**Not built yet — scaffold.** Phases 6–7 in the build order. "
            "Below is what's genuinely possible, and the one honest catch about "
            "the word \"trending.\"")

    st.selectbox("Genre / seed terms", ["(implemented later)"], disabled=True)
    st.radio("Mode", ["Snapshot — what's fast right now",
                      "Trend — what's accelerating vs last week (needs history)"],
             disabled=True)
    st.button("Discover trends", disabled=True, type="primary")
    st.caption("Controls are disabled until the tool is implemented.")
    st.markdown("---")

    st.markdown("#### What's genuinely possible")
    st.markdown(
        "**✅ Velocity-based emerging topics (the core).** Fetch recent videos for a "
        "genre, rank by *age-fair* velocity, and cluster by shared title keywords/n-grams "
        "into trends. Reuses `_age_banded_baseline` + `channel_clustering`.")
    st.markdown(
        "**✅ Per-trend features:** # videos per trend, # of distinct trends, median/total "
        "views, freshness, **effective-n** (is the trend one channel or many?), and top "
        "example videos.")
    st.markdown(
        "**✅ Emerging vs saturated:** few videos + high velocity = opportunity; many "
        "videos = crowded. Surfacing under-served, fast-rising topics is the gold.")
    st.markdown(
        "**✅ Category trending (coarse but real).** YouTube's `mostPopular` chart per "
        "broad category per region — cheap, real, just not fine-grained.")

    st.markdown("#### The honest catch")
    st.warning(
        "A single snapshot tells you what's currently **fast**, not what's **rising**. "
        "Real trend detection (accelerating over time) needs repeated sampling stored "
        "over days/weeks, then comparing snapshots. So this tool has two modes: "
        "**Snapshot** (works day one) and **Trend** (emerges once the archive from "
        "Phase 2 has accumulated history).")

    st.caption("Same reliability rules as Tool 1: never rank by raw views/day across "
               "different ages; always show effective-n so a \"trend\" that's really one "
               "channel says so.")
