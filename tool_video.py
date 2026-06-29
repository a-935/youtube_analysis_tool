"""
Tool 2 — Analyse a Specific Video  (UI)
=======================================
Deep-dive one video. Reuses the niche engine for every stat (age-fair velocity,
niche placement) and stays honest about the three things the API can't give:
  - clips are nominated from TRANSCRIPT CONTENT, not retention data
  - risk reads are advertiser-friendliness HINTS, not a copyright oracle
  - editing isn't detected; we surface watchable winners + text patterns
See video_tools.py for the engine and the honest labels.
"""

import streamlit as st
import yt_dashboard as engine
import video_tools as vt
import os


def _charge_quota(units):
    if units:
        st.session_state.quota_used += units


def render():
    st.markdown("Paste a video URL or ID. Everything below reuses the same age-fair "
                "velocity engine as the niche tool, and every heuristic says what it "
                "rests on.")

    url = st.text_input("Video URL or ID",
                        placeholder="https://www.youtube.com/watch?v=…")
    c1, c2, c3 = st.columns(3)
    region_label = c1.selectbox("Region (for niche peers)", list(engine.REGIONS.keys()))
    niche_kw = c2.text_input("Niche keyword for comparison",
                             help="Used to fetch similar-age peers so we can place this "
                                  "video in its niche. Leave blank to use the title's "
                                  "main words.")
    peers_n = c3.slider("Peers to pull", 0, 150, 50, 50,
                        help="0 = skip the niche comparison (saves quota). 50 peers "
                             "= ~200 quota units.")
    go = st.button("Analyse video", type="primary")

    if not os.environ.get("YT_KEY"):
        st.warning("No YouTube key found (YT_KEY in .env) — live fetch will fail until "
                   "you add it.")

    if go:
        vid = vt.parse_video_id(url)
        if not vid:
            st.error("Couldn't find a video ID in that input.")
            st.stop()
        with st.spinner("Fetching video…"):
            try:
                video = vt.fetch_video(vid)
                _charge_quota(2)
            except Exception as ex:
                st.error(f"Fetch failed: {ex}")
                st.stop()
        if not video:
            st.error("No video found for that ID.")
            st.stop()

        peers, place, winners = [], None, []
        if peers_n:
            kw = niche_kw.strip() or " ".join((video.get("title") or "").split()[:4])
            with st.spinner(f"Fetching niche peers for '{kw}'…"):
                try:
                    peers, cost, cached = vt.fetch_niche_peers(kw, per_format=peers_n,
                                                               region_label=region_label)
                    if not cached:
                        _charge_quota(cost)
                    place = vt.place_in_niche(video, peers)
                    winners = vt.similar_winners(peers, video)
                except Exception as ex:
                    st.warning(f"Niche comparison skipped: {ex}")

        with st.spinner("Fetching transcript…"):
            transcript = vt.fetch_transcript(vid)

        st.session_state.video_result = {
            "video": video, "place": place, "winners": winners,
            "transcript": transcript, "niche_kw": niche_kw,
        }
        st.session_state.pop("clips", None)
        st.session_state.pop("comment_themes", None)

    R = st.session_state.get("video_result")
    if not R:
        st.info("Paste a video and hit Analyse.")
        st.stop()

    video = R["video"]
    st.markdown("---")
    st.subheader(video.get("title", "(untitled)"))
    st.caption(f"{video.get('channel','')} · {str(video.get('published',''))[:10]} · "
               f"{'Short' if video.get('is_short') else 'long-form'} · "
               f"[open ↗]({video.get('url')})")

    # ---- Stat snapshot (diagnostics) ----
    m = st.columns(4)
    m[0].metric("Views", f"{video.get('views',0):,}")
    m[1].metric("Velocity", f"{video.get('views_per_day',0):,}/day")
    m[2].metric("Age", f"{video.get('age_days',0)} days")
    lr = (video.get("like_rate") or 0) * 100
    m[3].metric("Like rate", f"{lr:.2f}%", help="Diagnostic only — a reach artifact, "
                                                "not a target to optimise.")

    place = R.get("place")
    if place and place.get("vs_similar_age"):
        st.markdown(
            f"**Niche placement (age-fair):** this video runs "
            f"**{place['vs_similar_age']}×** the typical *similar-age* video in its niche "
            f"(median ~{place['similar_age_median']:,}/day across {place['n_peers']} peers). "
            f"Compared within its age band, so old-vs-new is a fair fight.")
    elif R.get("place") is None:
        st.caption("Niche placement skipped (peers set to 0).")

    # ---- Description mining ----
    mined = vt.mine_description(video.get("description", ""), video_id=video.get("id"))
    with st.expander("📝 Description signal (official API data)"):
        if mined["chapters"]:
            st.markdown("**Creator chapters** (great clip candidates — the creator "
                        "literally marked the segments):")
            for ch in mined["chapters"]:
                link = ch.get("url")
                st.markdown(f"- [{ch['t']}]({link}) — {ch['label']}" if link
                            else f"- {ch['t']} — {ch['label']}")
        else:
            st.caption("No creator chapter timestamps found.")
        if mined["hashtags"]:
            st.markdown("**Hashtags:** " + " ".join(mined["hashtags"][:20]))
        if mined["sponsor_mentions"]:
            st.markdown("**Sponsor/affiliate language detected** in the description.")
        if mined["hook_line"]:
            st.caption(f"Opening line: “{mined['hook_line'][:160]}”")

    # ---- Transcript-derived ----
    tr = R["transcript"]
    with st.expander("🎙 Transcript-derived reads",
                     expanded=not tr.get("available")):
        if not tr.get("available"):
            st.info(tr.get("reason") or "No transcript available.")
            st.markdown("**Paste it manually instead** — copy the transcript from "
                        "YouTube (the ⋯ menu → *Show transcript*) and drop it below. "
                        "Timestamps are kept if present; plain text works too.")
        else:
            src = tr.get("source")
            st.caption("Using your pasted transcript." if src == "manual"
                       else "Auto-fetched transcript. You can override it below.")

        with st.form(key="paste_form", clear_on_submit=False):
            pasted = st.text_area(
                "Paste transcript", height=160,
                placeholder="0:00 what is going on guys\n0:04 today we hit insane shots\n…",
                label_visibility="collapsed")
            submitted = st.form_submit_button("Use this transcript")
        if submitted and pasted.strip():
            parsed = vt.parse_pasted_transcript(pasted)
            new_tr = {"available": True, "source": "manual",
                      "segments": parsed["segments"], "text": parsed["text"],
                      "has_timestamps": parsed["has_timestamps"]}
            R["transcript"] = new_tr
            st.session_state.video_result = R
            try:    # cache it so you never paste twice for this video
                import storage
                storage.cache_transcript(video["id"], True, "manual",
                                         parsed["text"], parsed["segments"])
            except Exception:
                pass
            st.session_state.pop("clips", None)   # stale clips for old transcript
            st.rerun()

        tr = R["transcript"]
        if tr.get("available"):
            segs = tr["segments"]
            has_ts = tr.get("has_timestamps",
                            any((s.get("start") or 0) > 0 for s in segs))
            st.markdown("---")
            if has_ts:
                wpm = vt.transcript_wpm(segs)
                hook = vt.opening_hook(segs, 10)
                st.markdown(f"**Pacing proxy:** ~{wpm} words/min "
                            f"*(from transcript text — a proxy, NOT a measure of editing "
                            f"pace or cut frequency, which the API can't give).*")
                if hook:
                    st.markdown(f"**Spoken hook (first 10s):** “{hook}”")
            else:
                first_words = " ".join(tr["text"].split()[:30])
                st.caption("No timestamps in this transcript, so words/min and the "
                           "'first 10 seconds' hook aren't available.")
                if first_words:
                    st.markdown(f"**Opening (first ~30 words):** “{first_words}…”")

            # risk hints — explicitly framed
            risk = vt.risk_hints(tr["text"])
            st.markdown("**Advertiser-friendliness hints** *(from transcript text only — "
                        "NOT Content ID, NOT a copyright/strike prediction):*")
            st.markdown(f"- {risk['ad_friendliness_hint']} "
                        f"({risk['profanity_per_1000_words']}/1000 words)")
            if risk["music_reuse_hint"]:
                st.markdown("- Mentions of songs/artists detected → *possible* music-reuse "
                            "risk to check (a hint, not a verdict).")
            if risk["sensitive_keywords"]:
                st.markdown("- Sensitive keywords present: " +
                            ", ".join(risk["sensitive_keywords"]))
            st.caption(risk["disclaimer"])

    # ---- AI clip nomination ----
    with st.expander("✂ Suggested Short clips (AI, from transcript content)"):
        if not tr.get("available"):
            st.caption("Needs a transcript.")
        else:
            if st.button("Nominate clips (Claude)", key="clip_btn"):
                with st.spinner("Asking Claude to nominate clips…"):
                    res = vt.nominate_clips(video, tr["segments"])
                    if "error" in res:
                        st.session_state.clips = f"Failed: {res['error']}"
                    else:
                        st.session_state.claude_used += res.get("cost_usd", 0) or 0
                        st.session_state.clips = res["text"]
            if st.session_state.get("clips"):
                st.markdown(st.session_state.clips)
            st.caption("Suggested from transcript content, NOT from audience-retention / "
                       "“most replayed” data (that isn't in the API).")

    # ---- Similar winners to learn from ----
    winners = R.get("winners") or []
    with st.expander("🏆 Winners in your lane — watch how they're cut"):
        if not winners:
            st.caption("Pull niche peers (set Peers > 0) to populate this.")
        for w in winners:
            q = " · question title" if w.get("is_question") else ""
            st.markdown(f"- [{w['title']}]({w['url']}) — {w['views']:,} views · "
                        f"{w['duration_sec']}s · {w['age_fair_score']}× age-fair{q}")
        if winners:
            st.caption("These are the age-fair top performers in the same niche+format. "
                       "We can't detect editing via API — so the honest move is: watch "
                       "how these are cut, plus the text patterns above.")

    # ---- Comment themes ----
    with st.expander("💬 Comment themes (AI)"):
        if st.button("Summarise top comments (Claude)", key="cmt_btn"):
            with st.spinner("Fetching comments…"):
                comments = vt.fetch_top_comments(video["id"])
                _charge_quota(1)
            if not comments:
                st.session_state.comment_themes = "No comments available (or disabled)."
            else:
                with st.spinner("Clustering themes…"):
                    try:
                        prompt = vt.build_comment_prompt(comments, video.get("title"))
                        res = engine._call_claude(prompt, max_tokens=900)
                        st.session_state.claude_used += res.get("cost_usd", 0) or 0
                        st.session_state.comment_themes = res["text"]
                    except Exception as ex:
                        st.session_state.comment_themes = f"Claude failed: {ex}"
        if st.session_state.get("comment_themes"):
            st.markdown(st.session_state.comment_themes)
