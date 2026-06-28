"""
Tool 2 — Analyse a Specific Video  (SCAFFOLD)
=============================================
Not built yet. This is the honest placeholder for the specific-video deep-dive
described in Niche_Research_Expansion_Plan.md §3. It states up front what's
solid, what needs a library, and what is NOT real — so we don't rebuild the
"dumb logic" problem when we wire it up.

When implemented, this tool will reuse the existing engine (fetch_dataset,
enrich, _age_banded_baseline) rather than fork the velocity/age logic.
"""

import streamlit as st


def render():
    st.info("**Not built yet — scaffold.** This is Phase 5 in the build order. "
            "Below is exactly what it will do, and what's honestly possible.")

    vid = st.text_input("Video URL or ID", placeholder="https://www.youtube.com/watch?v=…",
                        disabled=True)
    st.button("Analyse video", disabled=True, type="primary")
    st.caption("Controls are disabled until the tool is implemented.")
    st.markdown("---")

    st.markdown("#### Planned, and how trustworthy each part is")

    st.markdown(
        "**✅ Stat snapshot (solid — reuses the engine).** Views, age-fair velocity, "
        "vs-channel-typical, like/comment rate *as diagnostics only*. Optionally place "
        "the video against its niche peers: \"3.2× the typical similar-age video in its "
        "niche\" via the same age-banded baseline the niche tool uses.")

    st.markdown(
        "**✅ Transcript + description (reliable for a single video).** Auto-captions "
        "exist for nearly all talking videos; a silent/music-only video just shows "
        "*\"No transcript available.\"* The description is fully official API data — "
        "often packed with creator-written chapter timestamps, hashtags, links and the "
        "hook line.")

    st.markdown(
        "**✅ AI-nominated Short clips — labelled honestly.** The AI reads the timestamped "
        "transcript and nominates 3–6 candidate clips with reasons and clickable "
        "`…&t=` links. Labelled clearly: *suggested from transcript content, not from "
        "audience-retention data* (\"most replayed\" is not in the API).")

    st.markdown(
        "**⚠ Advertiser-friendliness hints — NOT a copyright oracle.** We cannot run "
        "Content ID or detect copyrighted audio/video. What we *can* do is flag textual "
        "risk hints from the transcript (profanity density, named songs/artists, "
        "sensitive-topic keywords) as *hints to check*, never \"YouTube will flag this.\"")

    st.markdown(
        "**❌ Editing-style detection — out of scope.** Cut frequency / pacing / effects "
        "aren't in the API and detecting them means downloading the video (heavy, "
        "ToS-grey). Replaced with \"here are the winners in your lane — watch how they're "
        "cut,\" plus text-derivable patterns (opening hook, words-per-minute, "
        "question vs statement).")

    st.caption("Reliability principles (Expansion Plan §6) carry over verbatim: "
               "age-fair velocity, effective-n on any per-video claim, and heuristics "
               "labelled as suggestions-from-text, not measurements.")
