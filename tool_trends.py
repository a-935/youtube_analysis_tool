"""
Tool 3 — Trend Discovery  (UI)
==============================
Pick a BROAD area (Gaming, Cooking, …) and get the SPECIFIC sub-trends popular
inside it right now — each with its most popular videos. Worldwide; no region to
pick (it doesn't matter for finding globally popular niches). Reuses the niche
engine for age-fair scoring + effective-n.

Modes:
  Discover  — broad area -> specific trends (the main flow)
  Trend     — accelerating vs a saved snapshot (needs history)
  Country chart — YouTube's official per-country mostPopular (region is inherent here)
"""

import os

import streamlit as st
import trends_tools as tt
import storage
import exports


def _charge_quota(units):
    if units:
        st.session_state.quota_used += units


def render():
    st.markdown("Pick a broad area and see the **specific niches trending inside it** — "
                "e.g. Gaming → a hot game, Cooking → a viral recipe — each with its most "
                "popular videos. Worldwide.")

    mode = st.radio("Mode", ["Discover — area → specific trends",
                             "Trend — accelerating vs a saved snapshot",
                             "Country chart — official mostPopular"],
                    horizontal=True)

    if not os.environ.get("YT_KEY"):
        st.warning("No YouTube key found (YT_KEY in .env) — live fetch will fail until "
                   "you add it.")

    if mode.startswith("Discover"):
        _render_discover()
    elif mode.startswith("Trend"):
        _render_trend_mode()
    else:
        _render_country()


def _render_discover():
    c1, c2, c3 = st.columns([3, 2, 2])
    area = c1.selectbox("Area", list(tt.BROAD_AREAS.keys()))
    n_trends = c2.slider("How many trends", 3, 20, 8)
    recent = c3.slider("Recent window (days)", 7, 90, 45,
                       help="Only videos published this recently count as 'now'.")
    broad_only = st.checkbox("Only broad trends (many channels, not one viral video)",
                             value=False,
                             help="Filters out trends carried by a single channel or one "
                                  "hit video — keeps niches where lots of independent "
                                  "channels are all getting views.")

    if st.button("Discover trends", type="primary"):
        with st.spinner(f"Finding what's hot in {area}…"):
            try:
                res = tt.discover_area(area, n_trends=max(n_trends, 20),
                                       recent_days=recent)
                _charge_quota(res.get("cost", 0))
                st.session_state.discover = res
            except Exception as ex:
                st.error(f"Discovery failed: {ex}")
                st.stop()

    res = st.session_state.get("discover")
    if not res:
        st.info("Pick an area and hit Discover trends.")
        return
    if not res.get("trends"):
        st.warning(res.get("note") or "No trends found — try a wider recent window.")
        return

    trends = res["trends"]
    if broad_only:
        trends = [t for t in trends if t.get("breadth") == "broad"]
    # broad first, then by opportunity
    rank = {"broad": 0, "mixed": 1, "one-channel": 2, "one-video": 3}
    trends = sorted(trends, key=lambda t: (rank.get(t.get("breadth"), 9),
                                           -t["opportunity"]))[:n_trends]
    if not trends:
        st.warning("No broad trends in this batch — every trend here is carried by one "
                   "channel/video. Untick 'Only broad trends' to see them anyway.")
        return

    st.success(f"**{res['area']}** — {len(trends)} "
               f"{'broad ' if broad_only else ''}trends from {res['n_videos']} recent "
               f"videos worldwide.")
    st.caption(res["note"] + "  🟢 broad = many channels · 🟡 a few · 🔴 one channel/video.")
    st.download_button("⬇ Export (Markdown)", exports.trends_to_markdown(res),
                       file_name=f"{res['area'].lower()}_trends.md")

    for rank_i, t in enumerate(trends, 1):
        emerging = t["stage"].startswith("emerging")
        flag = "🚀 " if emerging else ""
        with st.expander(f"{t['breadth_icon']} {flag}#{rank_i}  {t['trend']}  —  "
                         f"{t['stage']}  ·  opportunity {t['opportunity']}",
                         expanded=(rank_i <= 3)):
            st.markdown(
                f"{t['breadth_icon']} **{t['breadth_note']}** — "
                f"**{t['n_videos']} videos** · **{t['channels']} channels** "
                f"(effective-n **{t['effective_n']}**) · "
                f"median **{t['median_views']:,}** views · heat **{t['heat']}×** age-fair")
            if t["top1_share"] >= 0.5:
                st.caption(f"⚠ One channel owns {t['top1_share']:.0%} of this.")
            st.markdown("**Most popular videos in this trend:**")
            for ex in t["examples"]:
                cols = st.columns([1, 4])
                if ex.get("thumbnail"):
                    cols[0].image(ex["thumbnail"], use_container_width=True)
                cols[1].markdown(
                    f"[{ex['title']}]({ex['url']})  \n"
                    f"{ex.get('channel','')} · **{ex['views']:,}** views · "
                    f"{ex.get('views_per_day','?'):,}/day · {ex['score']}× age-fair")


def _render_trend_mode():
    st.markdown("Compare two saved snapshots of the **same area** to see what's "
                "accelerating. Needs history — save discoveries over days, then compare.")
    snaps = storage.list_trend_snapshots()
    if len(snaps) < 2:
        st.info(f"Only {len(snaps)} saved snapshot(s). Save discoveries (button appears "
                "after you run one) on different days, then come back.")
        return
    labels = {f"#{s['id']} · {s.get('genre','?')} · {str(s.get('ts',''))[:16]}": s
              for s in snaps}
    keys = list(labels.keys())
    c1, c2 = st.columns(2)
    older = c1.selectbox("Older", keys, index=min(1, len(keys) - 1))
    newer = c2.selectbox("Newer", keys, index=0)
    if st.button("Compare", type="primary"):
        diff = tt.diff_trends(labels[older], labels[newer])
        if not diff["changes"]:
            st.info("No overlapping trends to compare.")
            return
        icon = {"accelerating": "🚀", "new": "✨", "steady": "➖",
                "cooling": "🧊", "gone": "💀"}
        for r in diff["changes"]:
            dv = "" if r["heat_delta"] is None else f"  ·  heat Δ {r['heat_delta']:+}"
            st.markdown(f"{icon.get(r['state'],'')} **{r['trend']}** — {r['state']}"
                        f"{dv}  ·  videos Δ {r['videos_delta']:+}")


def _render_country():
    st.markdown("YouTube's official **mostPopular** chart. This one *is* per-country by "
                "design, so the region matters here (and only here).")
    c1, c2 = st.columns(2)
    cat = c1.selectbox("Category", ["(all)"] + list(tt.CATEGORY_IDS.keys()))
    region = c2.text_input("Country code", value="US", max_chars=2,
                           help="ISO code, e.g. US, GB, SA, DE.")
    if st.button("Show chart", type="primary"):
        cat_id = None if cat == "(all)" else tt.CATEGORY_IDS[cat]
        with st.spinner("Fetching mostPopular…"):
            try:
                vids = tt.category_trending(region_code=region.upper(),
                                            category_id=cat_id)
                _charge_quota(1)
                st.session_state.country_vids = vids
            except Exception as ex:
                st.error(f"Fetch failed: {ex}")
                st.stop()
    vids = st.session_state.get("country_vids")
    if vids:
        st.caption(f"{len(vids)} videos on the chart.")
        for v in vids[:25]:
            st.markdown(f"- [{v['title']}]({v['url']}) — {v['channel']} · "
                        f"{v['views']:,} views · {v['views_per_day']:,}/day")
