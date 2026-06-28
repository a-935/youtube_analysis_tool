"""
YouTube Niche Research DASHBOARD — Modular Engine
=================================================
A check-mark menu of analysis tools. You pick a topic, a date range, channel-size
tiers, and which tools to run. Each tool is SELF-CONTAINED and returns the same
shape: {name, cost, summary, result}. That uniform shape is what lets the future
Streamlit menu display any tool the same way, and lets you combine tools freely.

CORE RULES (by design):
- Shorts and long-form are ALWAYS analyzed separately, with their own ranges.
- Fetching costs YouTube quota; analysis tools that read already-fetched data
  cost 0. A live cost meter subtracts from your daily wallet.
- Fetched data is CACHED, so re-running the same search costs nothing.
- AI tools spend a SEPARATE wallet (your Claude credit), shown apart from quota.

LAYERS:
  1. ENGINE      — fetch + enrich + cache (costs quota)
  2. HELPERS     — small shared math used by tools
  3. TOOLS       — each returns {name, cost, summary, result}
  4. REGISTRY    — the menu: maps tool keys -> functions + labels
  5. RUNNER      — runs the checked tools, prints blocks, updates the wallet
"""

import os
import re
import json
import statistics
from collections import Counter
from datetime import datetime, timezone, timedelta

import requests

BASE = "https://www.googleapis.com/youtube/v3"
SHORTS_MAX_SECONDS = 180        # <= 3 min counts as a Short (heuristic)
CACHE_FILE = "yt_cache.json"

# Videos under this many TOTAL views are kept OUT of the niche-median baseline (they're
# still scored and shown). Abandoned livestream VODs with a handful of views otherwise
# drag the long-form median to absurd lows and inflate every "x niche median". Tune here.
BASELINE_MIN_VIEWS = 500

# Channel-size tiers (subscriber thresholds — adjustable)
TIERS = {"small": (0, 100_000), "medium": (100_000, 1_000_000), "large": (1_000_000, 10**12)}

# Wallets. Quota resets daily (free). Claude credit is real money.
WALLET = {"quota": 10_000, "claude_usd": 5.00}

# Region / language presets for the search. Each maps to YouTube search params:
#   regionCode = ISO country (affects availability), relevanceLanguage = ISO language
#   (biases results toward that language). "All regions" = no filter (worldwide).
# This lets an English creator stop having their RL data diluted by Spanish/French/etc.
REGIONS = {
    "All regions": None,
    "English (US)": {"regionCode": "US", "relevanceLanguage": "en"},
    "English (UK)": {"regionCode": "GB", "relevanceLanguage": "en"},
    "Spanish": {"relevanceLanguage": "es"},
    "Portuguese (Brazil)": {"regionCode": "BR", "relevanceLanguage": "pt"},
    "French": {"relevanceLanguage": "fr"},
    "German": {"relevanceLanguage": "de"},
    "Arabic": {"relevanceLanguage": "ar"},
    "Japanese": {"regionCode": "JP", "relevanceLanguage": "ja"},
    "Korean": {"regionCode": "KR", "relevanceLanguage": "ko"},
}

# --- Claude (AI summary) config ---
CLAUDE_MODEL = "claude-haiku-4-5-20251001"   # cheapest; swap to claude-sonnet-4-6 for deeper analysis
# ROUGH price estimate in USD per MILLION tokens. VERIFY at anthropic.com/pricing
# and adjust — this only affects the on-screen cost estimate, not real billing.
CLAUDE_PRICE = {"input_per_mtok": 1.00, "output_per_mtok": 5.00}


# ======================================================================
# 1. ENGINE
# ======================================================================
def get_api_key():
    """The ONLY place that knows where the YouTube key comes from."""
    try:
        from google.colab import userdata
        return userdata.get("YT_KEY")
    except Exception:
        pass
    key = os.environ.get("YT_KEY")
    if key:
        return key
    raise RuntimeError("No API key found. Set 'YT_KEY' in Colab Secrets or env var.")


def _get(endpoint, params):
    params["key"] = get_api_key()
    r = requests.get(f"{BASE}/{endpoint}", params=params)
    r.raise_for_status()
    return r.json()


# ---- caching -----------------------------------------------------------
def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


