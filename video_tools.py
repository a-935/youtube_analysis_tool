"""
video_tools.py — engine for Tool 2 (Analyse a Specific Video)
=============================================================
Reuses the niche engine (yt_dashboard) for every stat so the velocity/age logic
is never forked (Plan §1, §3a). The honest constraints from the plan are baked in:
  - clips are nominated from TRANSCRIPT CONTENT, not audience-retention data (§3c)
  - "risk hints" are advertiser-friendliness HINTS from text, never a copyright
    oracle (§3d)
  - editing style isn't detected; we surface watchable winners + text patterns (§3e)

Split by verifiability:
  PURE (unit-tested): parse_video_id, mine_description, segments_to_text,
                      transcript_wpm, opening_hook, risk_hints, place_in_niche,
                      similar_winners, build_clip_prompt, build_comment_prompt
  LIVE (needs keys/network, graceful fallback): fetch_video, fetch_niche_peers,
                      fetch_transcript, nominate_clips, fetch_top_comments
"""

import re

import yt_dashboard as engine

# ----------------------------------------------------------------- URL / ID
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_id(url_or_id):
    """Accept a raw 11-char ID or any common YouTube URL form and return the ID.
    Returns None if nothing id-shaped is found."""
    s = (url_or_id or "").strip()
    if not s:
        return None
    if _ID_RE.match(s):
        return s
    # youtu.be/<id>, /watch?v=<id>, /shorts/<id>, /embed/<id>, /live/<id>
    m = re.search(r"(?:v=|/shorts/|/embed/|/live/|youtu\.be/)([A-Za-z0-9_-]{11})", s)
    if m:
        return m.group(1)
    # last resort: any 11-char token in the path
    m = re.search(r"([A-Za-z0-9_-]{11})", s)
    return m.group(1) if m else None


def _t_link(video_id, seconds):
    return f"https://www.youtube.com/watch?v={video_id}&t={int(seconds)}s"


# ----------------------------------------------------------------- description mining
_TS_RE = re.compile(r"^\s*\(?(\d{1,2}:\d{2}(?::\d{2})?)\)?\s*[-–—:]?\s*(.+?)\s*$")
_HASHTAG_RE = re.compile(r"#\w+")
_URL_RE = re.compile(r"https?://[^\s)>\]]+")
_SPONSOR_HINT = re.compile(
    r"\b(sponsor|sponsored|use code|promo code|discount code|affiliate|"
    r"thanks to|brought to you by|ad\b|#ad|paid partnership)\b", re.I)


def _ts_to_seconds(ts):
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def mine_description(text, video_id=None):
    """Pull the structured signal out of a description (fully official API data, §3b):
    creator chapter timestamps, hashtags, links, sponsor hints, and the hook line."""
    text = text or ""
    lines = [ln.rstrip() for ln in text.splitlines()]

    chapters = []
    for ln in lines:
        m = _TS_RE.match(ln)
        if not m:
            continue
        label = m.group(2).strip()
        if not label or _URL_RE.match(label):
            continue
        secs = _ts_to_seconds(m.group(1))
        ch = {"t": m.group(1), "seconds": secs, "label": label}
        if video_id:
            ch["url"] = _t_link(video_id, secs)
        chapters.append(ch)
    # a real chapter list is monotonic and starts at/near 0 — guard against false hits
    if chapters:
        starts_low = chapters[0]["seconds"] <= 5
        monotonic = all(chapters[i]["seconds"] <= chapters[i + 1]["seconds"]
                        for i in range(len(chapters) - 1))
        if not (starts_low and monotonic and len(chapters) >= 2):
            chapters = []   # not a genuine chapter list; drop rather than mislead

    hashtags = _HASHTAG_RE.findall(text)
    links = _URL_RE.findall(text)
    hook = next((ln.strip() for ln in lines if ln.strip()), "")
    return {
        "chapters": chapters,
        "hashtags": list(dict.fromkeys(hashtags)),
        "links": list(dict.fromkeys(links)),
        "sponsor_mentions": bool(_SPONSOR_HINT.search(text)),
        "hook_line": hook,
    }


# ----------------------------------------------------------------- transcript helpers
def segments_to_text(segments):
    """[{text, start, duration}, ...] -> one string."""
    return " ".join((s.get("text") or "").replace("\n", " ").strip()
                    for s in (segments or [])).strip()


def transcript_wpm(segments):
    """Words per minute over the transcript — a PACING PROXY, not a measure of
    editing (§3e). Honest label is applied in the UI."""
    if not segments:
        return None
    words = sum(len((s.get("text") or "").split()) for s in segments)
    last = segments[-1]
    end = (last.get("start") or 0) + (last.get("duration") or 0)
    minutes = end / 60.0
    if minutes <= 0:
        return None
    return round(words / minutes, 1)


