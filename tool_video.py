"""
Tool 2 — Analyse a Specific Video  (UI)
=======================================
Turns one video into actionable lessons, not a data dump. Reuses the niche engine
for age-fair stats. The comparison that matters is "is this a hit FOR THIS CHANNEL?"
(vs the channel's own videos) — not a huge channel vs random tiny videos.

No region picker: irrelevant for analysing a single video.
Honest limits unchanged: clips from transcript content (not retention), risk = hints
(not Content ID), no editing detection.
"""

import os

import streamlit as st
import yt_dashboard as engine
import video_tools as vt


def _q(units):
    if units:
        st.session_state.quota_used += units


def render():
    st.markdown("Paste a video, get **what to steal from it** — age-fair stats vs the "
                "creator's own typical video, the moments the audience flagged, and an "
                "AI teardown. Every heuristic says what it rests on.")

    url = st.text_input("Video URL or ID",
                        placeholder="https://www.youtube.com/watch?v=…")
    c1, c2 = st.columns([3, 2])
    niche = c1.text_input("Your niche / channel focus (optional)",
                          placeholder="e.g. rocket league freestyling",
                          help="Tailors the AI teardown to your content and finds the "
                               "'winners in your lane'. Leave blank to use the video's "
                               "own topic.")
    peers_n = c2.slider("Compare against N similar videos", 0, 150, 50, 50,
                        help="Pulls this many other videos in the same niche to build "
                             "'winners in your lane' + niche context. 0 = skip (saves "
                             "~200 quota units). 50 ≈ 200 units.")
    st.caption("‘Compare against N similar videos’ = how many same-niche videos to fetch "
               "so the tool can show the top performers in your lane. 0 turns it off.")
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

        # vs the channel's OWN videos — the comparison that means something
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

        with st.spinner("Fetching transcript…"):
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
            "comments": comments,
            "moments": vt.mine_comment_moments(comments),
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

    # ---- Performance verdict (meaningful comparison first) ----
    vc = R.get("vs_channel")
    if vc and vc.get("vs_channel_typical"):
        x = vc["vs_channel_typical"]
        verdict = ("a hit for this channel" if x >= 1.5 else
                   "underperforming for this channel" if x < 0.7 else
                   "about typical for this channel")
        st.markdown(f"**vs the creator's own videos:** this runs **{x}×** "
                    f"{vc['channel']}'s typical similar-age video "
                    f"(median ~{vc['channel_median_vpd']:,}/day across "
                    f"{vc['n_channel_videos']} recent uploads) → **{verdict}**. "
                    f"This controls for channel size, so it's the comparison that means "
                    f"something.")
    place = R.get("place")
    if place and place.get("vs_similar_age"):
        x = place["vs_similar_age"]
        med = place.get("similar_age_median") or 0
        if x > 50 and med < 50:
            st.caption("⚠ Niche-peer comparison suppressed: the peers pulled are far "
                       "smaller channels, so a raw multiple here would mostly reflect "
                       "channel size, not the video. Trust the vs-channel number above.")
        else:
            st.caption(f"vs niche peers: {x}× the typical similar-age niche video "
                       f"(median ~{med:,}/day, {place['n_peers']} peers).")

    # ---- Transcript status marker (so you know at a glance) ----
    tr = R["transcript"]
    if tr.get("available"):
        src = "you pasted it" if tr.get("source") == "manual" else "fetched automatically"
        st.success(f"✓ Transcript available ({src}). Summary, clips and pacing are live.")
    else:
        st.warning("✗ No transcript fetched. Open **🎙 Transcript-derived reads** below "
                   "and paste it in to unlock the summary, clips, pacing and risk hints.")

    # ---- AI teardown: the headline, what to steal ----
    hook = ""
    tr = R["transcript"]
    if tr.get("available"):
        hook = vt.opening_hook(tr["segments"], 10) or tr["text"][:300]
    with st.container(border=True):
        st.markdown("### 🔧 What to steal from this video")
        st.caption("Ideas & styles to copy — the moves that make it work.")
        if st.button("Generate teardown (Claude)", type="primary", key="teardown_btn"):
            mined = vt.mine_description(video.get("description", ""),
                                       video_id=video.get("id"))
            with st.spinner("Synthesising why it works + what to steal…"):
                res = vt.video_teardown(video, mined, hook, R.get("moments"),
                                        st.session_state.get("comment_themes"),
                                        R.get("winners"), R.get("niche", ""))
            st.session_state.teardown = res.get("text") or f"Failed: {res.get('error')}"
            if "cost_usd" in res:
                st.session_state.claude_used += res.get("cost_usd", 0) or 0
        if st.session_state.get("teardown"):
            st.markdown(st.session_state.teardown)
        else:
            st.caption("One Claude call ties the hook, structure, audience-flagged "
                       "moments and niche winners into concrete moves you can copy"
                       + (f" for *{R['niche']}*." if R.get("niche") else "."))

    # ---- Video summary: what it was ABOUT (distinct from the teardown) ----
    with st.container(border=True):
        st.markdown("### 📄 Video summary")
        st.caption("What the video was actually about — topics and key points, not advice.")
        if st.button("Summarize this video (Claude)", key="summary_btn"):
            mined = vt.mine_description(video.get("description", ""),
                                       video_id=video.get("id"))
            ttext = tr.get("text", "") if tr.get("available") else ""
            with st.spinner("Summarising the content…"):
                res = vt.summarize_video(video, ttext, mined)
            st.session_state.summary = res.get("text") or f"Failed: {res.get('error')}"
            if "cost_usd" in res:
                st.session_state.claude_used += res.get("cost_usd", 0) or 0
        if st.session_state.get("summary"):
            st.markdown(st.session_state.summary)
        elif not tr.get("available"):
            st.caption("Works best with a transcript (paste one below); otherwise it "
                       "summarises from title, description and chapters.")

    # ---- Audience-flagged moments (honest retention proxy) ----
    moments = R.get("moments") or []
    with st.expander(f"⭐ Moments the audience flagged ({len(moments)})",
                     expanded=bool(moments)):
        if not moments:
            st.caption("No timestamps cited in the comments — or comments not pulled.")
        else:
            st.caption("Timestamps viewers keep quoting in the comments. The closest "
                       "honest signal to 'most replayed' we can get — it's what the "
                       "audience itself pointed at, not retention data.")
            for mo in moments:
                jump = f"{video.get('url')}&t={mo['seconds']}s"
                st.markdown(f"- **[{mo['t']}]({jump})** — cited by {mo['mentions']} "
                            f"comment(s): “{mo['sample']}”")

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
            st.markdown("**Creator chapters** (the creator marked these segments):")
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

    # ---- Transcript-derived (with manual paste fallback) ----
    tr = R["transcript"]
    with st.expander("🎙 Transcript-derived reads", expanded=not tr.get("available")):
        if not tr.get("available"):
            st.info(tr.get("reason") or "No transcript available.")
            st.markdown("**Paste it manually** — YouTube ⋯ → *Show transcript*, copy, "
                        "drop below. Timestamps kept if present; plain text works too.")
        else:
            st.caption("Using your pasted transcript." if tr.get("source") == "manual"
                       else "Auto-fetched transcript. Override below if needed.")

        with st.form(key="paste_form", clear_on_submit=False):
            pasted = st.text_area("Paste transcript", height=160,
                                  placeholder="0:00 what is going on guys\n0:04 …",
                                  label_visibility="collapsed")
            submitted = st.form_submit_button("Use this transcript")
        if submitted and pasted.strip():
            parsed = vt.parse_pasted_transcript(pasted)
            R["transcript"] = {"available": True, "source": "manual",
                               "segments": parsed["segments"], "text": parsed["text"],
                               "has_timestamps": parsed["has_timestamps"]}
            st.session_state.video_result = R
            try:
                import storage
                storage.cache_transcript(video["id"], True, "manual",
                                         parsed["text"], parsed["segments"])
            except Exception:
                pass
            st.session_state.pop("clips", None)
            st.rerun()

        tr = R["transcript"]
        if tr.get("available"):
            segs = tr["segments"]
            has_ts = tr.get("has_timestamps",
                            any((s.get("start") or 0) > 0 for s in segs))
            st.markdown("---")
            if has_ts:
                wpm = vt.transcript_wpm(segs)
                hk = vt.opening_hook(segs, 10)
                st.markdown(f"**Pacing proxy:** ~{wpm} words/min *(text proxy — NOT "
                            f"editing pace/cut frequency, which the API can't give).*")
                if hk:
                    st.markdown(f"**Spoken hook (first 10s):** “{hk}”")
            else:
                fw = " ".join(tr["text"].split()[:30])
                st.caption("No timestamps in this transcript, so words/min and the "
                           "'first 10s' hook aren't available.")
                if fw:
                    st.markdown(f"**Opening (first ~30 words):** “{fw}…”")

            risk = vt.risk_hints(tr["text"])
            st.markdown("**Advertiser-friendliness hints** *(transcript text only — NOT "
                        "Content ID, NOT a copyright/strike prediction):*")
            st.markdown(f"- {risk['ad_friendliness_hint']} "
                        f"({risk['profanity_per_1000_words']}/1000 words)")
            if risk["music_reuse_hint"]:
                st.markdown("- Song/artist mentions → *possible* music-reuse risk to "
                            "check (a hint, not a verdict).")
            if risk["sensitive_keywords"]:
                st.markdown("- Sensitive keywords: " + ", ".join(risk["sensitive_keywords"]))
            st.caption(risk["disclaimer"])

    # ---- AI clips ----
    with st.expander("✂ Suggested Short clips (AI, from transcript content)"):
        if not tr.get("available"):
            st.caption("Needs a transcript (paste one above).")
        else:
            if st.button("Nominate clips (Claude)", key="clip_btn"):
                with st.spinner("Nominating clips…"):
                    res = vt.nominate_clips(video, tr["segments"])
                st.session_state.clips = (res["text"] if "error" not in res
                                          else f"Failed: {res['error']}")
                if "cost_usd" in res:
                    st.session_state.claude_used += res.get("cost_usd", 0) or 0
            if st.session_state.get("clips"):
                st.markdown(st.session_state.clips)
            st.caption("From transcript content, NOT audience-retention / 'most "
                       "replayed' data (not in the API).")

    # ---- Winners in your lane ----
    winners = R.get("winners") or []
    with st.expander("🏆 Winners in your lane — watch how they're cut"):
        if not winners:
            st.caption("Set 'Niche videos to pull' > 0 to populate this.")
        for w in winners:
            q = " · question title" if w.get("is_question") else ""
            st.markdown(f"- [{w['title']}]({w['url']}) — {w['views']:,} views · "
                        f"{w['duration_sec']}s · {w['age_fair_score']}× age-fair{q}")
        if winners:
            st.caption("Age-fair top performers in the same niche+format. Editing isn't "
                       "detectable via API — so watch how these are cut.")

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