# ---- small parsers -----------------------------------------------------
def parse_duration(iso):
    """'PT8M30S' -> seconds."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mn, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mn * 60 + s


# ---- fetching ----------------------------------------------------------
def search_ids(keyword, max_results=50, after=None, before=None,
               order="viewCount", video_duration=None, pages=1, region=None):
    """
    YouTube search. Returns video IDs. COSTS 100 UNITS PER PAGE.
    pages=1 -> up to 50 IDs (100 units). pages=2 -> up to 100 IDs (200 units), etc.
    'region' is an optional dict of extra search params (regionCode and/or
    relevanceLanguage) to bias results toward a country/language. None = worldwide.
    """
    base = {"part": "id", "q": keyword, "type": "video",
            "order": order, "maxResults": 50}
    if after:
        base["publishedAfter"] = f"{after}T00:00:00Z"
    if before:
        base["publishedBefore"] = f"{before}T00:00:00Z"
    if video_duration:
        base["videoDuration"] = video_duration
    if region:
        base.update(region)        # regionCode / relevanceLanguage
    ids, token = [], None
    for _ in range(max(1, pages)):
        params = dict(base)
        if token:
            params["pageToken"] = token
        data = _get("search", params)
        ids += [i["id"]["videoId"] for i in data.get("items", [])]
        token = data.get("nextPageToken")
        if not token:
            break
    return ids


def get_videos_details(video_ids):
    """Rich stats per video (1 unit / 50)."""
    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        data = _get("videos", {"part": "snippet,statistics,contentDetails",
                               "id": ",".join(batch)})
        for item in data["items"]:
            st = item["statistics"]
            dur = parse_duration(item["contentDetails"]["duration"])
            videos.append({
                "id": item["id"],
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "channel_id": item["snippet"]["channelId"],
                "published": item["snippet"]["publishedAt"],
                "thumbnail": item["snippet"]["thumbnails"]["high"]["url"],
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
                "duration_sec": dur,
                "is_short": 0 < dur <= SHORTS_MAX_SECONDS,
            })
    return videos


def get_channel_subs(channel_ids):
    """channel_id -> subscriber count (1 unit / 50)."""
    subs = {}
    for i in range(0, len(set(channel_ids)), 50):
        batch = list(set(channel_ids))[i:i + 50]
        data = _get("channels", {"part": "statistics", "id": ",".join(batch)})
        for item in data["items"]:
            subs[item["id"]] = int(item["statistics"].get("subscriberCount", 0))
    return subs


def enrich(videos, subs_map=None):
    """Add the derived 'smart' numbers to every video."""
    now = datetime.now(timezone.utc)
    for v in videos:
        pub = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
        age = max((now - pub).days, 1)
        v["age_days"] = age
        v["views_per_day"] = round(v["views"] / age, 1)
        v["like_rate"] = round(v["likes"] / v["views"], 4) if v["views"] else 0
        v["comment_rate"] = round(v["comments"] / v["views"], 5) if v["views"] else 0
        wd = pub.weekday()       # 0 = Monday
        v["weekday"] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd]
        v["hour"] = pub.hour
        if subs_map is not None:
            v["subs"] = subs_map.get(v["channel_id"], 0)
            v["views_per_sub"] = round(v["views"] / v["subs"], 2) if v.get("subs") else 0
    return videos


def refresh_ages(videos):
    """Recompute the time-dependent fields (age_days, views_per_day) from each video's
    'published' timestamp using the CURRENT time.

    Why: age_days is otherwise FROZEN at fetch time and cached. A cached run viewed a day
    later understates every velocity — worst for 1-2 day old videos, where one extra day
    is most of the denominator (a 1-day-old video read as still 1 day old overstates its
    views/day by ~2x once it's actually 2 days old). All other derived fields (like_rate,
    comment_rate, weekday, subs) are time-invariant, so we leave them untouched."""
    now = datetime.now(timezone.utc)
    for v in videos:
        try:
            pub = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
        except Exception:
            continue                       # leave the stored values if the date is junk
        age = max((now - pub).days, 1)
        v["age_days"] = age
        v["views_per_day"] = round(v["views"] / age, 1)
    return videos


def fetch_dataset(topic, after=None, before=None, max_results=50,
                  balanced=True, max_age_days=None, use_cache=True,
                  videos_per_format=50, region_label="All regions"):
    """
    Orchestrates a full fetch and returns a Dataset:
      {topic, videos, cost, from_cache}
    'balanced' fetches Shorts AND long-form separately (2 searches).
    'videos_per_format' = how many videos to pull per format. Each 50 is one
    search PAGE = 100 units. So 100 videos/format balanced = 4 pages = 400 units.
    'region_label' picks a REGIONS preset to bias results to a country/language.
    Results are cached so an identical call later costs 0.
    """
    region = REGIONS.get(region_label)
    pages = max(1, (videos_per_format + 49) // 50)

    # KEY FIX: 'max_age_days' now drives the SEARCH window, not just a post-filter.
    # Before, the search used the (often months-old) 'From' date and order=viewCount,
    # so it pulled the all-time top videos since 'From' and then threw away everything
    # older than max_age_days — wasting quota and leaving a tiny sample. Now we move
    # publishedAfter up to (today - max_age_days) when that's more recent than 'From',
    # so the API returns recent videos directly. We keep the post-filter as a safety net.
    search_after = after
    if max_age_days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
        if search_after is None or cutoff > search_after:
            search_after = cutoff

    cache = _load_cache()
    # region_label + the effective search window are part of the key so different
    # regions/windows cache separately (and a new day re-fetches when max_age is set).
    key = json.dumps(["v5", topic, search_after, before, balanced, max_age_days, pages,
                      region_label])
    requested_per_format = pages * 50
    window = {"after": search_after, "before": before, "region": region_label}

    if use_cache and key in cache:
        vids = cache[key]
        refresh_ages(vids)        # cached ages are frozen at fetch time — recompute to "now"
        return {"topic": topic, "videos": vids, "cost": 0, "from_cache": True,
                "meta": _fetch_meta(vids, requested_per_format, balanced, window, 0)}

    cost = 0
    if balanced:
        ids = search_ids(topic, after=search_after, before=before,
                         video_duration="short", pages=pages, region=region)
        ids += search_ids(topic, after=search_after, before=before,
                          video_duration="medium", pages=pages, region=region)
        ids = list(dict.fromkeys(ids))
        cost += 100 * pages * 2
    else:
        ids = search_ids(topic, after=search_after, before=before, pages=pages, region=region)
        cost += 100 * pages

    videos = get_videos_details(ids)
    subs_map = get_channel_subs([v["channel_id"] for v in videos])
    cost += len(range(0, len(ids), 50)) + 1  # cheap detail + subs calls
    enrich(videos, subs_map)

    if max_age_days:
        videos = [v for v in videos if v["age_days"] <= max_age_days]

    cache[key] = videos
    _save_cache(cache)
    return {"topic": topic, "videos": videos, "cost": cost, "from_cache": False,
            "meta": _fetch_meta(videos, requested_per_format, balanced, window, cost)}


def _fetch_meta(videos, requested_per_format, balanced, window, cost):
    """Lightweight fetch diagnostics so the AI audit can see how much of what we
    requested actually came back (and flag a too-narrow window / tiny niche)."""
    ns = sum(v["is_short"] for v in videos)
    requested_total = requested_per_format * (2 if balanced else 1)
    returned = len(videos)
    fill = round(returned / requested_total, 2) if requested_total else 0
    return {"requested_per_format": requested_per_format,
            "requested_total": requested_total,
            "returned_total": returned, "returned_shorts": ns,
            "returned_long": returned - ns, "fill_ratio": fill,
            "quota_cost": cost, "window": window}


def fetch_channel_stats(dataset):
    """
    OPTIONAL extra fetch. For each unique channel in the dataset, pull its recent
    uploads to compute average views and upload cadence, then attach to each video:
      channel_avg_views, channel_uploads_per_month, channel_views_per_month
    Cost ~2 units per unique channel. Cached.
    """
    cache = _load_cache()
    videos = dataset["videos"]
    channels = list({v["channel_id"] for v in videos})
    cost = 0
    stats = {}
    for cid in channels:
        ck = f"chanstats::{cid}"
        if ck in cache:
            stats[cid] = cache[ck]
            continue
        try:
            ch = _get("channels", {"part": "contentDetails", "id": cid})["items"][0]
            uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
            pl = _get("playlistItems", {"part": "contentDetails",
                                        "playlistId": uploads, "maxResults": 50})
            vids = [i["contentDetails"]["videoId"] for i in pl["items"]]
            details = get_videos_details(vids)
            cost += 3
            views = [d["views"] for d in details if d["views"] > 0]
            # median, not mean: a channel's own viral hit drags the mean up and makes
            # every other video look like an "underperformer" (same lesson as bugs #4/#5,
            # which never reached this function).
            avg_views = statistics.median(views) if views else 0
            # cadence: spread of publish dates -> uploads & views per month
            dates = sorted(datetime.fromisoformat(d["published"].replace("Z", "+00:00"))
                           for d in details)
            span_days = max((dates[-1] - dates[0]).days, 1) if len(dates) > 1 else 30
            months = max(span_days / 30, 1)
            stats[cid] = {
                "channel_avg_views": round(avg_views),
                "channel_uploads_per_month": round(len(details) / months, 1),
                "channel_views_per_month": round(sum(d["views"] for d in details) / months),
            }
        except Exception:
            stats[cid] = {"channel_avg_views": 0, "channel_uploads_per_month": 0,
                          "channel_views_per_month": 0}
        cache[ck] = stats[cid]
    _save_cache(cache)
    for v in videos:
        v.update(stats.get(v["channel_id"], {}))
    dataset["channel_stats_cost"] = cost
    return cost


# ======================================================================
# 2. HELPERS (shared by tools)
# ======================================================================
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\u2190-\u21FF\u2B00-\u2BFF\u2700-\u27BF]")


def by_format(videos):
    return ([v for v in videos if v["is_short"]],
            [v for v in videos if not v["is_short"]])


def by_tier(videos, tier):
    lo, hi = TIERS[tier]
    return [v for v in videos if lo <= v.get("subs", 0) < hi]


def exclude_official(videos, topic):
    """
    Drop channels that look like the game's OWN official/brand channel — e.g. the
    'Call of Duty' channel when searching 'call of duty'. Their trailers crush the
    baseline and aren't creator content you can learn from.
    """
    t = topic.lower().strip()
    kept = []
    for v in videos:
        name = v["channel"].lower()
        # official if the channel name is basically the topic itself
        if name == t or name.replace(" ", "") == t.replace(" ", ""):
            continue
        kept.append(v)
    return kept


def per_format(videos, fn):
    """Run an analysis fn on Shorts and long-form separately."""
    shorts, longform = by_format(videos)
    return {"shorts": fn(shorts), "long": fn(longform)}


def _age_fair_scores(videos):
    """Attach v['_pattern_score'] = each video's velocity ÷ its OWN age band's median
    velocity, reusing the exact age-banding from the outliers tool. This is what makes
    'fastest third vs slowest third' age-fair everywhere — without it, top_bottom ranks by
    raw views/day and 'fast' silently means 'young' (a 2-day video almost always outranks a
    60-day one regardless of quality). Returns the videos that have a usable score."""
    band_median, _bands, _overall = _age_banded_baseline(videos)
    scored = []
    for v in videos:
        bm = band_median(v)
        if bm and v.get("views_per_day", 0) > 0:
            v["_pattern_score"] = v["views_per_day"] / bm
            scored.append(v)
        else:
            v["_pattern_score"] = 0
    return scored


def top_bottom(videos, metric="_pattern_score", frac=0.33):
    """Split a group into its fastest and slowest slice.

    By default we rank by '_pattern_score' — velocity relative to the video's OWN age band
    (see _age_fair_scores) — NOT raw views/day. This stops the fast/slow split from being a
    young/old split, which used to contaminate every pattern tool (duration, emoji, etc.):
    fresh videos sit at peak velocity and would always land in 'fast'. Pass
    metric='views_per_day' to force the old raw behaviour."""
    if metric == "_pattern_score":
        ranked = sorted(_age_fair_scores(videos),
                        key=lambda v: v["_pattern_score"], reverse=True)
    else:
        ranked = sorted([v for v in videos if v.get(metric, 0) > 0],
                        key=lambda v: v[metric], reverse=True)
    if len(ranked) < 4:
        return ranked, ranked       # too few to split meaningfully
    n = max(1, int(len(ranked) * frac))
    return ranked[:n], ranked[-n:]


def _frac(videos, pred):
    return sum(1 for v in videos if pred(v)) / len(videos) if videos else 0


def _med(videos, fn):
    vals = [fn(v) for v in videos if fn(v) is not None]
    return statistics.median(vals) if vals else 0


def channel_clustering(videos):
    """How independent is this sample, really? The pattern tools treat every video as an
    independent data point, but they cluster hard in a few prolific channels (one channel
    can supply 20% of a search). Returns distinct channels, the top-5 share, and the Kish
    effective sample size (Σnᵢ)²/Σnᵢ² — the number of *truly independent* observations the
    data is worth. n=244 from a handful of channels can be worth an effective ~14."""
    if not videos:
        return {"videos": 0, "channels": 0, "top5_share": 0, "effective_n": 0}
    counts = Counter(v["channel"] for v in videos)
    sizes = list(counts.values())
    total = sum(sizes)
    top5 = sum(c for _, c in counts.most_common(5))
    eff = (total ** 2) / sum(s * s for s in sizes) if sizes else 0
    return {"videos": total, "channels": len(counts),
            "top5_share": round(top5 / total, 2) if total else 0,
            "effective_n": round(eff, 1),
            "top_channels": counts.most_common(5)}


def has_emoji(text):
    return bool(EMOJI_RE.search(text))


def linkable_titles(obj):
    """
    Recursively find every video (any dict carrying both 'title' and 'url')
    anywhere inside a tool's result. This is the ONE function the GUI uses to
    render clickable titles — so EVERY title shown by ANY tool becomes a link
    automatically, with no per-tool work. Returns list of (title, url, views).
    """
    found = []
    if isinstance(obj, dict):
        if "title" in obj and "url" in obj:
            found.append((obj["title"], obj["url"], obj.get("views")))
        for val in obj.values():
            found += linkable_titles(val)
    elif isinstance(obj, list):
        for item in obj:
            found += linkable_titles(item)
    return found


def caps_words(text):
    return sum(1 for w in text.split() if len(w) >= 2 and w.isupper())


def detect_script(text):
    for ch in text:
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF:
            return "Arabic"
        if 0x0400 <= o <= 0x04FF:
            return "Cyrillic"
        if 0x3040 <= o <= 0x30FF:
            return "Japanese"
        if 0x4E00 <= o <= 0x9FFF:
            return "CJK"
    return "Latin"


# ======================================================================
# 3. TOOLS  — each returns {name, cost, summary, result}
#    Every tool reports Shorts and long-form separately.
# ======================================================================
def _verdict(top, bottom, min_base=1):
    """Plain-English read of a top-vs-bottom comparison, honest about ties.

    'min_base' floors the denominator to stop a divide-by-near-zero from turning a
    meaningless wobble into a "signal". The default of 1 is right for proportion metrics
    (emoji/question/numbers live on 0-1, so a 14-point gap genuinely IS small) and for
    metrics whose values exceed 1 anyway (like-rate %). But comment-rate lives at ~0.02-
    0.05%, so a floor of 1 swallows it whole and it ALWAYS reads "no clear difference" even
    when slow videos clearly draw 2-3x the comments per view (the same reach artifact as
    like-rate). Such metrics pass a smaller min_base so their real range isn't erased."""
    base = max(abs(top), abs(bottom), min_base)
    if abs(top - bottom) / base < 0.15:
        return "no clear difference"
    return "winners higher" if top > bottom else "winners lower"