def opening_hook(segments, seconds=10):
    """The transcript text from the first N seconds — the spoken hook (§3e)."""
    out = []
    for s in (segments or []):
        if (s.get("start") or 0) <= seconds:
            out.append((s.get("text") or "").strip())
        else:
            break
    return " ".join(out).strip()


# ----------------------------------------------------------------- risk hints (TEXT only)
# Advertiser-friendliness HINTS from transcript text. This is NOT Content ID and NOT
# a copyright/strike predictor (§3d). Common profanity only (for the yellow-icon hint);
# deliberately no slurs are enumerated here.
_PROFANITY = {"damn", "hell", "crap", "ass", "bitch", "shit", "fuck", "fucking",
              "bastard", "dick", "piss"}
_SENSITIVE = {"kill", "death", "blood", "gun", "shoot", "violence", "drug", "suicide",
              "war", "abuse"}
_MUSIC_HINT = re.compile(
    r"\b(official music video|feat\.|ft\.|remix|soundtrack|prod\.|"
    r"original song|lyrics|cover of)\b", re.I)


def risk_hints(text):
    """Returns labelled HINTS, never verdicts. The caller must present them as
    'things to check', not 'YouTube will flag this'."""
    text = text or ""
    words = re.findall(r"[A-Za-z']+", text.lower())
    n = len(words) or 1
    prof = sum(1 for w in words if w in _PROFANITY)
    sens = sorted({w for w in words if w in _SENSITIVE})
    prof_density = round(prof / n * 1000, 2)   # per 1000 words
    if prof == 0:
        ad_hint = "no profanity detected in transcript"
    elif prof_density < 1:
        ad_hint = "occasional profanity — usually fine, but check"
    else:
        ad_hint = "frequent profanity — may get limited ads (yellow icon); check"
    return {
        "profanity_count": prof,
        "profanity_per_1000_words": prof_density,
        "ad_friendliness_hint": ad_hint,
        "sensitive_keywords": sens,
        "music_reuse_hint": bool(_MUSIC_HINT.search(text)),
        "disclaimer": ("Hints from transcript TEXT only — not Content ID, not a "
                       "copyright/strike prediction. Verify in YouTube Studio."),
    }


# ----------------------------------------------------------------- niche placement (age-fair)
def place_in_niche(video, peers):
    """Where does this video sit vs similar-age peers in its niche? Reuses the engine's
    age-banded baseline so it's age-fair (Plan §6.1). 'peers' are enriched video dicts
    (same format as a dataset's videos). Returns a multiplier + the band used."""
    pool = [p for p in peers if p.get("id") != video.get("id")] + [video]
    band_median, bands, overall = engine._age_banded_baseline(pool)
    bm = band_median(video)
    vpd = video.get("views_per_day") or 0
    return {
        "views_per_day": vpd,
        "similar_age_median": round(bm) if bm else None,
        "vs_similar_age": round(vpd / bm, 2) if bm else None,
        "overall_median": round(overall) if overall else None,
        "n_peers": len(pool) - 1,
        "n_bands": len(bands),
    }


def similar_winners(peers, video, k=8):
    """The age-fair top videos in the same niche+format — 'watch how these are cut'
    (§3e). Reuses the engine's age-fair scoring so 'winner' isn't just 'youngest'."""
    same_format = [p for p in peers
                   if bool(p.get("is_short")) == bool(video.get("is_short"))
                   and p.get("id") != video.get("id")]
    scored = engine._age_fair_scores(same_format)
    scored.sort(key=lambda v: v.get("_pattern_score", 0), reverse=True)
    out = []
    for v in scored[:k]:
        out.append({
            "title": v.get("title"), "channel": v.get("channel"),
            "url": v.get("url", f"https://www.youtube.com/watch?v={v.get('id', '')}"),
            "views": v.get("views"), "duration_sec": v.get("duration_sec"),
            "age_fair_score": round(v.get("_pattern_score", 0), 2),
            "is_question": "?" in (v.get("title") or ""),
        })
    return out


# ----------------------------------------------------------------- AI prompts
def build_clip_prompt(video_meta, segments):
    """Prompt to nominate Short-worthy clips from transcript content. The honesty label
    is part of the instruction so the model never claims retention data (§3c)."""
    lines = []
    for s in (segments or []):
        start = int(s.get("start") or 0)
        mm, ss = divmod(start, 60)
        lines.append(f"[{mm:02d}:{ss:02d}] {(s.get('text') or '').strip()}")
    body = "\n".join(lines)[:12000]   # keep prompt bounded
    title = video_meta.get("title", "(unknown)")
    return f"""You are a short-form editor. Below is the TIMESTAMPED TRANSCRIPT of a \
YouTube video titled "{title}". Nominate 3-6 candidate moments that could become Shorts.

You do NOT have audience-retention or "most replayed" data — judge ONLY from the content \
(a strong hook, a payoff, a funny or surprising beat, a self-contained moment).

Transcript:
{body}

Respond in markdown, one bullet per clip, each as:
- **start–end (mm:ss)** — one line why it works; suggested Short title; "self-contained" \
or "needs setup".
Begin every response by stating these are suggested from transcript content, not from \
audience-retention data."""


