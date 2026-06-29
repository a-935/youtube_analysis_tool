"""
Tool 3 — Trend Discovery  (UI)
==============================
Velocity + clustering over a genre, reusing the niche engine (age-fair scoring,
effective-n). Honest about "trending": a single snapshot shows what's FAST now,
not what's RISING — that needs stored history, which the archive accumulates.
See trends_tools.py for the engine.
"""

import os

import streamlit as st
import yt_dashboard as engine
import trends_tools as tt
import storage
import exports


def _charge_quota(units):
    if units:
        st.session_state.quota_used += units


def render():
    st.markdown("Find what's fast across a genre: recent videos ranked by **age-fair "
                "velocity**, clustered into trends, with saturation and an opportunity "
                "score (high rise ÷ low competition).")

    mode = st.radio("Mode", ["Snapshot — what's fast now",
                             "Trend — accelerating vs a past snapshot",
                             "Category chart — YouTube mostPopular"],
                    horizontal=True)

    if not os.environ.get("YT_KEY"):
        st.warning("No YouTube key found (YT_KEY in .env) — live fetch will fail until "
                   "you add it.")

    if mode.startswith("Snapshot"):
        _render_snapshot()
    elif mode.startswith("Trend"):
        _render_trend_mode()
    else:
        _render_category()


def _render_snapshot():
    c1, c2, c3 = st.columns([3, 2, 2])
    genre = c1.text_input("Genre / seed terms", value="rocket league")
    region_label = c2.selectbox("Region", list(engine.REGIONS.keys()))
    per_format = c3.slider("Videos per format", 50, 250, 50, 50)
    min_cluster = st.slider("Min videos to call something a trend", 2, 8, 3)

    if st.button("Discover trends", type="primary"):
        with st.spinner(f"Fetching '{genre}' and clustering…"):
            try:
                snap = tt.snapshot(genre, per_format=per_format,
                                   region_label=region_label, min_cluster=min_cluster)
                if not snap.get("from_cache"):
                    _charge_quota(snap.get("cost", 0))
                st.session_state.trend_snapshot = snap
            except Exception as ex:
                st.error(f"Snapshot failed: {ex}")
                st.stop()

    snap = st.session_state.get("trend_snapshot")
    if not snap:
        st.info("Pick a genre and hit Discover trends.")
        return

    st.success(f"**{snap['topic']}** — {snap['n_trends']} trends from "
               f"{snap['n_videos']} videos "
               f"({snap['unclustered']} didn't cluster).")
    st.caption(snap["note"])

    csave, cexp = st.columns(2)
    if csave.button("💾 Save snapshot (for Trend mode later)", use_container_width=True):
        try:
            sid = storage.save_trend_snapshot(snap["topic"],
                                              snap.get("region", ""), snap["trends"])
            st.session_state.trend_snapshot["ts"] = "saved"
            st.success(f"Saved snapshot #{sid}. Re-run in a few days, then use Trend mode.")
        except Exception as ex:
            st.warning(f"Save failed: {ex}")
    cexp.download_button("⬇ Export (Markdown)", exports.trends_to_markdown(snap),
                         file_name="trend_snapshot.md", use_container_width=True)

    for t in snap["trends"]:
        emerging = t["stage"].startswith("emerging")
        flag = "🚀 " if emerging else ""
        with st.expander(f"{flag}{t['trend']} — {t['stage']}  ·  opportunity "
                         f"{t['opportunity']}"):
            st.markdown(
                f"- **{t['n_videos']} videos** across **{t['channels']} channels** "
                f"(effective-n **{t['effective_n']}** — "
                f"{'really just a few channels' if t['effective_n'] < 3 else 'genuinely several'})")
            st.markdown(f"- median **{t['median_views']:,}** views · freshness "
                        f"**{t['median_age_days']}** days · heat **{t['heat']}×** age-fair")
            if t["top1_share"] >= 0.5:
                st.caption(f"⚠ One channel holds {t['top1_share']:.0%} of this trend — "
                           f"treat it as that channel's thing, not a broad trend.")
            for ex in t["examples"]:
                st.markdown(f"  - [{ex['title']}]({ex['url']}) — {ex['views']:,} views "
                            f"({ex['score']}× age-fair)")


def _render_trend_mode():
    st.markdown("Compare two saved snapshots of the **same genre** to see what's "
                "accelerating. This is the honest 'rising over time' read — it needs "
                "history, so save snapshots over days/weeks first.")
    snaps = storage.list_trend_snapshots()
    if len(snaps) < 2:
        st.info(f"Only {len(snaps)} saved snapshot(s). Save at least two (same genre, "
                "different days) from Snapshot mode, then come back.")
        return
    labels = {f"#{s['id']} · {s.get('genre','?')} · {str(s.get('ts',''))[:16]}": s
              for s in snaps}
    keys = list(labels.keys())
    c1, c2 = st.columns(2)
    older = c1.selectbox("Older snapshot", keys, index=min(1, len(keys) - 1))
    newer = c2.selectbox("Newer snapshot", keys, index=0)
    if st.button("Compare", type="primary"):
        diff = tt.diff_trends(labels[older], labels[newer])
        rows = diff["changes"]
        if not rows:
            st.info("No overlapping trends to compare.")
            return
        icon = {"accelerating": "🚀", "new": "✨", "steady": "➖",
                "cooling": "🧊", "gone": "💀"}
        for r in rows:
            dv = "" if r["heat_delta"] is None else f"  ·  heat Δ {r['heat_delta']:+}"
            st.markdown(f"{icon.get(r['state'],'')} **{r['trend']}** — {r['state']}"
                        f"{dv}  ·  videos Δ {r['videos_delta']:+}")


def _render_category():
    st.markdown("YouTube's official **mostPopular** chart — broad but real. Coarse "
                "categories, not fine-grained trends.")
    c1, c2 = st.columns(2)
    cat = c1.selectbox("Category", ["(all)"] + list(tt.CATEGORY_IDS.keys()))
    region = c2.text_input("Region code", value="US", max_chars=2,
                           help="ISO country code, e.g. US, GB, DE.")
    if st.button("Show chart", type="primary"):
        cat_id = None if cat == "(all)" else tt.CATEGORY_IDS[cat]
        with st.spinner("Fetching mostPopular…"):
            try:
                vids = tt.category_trending(region_code=region.upper(),
                                            category_id=cat_id)
                _charge_quota(1)
                st.session_state.category_vids = vids
            except Exception as ex:
                st.error(f"Fetch failed: {ex}")
                st.stop()
    vids = st.session_state.get("category_vids")
    if vids:
        st.caption(f"{len(vids)} videos on the chart.")
        for v in vids[:25]:
            st.markdown(f"- [{v['title']}]({v['url']}) — {v['channel']} · "
                        f"{v['views']:,} views · {v['views_per_day']:,}/day")