def _vid_card(v, baseline=None):
    """A compact, link-ready dict for one video, with context numbers attached.
    Also carries the RAW numbers behind each multiplier (niche baseline, channel
    median, channel name) so the GUI can reveal them on hover."""
    card = {
        "title": v["title"], "url": v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
        "views": v["views"], "views_per_day": v.get("views_per_day"),
        "age_days": v.get("age_days"), "channel": v.get("channel"),
        "published": v.get("published"),
    }
    if baseline:
        card["baseline"] = round(baseline)
        card["vs_baseline"] = round(v.get("views_per_day", 0) / baseline, 2) if baseline else None
    avg = v.get("channel_avg_views")
    if avg:
        card["channel_avg_views"] = round(avg)
        card["vs_channel_avg"] = round(v["views"] / avg, 2) if avg else None
    return card


def _age_banded_baseline(vids):
    """The age-fairness fix for velocity.

    views/day = total_views / age_days ASSUMES a video gathers views at a constant rate.
    It doesn't — YouTube views are heavily front-loaded, then decay. So an OLD video's
    lifetime-average velocity sits far below the speed it actually had when fresh, while a
    1-day-old video is measured at its peak. Pooling every age into one niche median
    therefore does two bad things at once: decayed old videos DEFLATE the median, and
    fresh videos look INFLATED against it (that's why a 36k-view fresh video could read
    '43x' while an 800k-view older video read '23x').

    Fix: compare each video only to videos of SIMILAR AGE. The front-loading bias is
    roughly shared within an age band, so it cancels — a 40-day video that's 3x the
    typical 40-day video really is 3x faster than its peers.

    Returns (band_median_fn, bands, overall_median):
      band_median_fn(video) -> the median velocity of the video's age band
      bands -> list of {min_age, max_age, median, n} for display
      overall_median -> the old single niche median (kept for the headline only)
    Bands are equal-COUNT slices of the age-sorted pool (so none is ever too thin), and we
    use 1 band per ~40 videos (max 5). Below ~40 videos it degrades to a single band,
    i.e. the original whole-niche median — so small samples behave exactly as before.
    """
    pool = [v for v in vids
            if v.get("views_per_day", 0) > 0 and v["views"] >= BASELINE_MIN_VIEWS]
    if not pool:
        pool = [v for v in vids if v.get("views_per_day", 0) > 0]
    if not pool:
        return (lambda v: 0), [], 0

    overall = statistics.median(v["views_per_day"] for v in pool)
    pool.sort(key=lambda v: v.get("age_days", 1))
    n_bands = max(1, min(5, len(pool) // 40))
    step = len(pool) / n_bands
    bands = []
    for i in range(n_bands):
        chunk = pool[round(i * step):round((i + 1) * step)]
        if not chunk:
            continue
        bands.append({"min_age": chunk[0].get("age_days", 1),
                      "max_age": chunk[-1].get("age_days", 1),
                      "median": statistics.median(v["views_per_day"] for v in chunk),
                      "n": len(chunk)})

    def band_median(v):
        age = v.get("age_days", 1)
        for b in bands:
            if age <= b["max_age"]:
                return b["median"]
        return bands[-1]["median"] if bands else overall

    return band_median, bands, overall


def tool_outliers(ds):
    """
    Ranks videos by views-per-day (velocity) against each FORMAT's own median.
    Labels are descriptive ('fastest'/'slowest in batch'), NOT judgmental — a
    low-velocity video may still beat its own channel, which we show too.
    """
    def grp(vids):
        # Age-fair baseline: each video is scored against the median velocity of videos
        # of SIMILAR AGE, not one whole-niche median (see _age_banded_baseline). The
        # min-views floor still applies inside it so near-dead VODs don't pollute any band.
        band_median, bands, overall = _age_banded_baseline(vids)
        for v in vids:
            bm = band_median(v)
            v["score"] = round(v["views_per_day"] / bm, 2) if bm else 0
            v["_band_baseline"] = round(bm) if bm else 0
        fast = sorted([v for v in vids if v["score"] >= 2], key=lambda v: -v["score"])
        slow = sorted([v for v in vids if 0 < v["score"] <= 0.5], key=lambda v: v["score"])
        return {"baseline": round(overall), "n": len(vids),
                "n_bands": len(bands), "bands": bands,
                "fastest": [_vid_card(v, v["_band_baseline"]) for v in fast],
                "slowest": [_vid_card(v, v["_band_baseline"]) for v in slow]}
    res = per_format(ds["videos"], grp)
    s, l = res["shorts"], res["long"]
    summary = (f"Each video vs the typical video of similar age (fair to old & new). "
               f"Shorts ~{s['baseline']:,}/day · {len(s['fastest'])} fast, {len(s['slowest'])} slow.  "
               f"Long ~{l['baseline']:,}/day · {len(l['fastest'])} fast, {len(l['slowest'])} slow.")
    return {"name": "Velocity outliers (views/day vs similar-age median)", "cost": 0,
            "summary": summary, "result": res}


def _presence_tool(name, pred):
    """Factory: how often a title trait appears in fastest vs slowest videos."""
    def tool(ds):
        def grp(vids):
            top, bot = top_bottom(vids)
            def items(vs):
                return [{"title": v["title"], "channel": v.get("channel"),
                         "url": v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
                         "published": v.get("published"),
                         "views": v["views"], "value": "yes" if pred(v) else "no"}
                        for v in vs]
            return {"top": _frac(top, pred), "bottom": _frac(bot, pred),
                    "top_n": len(top), "bottom_n": len(bot),
                    "top_items": items(top), "bottom_items": items(bot)}
        res = per_format(ds["videos"], grp)
        s = res["shorts"]
        verdict = _verdict(s["top"], s["bottom"])
        summary = (f"Shorts: {verdict} — {s['top']:.0%} of fastest vs "
                   f"{s['bottom']:.0%} of slowest "
                   f"(based on {s['top_n']}+{s['bottom_n']} videos)")
        return {"name": name, "cost": 0, "summary": summary, "result": res}
    return tool


def _numeric_tool(name, fn, unit="", decimals=1, min_base=1, caveat="", diagnostic=False):
    """Factory: median of a numeric trait in fastest vs slowest, with per-video values.
    'decimals' controls display precision — comment-rate needs more than 1 dp or it
    rounds to a useless 0.0% for every video.
    'min_base' is passed to _verdict; metrics with a tiny natural range (comment-rate)
    pass a small value so the verdict can actually see their differences.
    'caveat' is appended to the summary header for signals that are real but weak/
    format-dependent, so the warning shows in the collapsed UI (not buried).
    'diagnostic' marks reach artifacts (like/comment rate): we still SHOW the numbers but
    drop the 'winners higher/lower' verdict, because it isn't a craft signal to optimise —
    it tracks reach, and (comment-rate) even flips sign by format."""
    def tool(ds):
        def grp(vids):
            top, bot = top_bottom(vids)
            def items(vs):
                return [{"title": v["title"], "channel": v.get("channel"),
                         "url": v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
                         "published": v.get("published"),
                         "views": v["views"], "value": round(fn(v), decimals)}
                        for v in vs]
            return {"top": _med(top, fn), "bottom": _med(bot, fn),
                    "top_n": len(top), "bottom_n": len(bot),
                    "top_items": items(top), "bottom_items": items(bot)}
        res = per_format(ds["videos"], grp)
        s = res["shorts"]
        if diagnostic:
            summary = (f"Diagnostic only (reach artifact — tracks reach, not craft; "
                       f"don't optimise for it): fastest {s['top']:.{decimals}f}{unit} vs "
                       f"slowest {s['bottom']:.{decimals}f}{unit}")
        else:
            verdict = _verdict(s["top"], s["bottom"], min_base=min_base)
            summary = (f"Shorts: {verdict} — fastest {s['top']:.{decimals}f}{unit} vs "
                       f"slowest {s['bottom']:.{decimals}f}{unit} "
                       f"(based on {s['top_n']}+{s['bottom_n']} videos)")
        if caveat:
            summary += f" — {caveat}"
        return {"name": name, "cost": 0, "summary": summary, "result": res}
    return tool


# words that are never an interesting "hook" (pure glue) — plus the topic itself,
# stripped per-search so we don't "discover" that meccha-chameleon videos open with
# the word "meccha".
_HOOK_STOP = {"the", "a", "an", "is", "of", "to", "in", "on", "my", "with", "for"}


def tool_title_hook(ds):
    """Most common MEANINGFUL opening word among top performers (topic + glue words
    skipped, so the opener is actually informative rather than just the search term)."""
    topic_words = set(re.findall(r"\w+", ds.get("topic", "").lower()))
    skip = topic_words | _HOOK_STOP

    def first_real_word(title):
        for raw in title.lower().split():
            w = re.sub(r"[^\w']", "", raw)        # strip punctuation/emoji/hashes
            if w and w not in skip:
                return w
        return None

    def grp(vids):
        top, _ = top_bottom(vids)
        firsts = [w for w in (first_real_word(v["title"]) for v in top) if w]
        return {"common_openers": Counter(firsts).most_common(5),
                "top_videos": top, "n": len(top), "counted": len(firsts)}
    res = per_format(ds["videos"], grp)
    s = res["shorts"]["common_openers"][:3]
    summary = ("Top Shorts often open with: " + ", ".join(f"'{w}'" for w, _ in s)
               if s else "No clear opening-word pattern")
    return {"name": "Title hook (opening words)", "cost": 0,
            "summary": summary, "result": res}


def tool_upload_timing(ds):
    """Which weekday the top performers tend to post on."""
    def grp(vids):
        top, _ = top_bottom(vids)
        days = Counter(v["weekday"] for v in top)
        return {"by_weekday": days.most_common(), "top_videos": top, "n": len(top)}
    res = per_format(ds["videos"], grp)
    best = res["shorts"]["by_weekday"][0][0] if res["shorts"]["by_weekday"] else "?"
    summary = f"Top Shorts most often posted on {best}"
    return {"name": "Upload timing", "cost": 0, "summary": summary, "result": res}


def _is_auto_channel(name):
    """YouTube auto-generates '... - Topic' channels for music/art-tracks. They aren't
    creators you can learn from, and their tiny sub counts blow up any views/subs ratio."""
    return str(name).strip().endswith("- Topic")


def tool_small_breakouts(ds):
    """Videos that massively beat their channel's subscriber count — a sign the IDEA
    carried, not the existing audience. We drop auto-generated '- Topic' channels (not
    real creators) and flag tiny-sub denominators, since views÷subs explodes mechanically
    when subs are in the hundreds."""
    def grp(vids):
        ranked = sorted([v for v in vids
                         if v.get("views_per_sub", 0) > 0 and not _is_auto_channel(v.get("channel"))],
                        key=lambda v: -v["views_per_sub"])
        for v in ranked:
            v["small_denominator"] = v.get("subs", 0) < 1000
        return {"top": ranked[:8], "n": len(vids)}
    res = per_format(ds["videos"], grp)
    top = res["shorts"]["top"]
    if top:
        flag = " ⚠ tiny sub count — ratio is inflated" if top[0].get("small_denominator") else ""
        lead = f"{top[0]['views_per_sub']}x subs{flag}"
    else:
        lead = "n/a"
    summary = f"Best small-channel Short breakout: {lead}"
    return {"name": "Small-channel breakouts", "cost": 0,
            "summary": summary, "result": res}


def tool_saturation(ds):
    """How crowded the niche is: channel concentration + how independent the sample is.

    Concentration (distinct channels, top-5 share) is reported on the whole result set.
    But the effective independent sample is reported PER FORMAT, because the pattern tools
    run per format — and a channel that posts one Short and one Long would otherwise be
    double-counted as two independent voices, inflating the pooled figure ~2x. This keeps
    the visible number aligned with the per-format figure the AI reasons from."""
    vids = ds["videos"]
    chans = Counter(v["channel"] for v in vids)
    distinct = len(chans)
    top_share = chans.most_common(1)[0][1] / len(vids) if vids else 0
    pooled = channel_clustering(vids)
    cl_s = channel_clustering([v for v in vids if v.get("is_short")])
    cl_l = channel_clustering([v for v in vids if not v.get("is_short")])
    summary = (f"{distinct} channels across {len(vids)} videos — but the top 5 hold "
               f"{pooled['top5_share']:.0%} (top 1 = {top_share:.0%}). Effective independent "
               f"sample (what per-video patterns really rest on): Shorts ≈ "
               f"{cl_s['effective_n']:.0f}, Long ≈ {cl_l['effective_n']:.0f}. Treat "
               f"per-video findings with that in mind, not the raw video count.")
    return {"name": "Niche saturation", "cost": 0, "summary": summary,
            "result": {"distinct_channels": distinct,
                       "top_channels": chans.most_common(5),
                       "concentration": round(top_share, 2),
                       "top5_share": pooled["top5_share"],
                       "effective_n_shorts": cl_s["effective_n"],
                       "effective_n_long": cl_l["effective_n"]}}


def tool_language_split(ds):
    """Performance by title script/language."""
    def grp(vids):
        buckets = {}
        for v in vids:
            buckets.setdefault(detect_script(v["title"]), []).append(v)
        return {lang: {"count": len(vs),
                       "median_vpd": round(statistics.median(
                           [x["views_per_day"] for x in vs])),
                       "videos": vs}
                for lang, vs in buckets.items()}
    res = per_format(ds["videos"], grp)
    langs = ", ".join(res["shorts"].keys())
    summary = (f"Title scripts present in Shorts: {langs}. (Detects SCRIPT only — Latin "
               f"lumps English/Spanish/Portuguese/Polish together, so this is not a "
               f"region or language read.)")
    return {"name": "Title script split", "cost": 0,
            "summary": summary, "result": res}


def tool_freshness(ds):
    """
    Trend-spike check. Looks at how OLD the videos in this niche are. If almost
    everything is days/weeks old, the niche is exploding right now — the findings
    reflect that wave (and the game's virality), not a durable, repeatable lane.
    Caveat: if you set a 'Max video age' filter, ages are bounded by it, so run
    this with the age filter at 0 for an honest read.
    """
    def grp(vids):
        ages = sorted(v["age_days"] for v in vids if v.get("age_days"))
        if not ages:
            return {"n": 0}
        med = ages[len(ages) // 2]
        share_recent = round(sum(1 for a in ages if a <= 30) / len(ages), 2)
        return {"n": len(ages), "median_age_days": med,
                "share_under_30d": share_recent, "oldest_days": ages[-1]}

    res = per_format(ds["videos"], grp)
    lead = res["shorts"] if res["shorts"].get("n") else res["long"]
    if not lead.get("n"):
        return {"name": "Niche freshness (trend-spike check)", "cost": 0,
                "summary": "No dated videos to judge.", "result": res}

    med = lead["median_age_days"]
    share = lead.get("share_under_30d", 0)
    if med <= 30 and share >= 0.8:
        verdict = ("⚡ TREND SPIKE — most videos are days/weeks old. The niche is "
                   "exploding right now; signals reflect the wave (the game going "
                   "viral), not a durable lane. Worth riding NOW, but expect it to cool.")
    elif med <= 90:
        verdict = "Warming — fairly recent activity; neither a spike nor fully evergreen."
    else:
        verdict = "Evergreen — videos span a long time, so findings are likely durable."

    s_med = res["shorts"].get("median_age_days", "?")
    l_med = res["long"].get("median_age_days", "?")
    summary = f"Median age — Shorts {s_med}d / Long {l_med}d. {verdict}"
    return {"name": "Niche freshness (trend-spike check)", "cost": 0,
            "summary": summary, "result": res}


def tool_channel_outlier(ds):
    """Each video vs ITS OWN channel's average views. Needs fetch_channel_stats first."""
    if not ds["videos"] or "channel_avg_views" not in ds["videos"][0]:
        return {"name": "Per-channel over/under", "cost": 0,
                "summary": "Run 'channel stats' fetch first (this tool needs it).",
                "result": {}}

    def grp(vids):
        for v in vids:
            avg = v.get("channel_avg_views", 0)
            v["vs_own_channel"] = round(v["views"] / avg, 2) if avg else 0
        over = sorted([v for v in vids if v["vs_own_channel"] >= 1.5],
                      key=lambda v: -v["vs_own_channel"])
        under = sorted([v for v in vids if 0 < v["vs_own_channel"] <= 0.7],
                       key=lambda v: v["vs_own_channel"])
        rated = [v for v in vids if v["vs_own_channel"] > 0]
        # NOTE: over[:8]/under[:8] are trimmed for DISPLAY only. The *_count fields are
        # the real totals. The old summary counted the trimmed list, so it always said
        # "8" — which is what made the AI "discover" a fake 98%-underperform crisis.
        return {"overperformed": over[:8], "underperformed": under[:8],
                "over_count": len(over), "under_count": len(under),
                "rated_count": len(rated), "n": len(vids)}
    res = per_format(ds["videos"], grp)
    s = res["shorts"]
    summary = (f"Shorts beating their own channel median (≥1.5×): "
               f"{s.get('over_count', 0)} of {s.get('rated_count', 0)} rated")
    return {"name": "Per-channel over/under", "cost": 0,
            "summary": summary, "result": res}


def tool_cadence(ds):
    """Upload frequency vs reach: the 1-video-3M vs 10-video-500K question."""
    if not ds["videos"] or "channel_uploads_per_month" not in ds["videos"][0]:
        return {"name": "Upload cadence vs reach", "cost": 0,
                "summary": "Run 'channel stats' fetch first (this tool needs it).",
                "result": {}}
    # Only rank channels that actually appear in THIS niche more than once. A non-endemic
    # brand (e.g. a car company that sponsors esports) can match the query with ONE
    # tangential video yet top the ranking on channel-wide reach — its 'views_per_month'
    # is computed from its last ~50 uploads, which are off-topic. Requiring >=2 videos
    # in-search keeps the headline to channels genuinely active in the niche.
    MIN_APPEARANCES = 2
    counts = Counter(v["channel"] for v in ds["videos"])
    seen = {}
    for v in ds["videos"]:
        if counts[v["channel"]] < MIN_APPEARANCES:
            continue
        seen[v["channel"]] = {
            "uploads_per_month": v.get("channel_uploads_per_month", 0),
            "avg_views": v.get("channel_avg_views", 0),
            "views_per_month": v.get("channel_views_per_month", 0),
            "videos_in_search": counts[v["channel"]],
        }
    ranked = sorted(seen.items(), key=lambda kv: -kv[1]["views_per_month"])
    if not ranked:
        return {"name": "Upload cadence vs reach", "cost": 0,
                "summary": ("No channel appears 2+ times in this niche yet — widen the "
                            "search for a meaningful cadence ranking."),
                "result": {"channels": []}}
    summary = (f"Top reach (within this search): {ranked[0][0]} "
               f"({ranked[0][1]['uploads_per_month']}/mo, "
               f"{ranked[0][1]['views_per_month']:,} views/mo, "
               f"{ranked[0][1]['videos_in_search']} of {len(ds['videos'])} videos here). "
               f"Note: a channel that floods the search will top this — it's reach within "
               f"these results, not proof high cadence causes high reach.")
    return {"name": "Upload cadence vs reach", "cost": 0,
            "summary": summary, "result": {"channels": ranked}}


def _humanize(n):
    n = float(n)
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}K"
    return f"{int(n)}"


def _histogram(values, bins=10, mode="linear", fmt=None):
    """
    Bin values into a labelled histogram.
    mode='log' spreads right-skewed data (like views/day) so it isn't one tall bar.
    fmt formats the edge labels (e.g. seconds for duration, humanized for views).
    """
    if fmt is None:
        fmt = _humanize
    if mode == "log":
        values = [v for v in values if v and v > 0]
    else:
        values = [v for v in values if v is not None]
    if not values:
        return {"labels": [], "counts": []}

    if mode == "log":
        import math
        lo = max(min(values), 1)
        hi = max(values)
        if hi <= lo:
            hi = lo * 10
        llo, lhi = math.log10(lo), math.log10(hi)
        edges = [10 ** (llo + (lhi - llo) * i / bins) for i in range(bins + 1)]
    else:
        lo, hi = min(values), max(values)
        if hi == lo:
            hi = lo + 1
        edges = [lo + (hi - lo) * i / bins for i in range(bins + 1)]

    counts = [0] * bins
    for v in values:
        idx = bins - 1
        for i in range(bins):
            if v <= edges[i + 1]:
                idx = i
                break
        counts[idx] += 1
    labels = [f"{fmt(edges[i])}-{fmt(edges[i + 1])}" for i in range(bins)]
    return {"labels": labels, "counts": counts}


def tool_charts(ds):
    """
    Distribution charts per format: duration histogram, views-per-day histogram,
    and a views-vs-like-rate scatter (to see if like% just tracks reach).
    Pure math on already-fetched data — no API cost.
    """
    result = {}
    for name, grp in zip(("shorts", "long"), by_format(ds["videos"])):
        result[name] = {
            "duration_hist": _histogram([v["duration_sec"] for v in grp],
                                        fmt=lambda x: f"{int(x)}s"),
            "vpd_hist": _histogram([v["views_per_day"] for v in grp
                                    if v["views_per_day"] > 0], mode="log"),
            "scatter": [{"views": v["views"],
                         "like_rate_pct": round(v["like_rate"] * 100, 2)}
                        for v in grp if v["views"] > 0],
            "n": len(grp),
        }
    summary = ("Distributions per format: video length, views-per-day, and "
               "views-vs-like-rate (shows whether like% just falls as views rise).")
    return {"name": "Distribution charts", "cost": 0,
            "summary": summary, "result": result}


def tool_channels(ds):
    """
    For the channels in THIS search, show each channel's median views here and (if
    channel stats were fetched) how many of those videos beat the channel's ALL-TIME
    median — a real consistency signal. Shorts and long-form kept separate.

    NOTE: counting videos above the median OF THE SAME videos is tautological (a median
    splits its own set ~50/50 by definition), so that count carried no information. We
    now compare against the channel's all-time median (channel_avg_views, pulled by
    fetch_channel_stats). Without that fetch we simply omit the count rather than show a
    number that always says "about half".
    """
    def grp(vids):
        by_chan = {}
        for v in vids:
            by_chan.setdefault(v["channel"], []).append(v)
        rows = []
        for chan, cvids in by_chan.items():
            views = [v["views"] for v in cvids]
            n = len(cvids)
            # median is robust; for n==1 it's just that video (we label it honestly)
            typical = round(statistics.median(views))
            # Real bar = the channel's ALL-TIME median (same for every video of a channel,
            # attached by fetch_channel_stats). None if channel stats weren't fetched.
            alltime = next((v.get("channel_avg_views") for v in cvids
                            if v.get("channel_avg_views")), None)
            if alltime:
                above = sorted([v for v in cvids if v["views"] > alltime],
                               key=lambda v: -v["views"])
                above_count = len(above)
            else:
                above, above_count = [], None        # no honest count without all-time data
            above_videos = [{
                "title": v["title"],
                "url": v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
                "views": v["views"],
            } for v in above]
            rows.append({"channel": chan, "n": n, "typical_views": typical,
                         "single_video": n == 1,
                         "alltime_median": round(alltime) if alltime else None,
                         "above_count": above_count,
                         "above_videos": above_videos,
                         "all_videos": [{
                             "title": v["title"],
                             "url": v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
                             "views": v["views"]} for v in
                             sorted(cvids, key=lambda v: -v["views"])]})
        # Rank by typical views, but multi-video channels first (more trustworthy)
        rows.sort(key=lambda r: (r["n"] >= 3, r["typical_views"]), reverse=True)
        return rows

    res = per_format(ds["videos"], grp)

    # Build a printable table (the 'detail' the runner prints under the summary)
    detail = []
    for fmt_name, rows in (("SHORTS", res["shorts"]), ("LONG-FORM", res["long"])):
        if not rows:
            continue
        detail.append(f"    {fmt_name}:")
        detail.append(f"    {'channel':22} {'vids':>4} {'median views':>13}")
        for r in rows[:10]:
            tag = " (1 video)" if r["single_video"] else ""
            detail.append(f"    {r['channel'][:22]:22} {r['n']:>4} "
                          f"{r['typical_views']:>13,}{tag}")

    # Prefer a channel with several videos for the headline (more meaningful)
    def best(rows):
        multi = [r for r in rows if r["n"] >= 3]
        return (multi or rows)[0] if rows else None
    top = best(res["shorts"]) or best(res["long"])
    if top:
        kind = f"{top['n']} videos" if not top["single_video"] else "1 video (single data point)"
        summary = (f"Top niche channel (Shorts): {top['channel']} — "
                   f"median {top['typical_views']:,} across {kind}")
    else:
        summary = "No channels found"
    return {"name": "Channels in niche (median views)", "cost": 0,
            "summary": summary, "detail": detail, "result": res}


# ======================================================================
# AI SUMMARY (Claude) — spends the separate Claude wallet, not quota
# ======================================================================
def get_claude_key():
    """Where the Claude key comes from (Colab secret or .env / env var)."""
    try:
        from google.colab import userdata
        k = userdata.get("ANTHROPIC_API_KEY")
        if k:
            return k
    except Exception:
        pass
    k = os.environ.get("ANTHROPIC_API_KEY")
    if not k:
        raise RuntimeError("No Claude key. Add ANTHROPIC_API_KEY=... to your .env")
    return k


def _call_claude(prompt, max_tokens=1400):
    """One call to Claude. Returns {text, usage, cost_usd}."""
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": get_claude_key(),
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        data=json.dumps({"model": CLAUDE_MODEL, "max_tokens": max_tokens,
                         "messages": [{"role": "user", "content": prompt}]}))
    r.raise_for_status()
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    u = data.get("usage", {})
    cost = (u.get("input_tokens", 0) / 1e6 * CLAUDE_PRICE["input_per_mtok"]
            + u.get("output_tokens", 0) / 1e6 * CLAUDE_PRICE["output_per_mtok"])
    return {"text": text, "usage": u, "cost_usd": round(cost, 4)}


# What each tool is FOR — fed to the AI so it can judge whether a tool is working as
# intended and whether it's even relevant for the niche, not just read its number.
PURPOSES = {
    "outliers": "Rank videos by velocity (views/day) vs the median of videos of SIMILAR AGE (age-adjusted, because raw views/day favours fresh videos) to surface what's over/under-performing.",
    "title_len": "Test whether title length (chars) separates faster from slower videos.",
    "emoji": "Test whether using emoji in the title separates faster from slower videos.",
    "question": "Test whether question-style titles separate faster from slower videos.",
    "numbers": "Test whether numbers/$ in the title separate faster from slower videos.",
    "caps": "Test whether ALL-CAPS words in the title separate faster from slower videos.",
    "hook": "Surface the most common opening words among the fastest videos (qualitative).",
    "duration": "Test whether video length (seconds) separates faster from slower videos.",
    "timing": "Surface which weekday the fastest videos tend to post on (qualitative).",
    "like_rate": "Test whether like-per-view separates faster from slower videos (suspected reach artifact).",
    "comment_rate": "Test whether comment-per-view separates faster from slower videos (suspected reach artifact, like like-rate).",
    "breakouts": "Find videos that beat their channel's subscriber count the most (views/subs).",
    "chan_outlier": "Compare each video to its OWN channel's typical views (needs channel stats).",
    "cadence": "Relate a channel's upload frequency to its total reach (needs channel stats).",
    "channels": "Per-channel median views in this niche + how many of its videos beat that median.",
    "saturation": "Measure how concentrated the niche is: distinct channels, top-5 share, and the effective independent sample size (clustering-aware).",
    "language": "Split titles by SCRIPT only (Latin/CJK/etc.) — NOT language or region; Latin lumps English/Spanish/Portuguese/Polish together.",
    "freshness": "Median video age — flags a trend spike when most videos are very recent.",
}


def _collect_signals(ds):
    """Run the free analysis tools and gather, per tool, its INTENDED PURPOSE plus its
    one-line result — so Claude can audit whether each is working and relevant."""
    have_cs = bool(ds["videos"]) and "channel_avg_views" in ds["videos"][0]
    lines = []
    for key, spec in TOOLS.items():
        if spec["cat"] == "AI":          # don't run (or charge) any paid AI tool here
            continue
        if key == "all_videos":          # the raw data dump isn't a "signal"
            continue
        if spec["needs_channel_stats"] and not have_cs:
            continue
        try:
            out = spec["func"](ds)
            purpose = PURPOSES.get(key, "")
            min_v = MIN_VIDEOS.get(key)
            tag = f" [purpose: {purpose}]" if purpose else ""
            tag += f" [min sample wanted: {min_v}/group]" if min_v else ""
            lines.append(f"- {out['name']}{tag}: {out['summary']}")
        except Exception:
            pass
    return "\n".join(lines)


def _fetch_diagnostics(ds):
    """Plain-text fetch report so the AI can flag a too-narrow window / tiny niche /
    wasted quota — things invisible from the signal numbers alone."""
    m = ds.get("meta")
    if not m:
        return "Fetch diagnostics: not available."
    w = m.get("window", {})
    src = "from cache (0 quota)" if ds.get("from_cache") else f"{m.get('quota_cost', 0)} quota units"
    note = ""
    if m.get("requested_total") and m.get("fill_ratio", 1) < 0.5:
        note = (f" NOTE: only {m['returned_total']} of ~{m['requested_total']} requested came "
                f"back ({int(m['fill_ratio']*100)}%) — the search window may be too narrow or "
                f"the niche too small for this window; the sample is supply-limited, not a bug.")
    cl_s = channel_clustering([v for v in ds["videos"] if v.get("is_short")])
    cl_l = channel_clustering([v for v in ds["videos"] if not v.get("is_short")])
    cluster = (f" CLUSTERING (critical for reliability): Shorts come from {cl_s['channels']} "
               f"channels, top 5 = {cl_s['top5_share']:.0%}, EFFECTIVE independent sample "
               f"≈ {cl_s['effective_n']:.0f} (not {cl_s['videos']}). Long-form: "
               f"{cl_l['channels']} channels, top 5 = {cl_l['top5_share']:.0%}, effective "
               f"≈ {cl_l['effective_n']:.0f}. The per-video '% of fastest vs slowest' splits "
               f"rest on these effective sizes, not the raw counts — weight your confidence "
               f"accordingly and say so if the effective sample is small.")
    return (f"Fetch diagnostics: requested up to {m.get('requested_per_format')}/format; "
            f"returned {m.get('returned_total')} videos "
            f"({m.get('returned_shorts')} Shorts, {m.get('returned_long')} long-form); "
            f"window {w.get('after')}→{w.get('before') or 'today'}, region '{w.get('region')}'; "
            f"spent {src}.{note}{cluster}")


def _corr(xs, ys):
    """Pearson correlation; returns 0 if undefined."""
    n = len(xs)
    if n < 3:
        return 0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(num / (dx * dy), 2) if dx and dy else 0


def _distribution_summary(ds):
    """Plain-text description of the distributions, so Claude can 'see' the charts."""
    lines = []
    for name, grp in zip(("Shorts", "Long-form"), by_format(ds["videos"])):
        if len(grp) < 5:
            continue
        durs = sorted(v["duration_sec"] for v in grp)
        vpd = sorted(v["views_per_day"] for v in grp if v["views_per_day"] > 0)
        views = [v["views"] for v in grp if v["views"] > 0]
        likes = [v["like_rate"] * 100 for v in grp if v["views"] > 0]
        r = _corr(views, likes)
        med_d = durs[len(durs) // 2]
        med_v = vpd[len(vpd) // 2] if vpd else 0
        max_v = vpd[-1] if vpd else 0
        skew = "heavily right-skewed (a few viral outliers)" if max_v > med_v * 10 \
            else "fairly even"
        rel = ("like% falls as views rise — like-rate just tracks reach, not quality"
               if r <= -0.2 else
               "like% rises with views" if r >= 0.2 else
               "no clear link between views and like%")
        lines.append(
            f"{name}: median duration {med_d}s; views/day median {_humanize(med_v)}, "
            f"max {_humanize(max_v)} ({skew}); views-vs-like correlation r={r} ({rel}).")
    return "\n".join(lines)


def tool_ai_summary(ds):
    """
    Sends the computed signals to Claude for: a strategy brief, a per-signal read,
    a blunt reliability verdict, and developer notes (data-accuracy / feature audit).
    Costs the CLAUDE wallet (a few cents), not YouTube quota.
    """
    n = len(ds["videos"])
    ns = sum(v["is_short"] for v in ds["videos"])
    signals = _collect_signals(ds)
    distributions = _distribution_summary(ds)
    diagnostics = _fetch_diagnostics(ds)
    topic = ds.get("topic", "(unknown)")

    prompt = f"""You are a blunt, practical YouTube strategy analyst AND a QA reviewer \
auditing an automated niche-research tool. Do not flatter. Be concrete.

Topic searched: "{topic}"
Sample size: {n} videos ({ns} Shorts, {n - ns} long-form).
Note: "velocity" = views per day. Shorts and long-form are analysed separately.

{diagnostics}

Computed signals from the tool. Each line gives the tool's INTENDED PURPOSE and the \
minimum per-group sample it wants, then its result:
{signals}

Distribution data (from the charts):
{distributions}

CRITICAL — respect the tool's own verdict. Each signal line already contains the verdict \
the tool computed from the data: "no clear difference", "winners higher", or "winners \
lower". That verdict IS the ground truth. You must NOT upgrade a "no clear difference" to \
a "real signal", "actionable", or "keep" — if the tool found no clear difference, the \
honest read is noise / too-close-to-call, and you say so. A single run's gap that sits \
near the threshold (e.g. emoji at 65% vs 51%) is exactly the kind of thing that flips \
between runs; treat it as noise, not a trend. Only call something a real, actionable \
signal when the tool itself reports a clear direction AND the per-group sample meets its \
stated minimum. If your judgement genuinely differs from the tool's verdict, you may say \
so, but you must explicitly flag that you are overriding the tool and give the concrete \
statistical reason — never silently contradict it.

Respond in markdown with EXACTLY these five sections:

## Strategy brief
2-4 sentences: what kind of content wins in this niche and what the user should make next.

## Per-signal read
One short line per signal above: what it suggests, and whether it's a real signal or noise.

## Worth following, or noise?
Be blunt about reliability given the sample size. If comparisons rest on very few \
videos (e.g. 1 vs 1), say plainly the findings are NOT yet trustworthy and state roughly \
how many videos would be needed to trust them.

## Tool audit (is each tool working & relevant?)
Go through the tools using the stated PURPOSE of each. For each notable one say whether it \
is (a) working as intended, (b) relevant to THIS niche, or (c) broken / redundant / a data \
void / measuring something it doesn't claim to. Call out tools that should be cut or fixed, \
and any whose sample is below its stated minimum. Use the fetch diagnostics above: if far \
fewer videos came back than were requested, say the window is too narrow or the niche too \
thin for it, and that this — not the tools — is what's making samples unreliable.

## Developer notes (data accuracy & feature ideas)
Flag anything that looks like a data error, misleading metric, unsound comparison, or likely \
bug not already covered above. Then suggest 2-3 concrete features or fixes. Be specific."""

    try:
        res = _call_claude(prompt, max_tokens=1800)
    except Exception as e:
        return {"name": "AI summary (Claude)", "cost": 0,
                "summary": f"Claude call failed: {e}",
                "result": {"text": "", "error": str(e)}}

    out_tok = res["usage"].get("output_tokens", "?")
    return {"name": "AI summary (Claude)", "cost": 0,
            "claude_cost_usd": res["cost_usd"], "tokens": res["usage"],
            "summary": f"AI brief generated — ~${res['cost_usd']:.4f}, {out_tok} output tokens",
            "result": {"text": res["text"]}}


def tool_ai_ideas(ds):
    """
    Creative Claude tool: pitches concrete NEW video ideas built from what's actually
    winning in THIS niche's data (not generic advice). Costs the Claude wallet.
    Distinct from ai_summary, which audits the data/tool.
    """
    topic = ds.get("topic", "(unknown)")
    shorts, longform = by_format(ds["videos"])

    def fastest(vids, k=10):
        return sorted([v for v in vids if v.get("views_per_day", 0) > 0],
                      key=lambda v: -v["views_per_day"])[:k]

    win_sh = [f'- "{v["title"]}" ({_humanize(v["views"])} views, {v["duration_sec"]}s)'
              for v in fastest(shorts)]
    win_lo = [f'- "{v["title"]}" ({_humanize(v["views"])} views)'
              for v in fastest(longform)]
    signals = _collect_signals(ds)

    prompt = f"""You are a YouTube content strategist pitching NEW video ideas for a creator \
in the "{topic}" niche. Base every idea ONLY on what is actually winning in their data \
below — no generic advice.

Top-performing Shorts:
{chr(10).join(win_sh) or "(none)"}

Top-performing long-form:
{chr(10).join(win_lo) or "(none)"}

Measured signals:
{signals}

Pitch exactly 5 specific, ready-to-film ideas. For EACH give:
1. A working title that follows the patterns that win here (mind length, avoid ALL-CAPS).
2. One line on the hook / first 3 seconds.
3. Format: Short or long-form.
4. One blunt line on how derivative-vs-fresh it is (don't pretend a copycat is original).

Respond in markdown, numbered 1-5, no preamble."""

    try:
        res = _call_claude(prompt)
    except Exception as e:
        return {"name": "AI video ideas (Claude)", "cost": 0,
                "summary": f"Claude call failed: {e}",
                "result": {"text": "", "error": str(e)}}

    out_tok = res["usage"].get("output_tokens", "?")
    return {"name": "AI video ideas (Claude)", "cost": 0,
            "claude_cost_usd": res["cost_usd"], "tokens": res["usage"],
            "summary": f"5 ideas generated — ~${res['cost_usd']:.4f}, {out_tok} output tokens",
            "result": {"text": res["text"]}}


def tool_all_videos(ds):
    """
    Full browse table: EVERY video in the search with all its fields (views, likes,
    comments, channel, release date, duration, velocity, subs, etc.). This is a raw
    data dump for sorting/exporting — not an analysis — so Shorts and long-form share
    one table but carry a 'format' flag you can sort by.
    """
    vids = ds["videos"]
    ns = sum(v["is_short"] for v in vids)
    summary = (f"{len(vids)} videos ({ns} Shorts, {len(vids) - ns} long-form) — "
               f"full sortable table with thumbnails; download as CSV from the table toolbar.")
    return {"name": "All videos (full table)", "cost": 0,
            "summary": summary, "result": {"videos": vids}}


# ======================================================================
# 4. REGISTRY — the check-mark menu
#    key -> {label, category, func, cost_note}
# ======================================================================
TOOLS = {
    "outliers":    {"label": "Outliers (winners & flops)", "cat": "Discovery",
                    "func": tool_outliers, "needs_channel_stats": False},
    "title_len":   {"label": "Title length sweet spot", "cat": "Title",
                    "func": _numeric_tool("Title length (characters)",
                                          lambda v: len(v["title"]), " chars"),
                    "needs_channel_stats": False},
    "emoji":       {"label": "Emoji impact", "cat": "Title",
                    "func": _presence_tool("Emoji impact",
                                           lambda v: has_emoji(v["title"])),
                    "needs_channel_stats": False},
    "question":    {"label": "Question vs statement titles", "cat": "Title",
                    "func": _presence_tool("Question titles",
                                           lambda v: "?" in v["title"]),
                    "needs_channel_stats": False},
    "numbers":     {"label": "Numbers / $ in title", "cat": "Title",
                    "func": _presence_tool("Number or $ in title",
                                           lambda v: bool(re.search(r"[\d$]", v["title"]))),
                    "needs_channel_stats": False},
    "caps":        {"label": "ALL-CAPS / hype words", "cat": "Title",
                    "func": _numeric_tool("ALL-CAPS words",
                                          lambda v: caps_words(v["title"]),
                                          caveat=("weak, Shorts-only signal — caps also "
                                                  "show up in FAST long-form, so don't "
                                                  "treat 'avoid caps' as a rule")),
                    "needs_channel_stats": False},
    "hook":        {"label": "Title hook (opening words)", "cat": "Title",
                    "func": tool_title_hook, "needs_channel_stats": False},
    "duration":    {"label": "Duration sweet spot", "cat": "Video",
                    "func": _numeric_tool("Duration (sec)",
                                          lambda v: v["duration_sec"], "s"),
                    "needs_channel_stats": False},
    "timing":      {"label": "Upload timing (weekday)", "cat": "Video",
                    "func": tool_upload_timing, "needs_channel_stats": False},
    "like_rate":   {"label": "Like-per-view rate", "cat": "Engagement",
                    "func": _numeric_tool("Like rate", lambda v: v["like_rate"] * 100, "%",
                                          diagnostic=True),
                    "needs_channel_stats": False},
    "comment_rate": {"label": "Comment-per-view rate", "cat": "Engagement",
                     "func": _numeric_tool("Comment rate",
                                           lambda v: v["comment_rate"] * 100, "%",
                                           decimals=3, min_base=0.01, diagnostic=True),
                     "needs_channel_stats": False},
    "breakouts":   {"label": "Small-channel breakouts", "cat": "Channel",
                    "func": tool_small_breakouts, "needs_channel_stats": False},
    "saturation":  {"label": "Niche saturation", "cat": "Niche",
                    "func": tool_saturation, "needs_channel_stats": False},
    "language":    {"label": "Title script split", "cat": "Niche",
                    "func": tool_language_split, "needs_channel_stats": False},
    "freshness":   {"label": "Niche freshness (trend-spike check)", "cat": "Niche",
                    "func": tool_freshness, "needs_channel_stats": False},
    "chan_outlier": {"label": "Per-channel over/under", "cat": "Channel",
                     "func": tool_channel_outlier, "needs_channel_stats": True},
    "cadence":     {"label": "Upload cadence vs reach", "cat": "Channel",
                    "func": tool_cadence, "needs_channel_stats": True},
    "channels":    {"label": "Channels in niche (avg views + consistency)",
                    "cat": "Channel",
                    "func": tool_channels, "needs_channel_stats": False},
    "ai_summary":  {"label": "AI summary (Claude) — costs credit", "cat": "AI",
                    "func": tool_ai_summary, "needs_channel_stats": False},
    "ai_ideas":    {"label": "AI video ideas (Claude) — costs credit", "cat": "AI",
                    "func": tool_ai_ideas, "needs_channel_stats": False},
    "all_videos":  {"label": "All videos (full table)", "cat": "Data",
                    "func": tool_all_videos, "needs_channel_stats": False},
    "charts":      {"label": "Distribution charts", "cat": "Visual",
                    "func": tool_charts, "needs_channel_stats": False},
}


# ======================================================================
# SAMPLE-SIZE HONESTY — each comparison tool declares a minimum sample.
# Below it, the GUI stamps a "needs more data" warning instead of pretending
# a top-third-vs-bottom-third split on a handful of videos is meaningful.
# (Pattern/timing tools only — descriptive tools like saturation aren't
# top-vs-bottom comparisons, so a small sample doesn't mislead the same way.)
# ======================================================================
MIN_VIDEOS = {
    "title_len": 30, "emoji": 30, "question": 30, "numbers": 30, "caps": 30,
    "hook": 30, "duration": 30, "timing": 30, "like_rate": 30, "comment_rate": 30,
}


def data_warning(key, out):
    """Return a warning naming any FORMAT whose comparison group is below the minimum,
    else None. Each pattern tool compares the fastest third vs the slowest third of a
    format, so a group is ~1/3 of that format's videos — NOT the total search size.
    The old message reported a bare number with no format label, which read like 'you
    only got N videos' (you didn't)."""
    thresh = MIN_VIDEOS.get(key)
    if not thresh:
        return None
    res = out.get("result", {})
    thin = []
    for fmt, label in (("shorts", "Shorts"), ("long", "long-form")):
        block = res.get(fmt)
        if not isinstance(block, dict):
            continue
        if "top_n" in block and "bottom_n" in block:
            grp = min(block["top_n"], block["bottom_n"])
        elif "n" in block:
            grp = block["n"]
        else:
            continue
        if 0 < grp < thresh:
            thin.append(f"{label} (~{grp} per group)")
    if not thin:
        return None
    return ("⚠ Small sample for " + ", ".join(thin) + ". This tool compares only the "
            "fastest third vs the slowest third of EACH format, so a group is about a "
            "third of that format's videos — not your whole search. Want 30+ per group; "
            "treat the flagged format as a hint, not a fact.")


def menu():
    """Print the available tools, grouped by category, with their keys."""
    print("AVAILABLE TOOLS (use the key to select):\n")
    cats = {}
    for key, spec in TOOLS.items():
        cats.setdefault(spec["cat"], []).append((key, spec["label"],
                                                  spec["needs_channel_stats"]))
    for cat, items in cats.items():
        print(f"  [{cat}]")
        for key, label, needs in items:
            tag = "  (needs channel stats)" if needs else ""
            print(f"    '{key}'  -  {label}{tag}")
        print()


# ======================================================================
# 5. RUNNER + COST METER
# ======================================================================
def estimate_cost(balanced=True, tiers=None):
    """Rough quota estimate BEFORE fetching, so the meter can warn you."""
    cost = 200 if balanced else 100
    cost += 2  # detail + subs fetches
    return cost


def run_dashboard(topic, selected_tools, after=None, before=None,
                  tier=None, balanced=True, max_age_days=None, max_results=50):
    """
    The single function the GUI will eventually call.
    1) estimate + show cost,  2) fetch (cached),  3) filter by tier,
    4) run each checked tool,  5) print blocks + update wallet.
    """
    print("=" * 64)
    print(f"RUN: '{topic}'  |  tools: {', '.join(selected_tools)}")
    if tier:
        print(f"Channel tier: {tier}")
    print("=" * 64)

    # --- fetch ---
    ds = fetch_dataset(topic, after, before, max_results, balanced, max_age_days)
    quota_cost = ds["cost"]

    # --- channel stats, only if a chosen tool needs it ---
    needs_cs = any(TOOLS[t]["needs_channel_stats"] for t in selected_tools)
    if needs_cs and not ds["from_cache"]:
        quota_cost += fetch_channel_stats(ds)
    elif needs_cs:
        fetch_channel_stats(ds)  # cached -> ~0

    # --- tier filter (applied after fetch; never mixes formats) ---
    if tier:
        ds = {**ds, "videos": by_tier(ds["videos"], tier)}

    WALLET["quota"] -= quota_cost
    src = "CACHED (free)" if ds["from_cache"] else f"{quota_cost} units"
    print(f"\nFetch cost: {src}   |   Quota wallet left: {WALLET['quota']:,}/10,000")
    print(f"Videos in play: {len(ds['videos'])} "
          f"({sum(v['is_short'] for v in ds['videos'])} Shorts, "
          f"{sum(not v['is_short'] for v in ds['videos'])} long-form)\n")

    # --- run each checked tool ---
    for key in selected_tools:
        if key not in TOOLS:
            print(f"  (unknown tool '{key}' skipped)")
            continue
        out = TOOLS[key]["func"](ds)
        print("-" * 64)
        print(f"▶ {out['name']}   [cost: {out['cost']}]")
        print(f"  {out['summary']}")
        for line in out.get("detail", []):   # optional detail table
            print(line)
    print("-" * 64)
    print(f"\nClaude credit (separate wallet): ${WALLET['claude_usd']:.2f} unused")
    return ds


# ======================================================================
# DEMO
# ======================================================================
if __name__ == "__main__":
    menu()
    # Example run (uncomment when your key is set):
    # run_dashboard("rocket league",
    #               selected_tools=["outliers", "emoji", "duration", "timing",
    #                               "like_rate", "saturation", "language"],
    #               after="2025-01-01", max_age_days=180)