def build_comment_prompt(comments, title="(unknown)"):
    joined = "\n".join(f"- {c}" for c in (comments or [])[:80])[:8000]
    return f"""Below are top comments on the YouTube video "{title}". Cluster them into \
themes: what landed, what people disliked, and what they're asking for next. Do not invent \
comments; summarise only what's here.

{joined}

Respond in markdown: ## What landed, ## What missed, ## What they want next."""


# ----------------------------------------------------------------- LIVE calls (graceful)
def fetch_video(video_id):
    """One video's enriched stats. LIVE (YouTube API). Returns enriched dict or raises."""
    vids = engine.get_videos_details([video_id])
    if not vids:
        return None
    subs = engine.get_channel_subs([vids[0]["channel_id"]])
    engine.enrich(vids, subs)
    v = vids[0]
    # get_videos_details doesn't copy the description/tags — grab them (1 cheap unit)
    try:
        data = engine._get("videos", {"part": "snippet", "id": video_id})
        items = data.get("items", [])
        if items:
            v["description"] = items[0]["snippet"].get("description", "")
            v["tags"] = items[0]["snippet"].get("tags", [])
    except Exception:
        v.setdefault("description", "")
    return v


def fetch_niche_peers(keyword, per_format=50, region_label="All regions"):
    """Recent niche peers for placement/similar-winners. LIVE. Reuses fetch_dataset so
    caching + age handling are identical to Tool 1."""
    ds = engine.fetch_dataset(keyword, balanced=True, videos_per_format=per_format,
                              region_label=region_label)
    return ds["videos"], ds.get("cost", 0), ds.get("from_cache", False)


def fetch_transcript(video_id, db_path=None):
    """LIVE + cached. Tries the cache, then youtube-transcript-api. ALWAYS returns a
    dict; a silent/blocked/missing transcript yields available=False with a reason
    (Plan §3b: 'No transcript available.' — done, move on)."""
    import storage
    cached = storage.get_cached_transcript(video_id,
                                           **({"db_path": db_path} if db_path else {}))
    if cached:
        return cached

    result = {"video_id": video_id, "available": False, "lang": None,
              "text": "", "segments": [], "reason": ""}
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        result["reason"] = ("transcript library not installed — run "
                            "`pip install youtube-transcript-api`")
        return result   # not cached: it's an environment issue, not a video fact

    try:
        # support both old (.get_transcript) and new (.fetch) library APIs
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            raw = YouTubeTranscriptApi.get_transcript(video_id)
            segments = [{"text": r.get("text", ""), "start": r.get("start", 0),
                         "duration": r.get("duration", 0)} for r in raw]
        else:
            fetched = YouTubeTranscriptApi().fetch(video_id)
            segments = [{"text": s.text, "start": s.start, "duration": s.duration}
                        for s in fetched]
        result.update(available=True, segments=segments,
                      text=segments_to_text(segments))
    except Exception as e:
        result["reason"] = f"No transcript available ({type(e).__name__})."

    storage.cache_transcript(video_id, result["available"], result.get("lang"),
                             result.get("text", ""), result.get("segments", []),
                             **({"db_path": db_path} if db_path else {}))
    return result


def nominate_clips(video_meta, segments):
    """LIVE (Claude). Returns {text, cost_usd} or {error}."""
    if not segments:
        return {"error": "No transcript — cannot nominate clips."}
    prompt = build_clip_prompt(video_meta, segments)
    try:
        res = engine._call_claude(prompt, max_tokens=1200)
        return {"text": res["text"], "cost_usd": res["cost_usd"]}
    except Exception as e:
        return {"error": str(e)}


def fetch_top_comments(video_id, limit=80, db_path=None):
    """LIVE (YouTube API) + cached. Returns list of comment strings (graceful: [] if
    comments are disabled)."""
    import storage
    cached = storage.get_cached_comments(video_id,
                                         **({"db_path": db_path} if db_path else {}))
    if cached is not None:
        return cached
    out = []
    try:
        data = engine._get("commentThreads",
                           {"part": "snippet", "videoId": video_id,
                            "maxResults": min(limit, 100), "order": "relevance"})
        for item in data.get("items", []):
            sn = item["snippet"]["topLevelComment"]["snippet"]
            out.append(sn.get("textOriginal", ""))
    except Exception:
        out = []   # comments disabled or unavailable
    storage.cache_comments(video_id, out, **({"db_path": db_path} if db_path else {}))
    return out
