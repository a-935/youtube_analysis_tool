"""
Tool 2 — Analyse a Specific Video  (UI)  ·  build v5
====================================================
v5: auto-fetch transcript (with paste override), a FULL transcript viewer so you can
confirm what was captured, a whole-video summary, and Short-ability on every clip
(cross-referenced with what the audience already flagged). No region (irrelevant for
one video). Honest limits unchanged.
"""

import os

import streamlit as st
import yt_dashboard as engine
import video_tools as vt

BUILD = "v5"


def _q(units):
    if units:
        st.session_state.quota_used += units


def render():
    st.caption(f"Tool 2 build **{BUILD}** — if you don't see this tag, you're running an "
               f"old file.")
    st.markdown("Paste a video, get **what to steal**, a **summary**, and **which parts "
                "can be Shorts**. Transcript is auto-fetched (paste to override).")

    url = st.text_input("Video URL or ID",
                        placeholder="https://www.youtube.com/watch?v=…")
    c1, c2 = st.columns([3, 2])
    niche = c1.text_input("Your niche / channel focus (optional)",
                          placeholder="e.g. rocket league freestyling",
                          help="Tailors the teardown to your content + finds 'winners in "
                               "your lane'.")
    peers_n = c2.slider("Compare against N similar videos", 0, 150, 50, 50,
                        help="Pulls this many same-niche videos for 'winners in your "
                             "lane' + niche context. 0 = skip (saves ~200 units).")
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
                _q(2)
            except Exception as ex:
                st.error(f"Fetch failed: {ex}")
                st.stop()
        if not video:
            st.error("No video found for that ID.")
            st.stop()

        vs_channel = None
        with st.spinner("Comparing to the channel's own recent videos…"):
            try:
                ch_vids = vt.fetch_channel_recent(video["channel_id"], n=25)
                _q(101)
                vs_channel = vt.place_vs_channel(video, ch_vids)
            except Exception:
                vs_channel = None

        peers, place, winners = [], None, []
        if peers_n:
            kw = niche.strip() or " ".join((video.get("title") or "").split()[:4])
            with st.spinner(f"Pulling niche videos for '{kw}'…"):
                try:
                    peers, cost, cached = vt.fetch_niche_peers(kw, per_format=peers_n)
                    if not cached:
                        _q(cost)
                    place = vt.place_in_niche(video, peers)
                    winners = vt.similar_winners(peers, video)
                except Exception as ex:
                    st.warning(f"Niche pull skipped: {ex}")

        with st.spinner("Auto-fetching transcript…"):
            transcript = vt.fetch_transcript(vid)
        with st.spinner("Fetching comments…"):
            try:
                comments = vt.fetch_top_comments(vid)
                _q(1)
            except Exception:
                comments = []

        st.session_state.video_result = {
            "video": video, "vs_channel": vs_channel, "place": place,
            "winners": winners, "transcript": transcript, "niche": niche,
            "comments": comments, "moments": vt.mine_comment_moments(comments),
            "title": vt.analyze_title(video, winners),
        }
        for k in ("clips", "comment_themes", "teardown", "summary"):
            st.session_state.pop(k, None)

    R = st.session_state.get("video_result")
    if not R:
        st.info("Paste a video and hit Analyse.")
        st.stop()

    video = R["video"]
    st.markdown("---")
    cimg, cmeta = st.columns([1, 3])
    if video.get("thumbnail"):
        cimg.image(video["thumbnail"], use_container_width=True)
    cmeta.subheader(video.get("title", "(untitled)"))
    cmeta.caption(f"{video.get('channel','')} · {str(video.get('published',''))[:10]} · "
                  f"{'Short' if video.get('is_short') else 'long-form'} · "
                  f"[open ↗]({video.get('url')})")

    m = st.columns(4)
    m[0].metric("Views", f"{video.get('views',0):,}")
    m[1].metric("Velocity", f"{video.get('views_per_day',0):,.0f}/day")
    m[2].metric("Age", f"{video.get('age_days',0)} days")
    m[3].metric("Like rate", f"{(video.get('like_rate') or 0)*100:.2f}%",
                help="Diagnostic only — a reach artifact, not a target.")

    # ---- Performance verdict ----
    vc = R.get("vs_channel")
    if vc and vc.get("vs_channel_typical"):
        x = vc["vs_channel_typical"]
        verdict = ("a hit for this channel" if x >= 1.5 else
                   "underperforming for this channel" if x < 0.7 else
                   "about typical for this channel")
        st.markdown(f"**vs the creator's own videos:** **{x}×** {vc['channel']}'s typical "
                    f"similar-age video (median ~{vc['channel_median_vpd']:,}/day across "
                    f"{vc['n_channel_videos']} uploads) → **{verdict}**. Controls for "
                    f"channel size — the comparison that means something.")
    place = R.get("place")
    if place and place.get("vs_similar_age"):
        x = place["vs_similar_age"]; med = place.get("similar_age_median") or 0
        if x > 50 and med < 50:
            st.caption("⚠ Niche-peer comparison suppressed: peers are far smaller "
                       "channels, so a raw multiple would mostly reflect channel size. "
                       "Trust the vs-channel number.")
        else:
            st.caption(f"vs niche peers: {x}× the typical similar-age niche video "
                       f"(median ~{med:,}/day, {place['n_peers']} peers).")

    # ---- Transcript status marker ----
    tr = R["transcript"]
    if tr.get("available"):
        wc = len((tr.get("text") or "").split())
        how = "you pasted it" if tr.get("source") == "manual" else "auto-fetched ✓"
        st.success(f"### ✅ Transcript captured ({how}) — {wc:,} words\n"
                   "Open **📜 Full transcript** below to read exactly what was captured. "
                   "Summary, clips, pacing and risk hints are unlocked.")
    else:
        st.error("### ❌ Transcript NOT captured\n"
                 f"Reason: {tr.get('reason') or 'no captions'}. Auto-fetch failed (YouTube "
                 "sometimes blocks it). Open **📜 Full transcript** below and paste it to "
                 "unlock summary, clips, pacing and risk hints. Everything else already ran.")

    # ---- FULL transcript viewer + paste override ----
    with st.expander("📜 Full transcript (read it / verify it / paste your own)",
                     expanded=not tr.get("available")):
        if tr.get("available"):
            st.caption(f"This is the exact transcript the AI is using "
                       f"({len((tr.get('text') or '').split()):,} words). Scroll to check it.")
            st.text_area("Captured transcript", value=tr.get("text", ""), height=260,
                         disabled=True, label_visibility="collapsed")
            st.markdown("**Wrong or incomplete?** Paste a better one to replace it:")
        else:
            st.markdown("Paste the transcript (YouTube ⋯ → *Show transcript* → copy):")
        with st.form("paste_form", clear_on_submit=False):
            pasted = st.text_area("Paste transcript", height=150,
                                  placeholder="0:00 what is going on guys\n0:04 …",
                                  label_visibility="collapsed")
            if st.form_submit_button("Use this transcript"):
                if pasted.strip():
                    parsed = vt.parse_pasted_transcript(pasted)
                    R["transcript"] = {"available": True, "source": "manual",
                                       "segments": parsed["segments"],
                                       "text": parsed["text"],
                                       "has_timestamps": parsed["has_timestamps"]}
                    st.session_state.video_result = R
                    st.session_state.pop("clips", None)
                    st.session_state.pop("summary", None)
                    try:
                        import storage
                        storage.cache_transcript(video["id"], True, "manual",
                                                 parsed["text"], parsed["segments"])
                    except Exception:
                        pass
                    st.rerun()

    # ---- What to steal (teardown) ----
    tr = R["transcript"]
    hook = vt.opening_hook(tr["segments"], 10) if tr.get("available") else ""
    with st.container(border=True):
        st.markdown("### 🔧 What to steal from this video")
        st.caption("Ideas & styles to copy — the moves that make it work.")
        if st.button("Generate teardown (Claude)", type="primary", key="teardown_btn"):
            mined = vt.mine_description(video.get("description", ""), video_id=video.get("id"))
            with st.spinner("Synthesising what to steal…"):
                res = vt.video_teardown(video, mined, hook, R.get("moments"),
                                        st.session_state.get("comment_themes"),
                                        R.get("winners"), R.get("niche", ""))
            st.session_state.teardown = res.get("text") or f"Failed: {res.get('error')}"
            if "cost_usd" in res:
                st.session_state.claude_used += res.get("cost_usd", 0) or 0
        if st.session_state.get("teardown"):
            st.markdown(st.session_state.teardown)

    # ---- Video summary (what it was ABOUT) ----
    with st.container(border=True):
        st.markdown("### 📄 Video summary")
        st.caption("What the video was actually about — its ideas, context and key points.")
        if st.button("Summarize this video (Claude)", type="primary", key="summary_btn"):
            mined = vt.mine_description(video.get("description", ""), video_id=video.get("id"))
            ttext = tr.get("text", "") if tr.get("available") else ""
            with st.spinner("Summarising the content…"):
                res = vt.summarize_video(video, ttext, mined)
            st.session_state.summary = res.get("text") or f"Failed: {res.get('error')}"
            if "cost_usd" in res:
                st.session_state.claude_used += res.get("cost_usd", 0) or 0
        if st.session_state.get("summary"):
            st.markdown(st.session_state.summary)
        elif not tr.get("available"):
            st.caption("Works best with a transcript; otherwise summarises from title, "
                       "description and chapters.")

    # ---- Can I make Shorts from this? ----
    moments = R.get("moments") or []
    with st.container(border=True):
        st.markdown("### ✂ Can I make Shorts from this?")
        if moments:
            safe = ", ".join(f"[{mo['t']}]({video.get('url')}&t={mo['seconds']}s)"
                             for mo in moments[:6])
            st.markdown(f"**🔥 Safest Short bets — the audience already quoted these "
                        f"moments:** {safe}")
            st.caption("People re-quote the bits worth clipping. Those timestamps are your "
                       "lowest-risk Shorts. Below, the AI rates each clip's Short potential.")
        if not tr.get("available"):
            st.info("Add a transcript (above) to get AI clip nominations with Short ratings.")
        else:
            if st.button("Nominate clips + rate Short potential (Claude)", key="clip_btn"):
                with st.spinner("Finding clips and rating them…"):
                    res = vt.nominate_clips(video, tr["segments"], moments)
                st.session_state.clips = (res["text"] if "error" not in res
                                          else f"Failed: {res['error']}")
                if "cost_usd" in res:
                    st.session_state.claude_used += res.get("cost_usd", 0) or 0
            if st.session_state.get("clips"):
                st.markdown(st.session_state.clips)
            st.caption("From transcript content, NOT audience-retention / 'most replayed' "
                       "data (not in the API).")

    # ---- Audience-flagged moments ----
    with st.expander(f"⭐ Moments the audience flagged ({len(moments)})"):
        if not moments:
            st.caption("No timestamps cited in the comments (or comments unavailable).")
        else:
            st.caption("Timestamps viewers keep quoting — the closest honest signal to "
                       "'most replayed' (not retention data).")
            for mo in moments:
                jump = f"{video.get('url')}&t={mo['seconds']}s"
                st.markdown(f"- **[{mo['t']}]({jump})** — ×{mo['mentions']}: "
                            f"“{mo['sample']}”")

    # ---- Transcript-derived reads ----
    with st.expander("🎙 Pacing, hook & risk (from transcript)"):
        if not tr.get("available"):
            st.caption("Add a transcript above to unlock these.")
        else:
            segs = tr["segments"]
            has_ts = tr.get("has_timestamps", any((s.get("start") or 0) > 0 for s in segs))
            if has_ts:
                st.markdown(f"**Pacing proxy:** ~{vt.transcript_wpm(segs)} words/min "
                            f"*(text proxy — NOT editing pace, which the API can't give).*")
                hk = vt.opening_hook(segs, 10)
                if hk:
                    st.markdown(f"**Spoken hook (first 10s):** “{hk}”")
            else:
                st.caption("No timestamps in this transcript — words/min and the 10s hook "
                           "aren't available.")
            risk = vt.risk_hints(tr["text"])
            st.markdown("**Advertiser-friendliness hints** *(transcript text only — NOT "
                        "Content ID / strike prediction):*")
            st.markdown(f"- {risk['ad_friendliness_hint']} "
                        f"({risk['profanity_per_1000_words']}/1000 words)")
            if risk["music_reuse_hint"]:
                st.markdown("- Song/artist mentions → possible music-reuse risk to check.")
            if risk["sensitive_keywords"]:
                st.markdown("- Sensitive keywords: " + ", ".join(risk["sensitive_keywords"]))
            st.caption(risk["disclaimer"])

    # ---- Title read ----
    ti = R.get("title") or {}
    with st.expander("🔤 Title read"):
        bits = [f"{ti.get('word_count')} words / {ti.get('char_count')} chars"]
        if ti.get("has_number"):
            bits.append("has a number")
        if ti.get("is_question"):
            bits.append("is a question")
        if ti.get("has_allcaps_word"):
            bits.append("has an ALL-CAPS word")
        st.markdown("- " + " · ".join(bits))
        if ti.get("winners_median_words") is not None:
            st.markdown(f"- {ti['vs_winners']} the niche winners "
                        f"(they median {ti['winners_median_words']} words)")

    # ---- Description mining ----
    mined = vt.mine_description(video.get("description", ""), video_id=video.get("id"))
    with st.expander("📝 Description signal (official API data)"):
        if mined["chapters"]:
            st.markdown("**Creator chapters:**")
            for ch in mined["chapters"]:
                link = ch.get("url")
                st.markdown(f"- [{ch['t']}]({link}) — {ch['label']}" if link
                            else f"- {ch['t']} — {ch['label']}")
        else:
            st.caption("No creator chapter timestamps found.")
        if mined["hashtags"]:
            st.markdown("**Hashtags:** " + " ".join(mined["hashtags"][:20]))
        if mined["sponsor_mentions"]:
            st.markdown("**Sponsor/affiliate language detected.**")
        if mined["hook_line"]:
            st.caption(f"Opening line: “{mined['hook_line'][:160]}”")

    # ---- Winners in your lane ----
    winners = R.get("winners") or []
    with st.expander("🏆 Winners in your lane — watch how they're cut"):
        if not winners:
            st.caption("Set 'Compare against N similar videos' > 0 to populate this.")
        for w in winners:
            q = " · question title" if w.get("is_question") else ""
            st.markdown(f"- [{w['title']}]({w['url']}) — {w['views']:,} views · "
                        f"{w['duration_sec']}s · {w['age_fair_score']}× age-fair{q}")

    # ---- Comment themes ----
    with st.expander("💬 Comment themes (AI)"):
        if st.button("Summarise top comments (Claude)", key="cmt_btn"):
            comments = R.get("comments") or []
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
