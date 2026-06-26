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
from datetime import datetime, timezone

import requests

BASE = "https://www.googleapis.com/youtube/v3"
SHORTS_MAX_SECONDS = 180        # <= 3 min counts as a Short (heuristic)
CACHE_FILE = "yt_cache.json"

# Channel-size tiers (subscriber thresholds — adjustable)
TIERS = {"small": (0, 100_000), "medium": (100_000, 1_000_000), "large": (1_000_000, 10**12)}

# Wallets. Quota resets daily (free). Claude credit is real money.
WALLET = {"quota": 10_000, "claude_usd": 5.00}

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
               order="viewCount", video_duration=None, pages=1):
    """
    YouTube search. Returns video IDs. COSTS 100 UNITS PER PAGE.
    pages=1 -> up to 50 IDs (100 units). pages=2 -> up to 100 IDs (200 units), etc.
    """
    base = {"part": "id", "q": keyword, "type": "video",
            "order": order, "maxResults": 50}
    if after:
        base["publishedAfter"] = f"{after}T00:00:00Z"
    if before:
        base["publishedBefore"] = f"{before}T00:00:00Z"
    if video_duration:
        base["videoDuration"] = video_duration
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
        v["comment_rate"] = round(v["comments"] / v["views"], 4) if v["views"] else 0
        wd = pub.weekday()       # 0 = Monday
        v["weekday"] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd]
        v["hour"] = pub.hour
        if subs_map is not None:
            v["subs"] = subs_map.get(v["channel_id"], 0)
            v["views_per_sub"] = round(v["views"] / v["subs"], 2) if v.get("subs") else 0
    return videos


def fetch_dataset(topic, after=None, before=None, max_results=50,
                  balanced=True, max_age_days=None, use_cache=True,
                  videos_per_format=50):
    """
    Orchestrates a full fetch and returns a Dataset:
      {topic, videos, cost, from_cache}
    'balanced' fetches Shorts AND long-form separately (2 searches).
    'videos_per_format' = how many videos to pull per format. Each 50 is one
    search PAGE = 100 units. So 100 videos/format balanced = 4 pages = 400 units.
    Results are cached so an identical call later costs 0.
    """
    pages = max(1, (videos_per_format + 49) // 50)
    cache = _load_cache()
    key = json.dumps(["v3", topic, after, before, balanced, max_age_days, pages])
    if use_cache and key in cache:
        return {"topic": topic, "videos": cache[key], "cost": 0, "from_cache": True}

    cost = 0
    if balanced:
        ids = search_ids(topic, after=after, before=before,
                         video_duration="short", pages=pages)
        ids += search_ids(topic, after=after, before=before,
                          video_duration="medium", pages=pages)
        ids = list(dict.fromkeys(ids))
        cost += 100 * pages * 2
    else:
        ids = search_ids(topic, after=after, before=before, pages=pages)
        cost += 100 * pages

    videos = get_videos_details(ids)
    subs_map = get_channel_subs([v["channel_id"] for v in videos])
    cost += len(range(0, len(ids), 50)) + 1  # cheap detail + subs calls
    enrich(videos, subs_map)

    if max_age_days:
        videos = [v for v in videos if v["age_days"] <= max_age_days]

    cache[key] = videos
    _save_cache(cache)
    return {"topic": topic, "videos": videos, "cost": cost, "from_cache": False}


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
            avg_views = statistics.mean(views) if views else 0
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


def top_bottom(videos, metric="views_per_day", frac=0.33):
    """Split a group into its top and bottom slice by a metric."""
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
def _verdict(top, bottom):
    """Plain-English read of a top-vs-bottom comparison, honest about ties."""
    base = max(abs(top), abs(bottom), 1)
    if abs(top - bottom) / base < 0.15:
        return "no clear difference"
    return "winners higher" if top > bottom else "winners lower"


def _vid_card(v, baseline=None):
    """A compact, link-ready dict for one video, with context numbers attached."""
    card = {
        "title": v["title"], "url": v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
        "views": v["views"], "views_per_day": v.get("views_per_day"),
        "age_days": v.get("age_days"),
    }
    if baseline:
        card["vs_baseline"] = round(v.get("views_per_day", 0) / baseline, 2) if baseline else None
    avg = v.get("channel_avg_views")
    if avg:
        card["vs_channel_avg"] = round(v["views"] / avg, 2) if avg else None
    return card


def tool_outliers(ds):
    """
    Ranks videos by views-per-day (velocity) against each FORMAT's own median.
    Labels are descriptive ('fastest'/'slowest in batch'), NOT judgmental — a
    low-velocity video may still beat its own channel, which we show too.
    """
    def grp(vids):
        vals = [v["views_per_day"] for v in vids if v["views_per_day"] > 0]
        base = statistics.median(vals) if vals else 0
        for v in vids:
            v["score"] = round(v["views_per_day"] / base, 2) if base else 0
        fast = sorted([v for v in vids if v["score"] >= 2], key=lambda v: -v["score"])
        slow = sorted([v for v in vids if 0 < v["score"] <= 0.5], key=lambda v: v["score"])
        return {"baseline": round(base), "n": len(vids),
                "fastest": [_vid_card(v, base) for v in fast],
                "slowest": [_vid_card(v, base) for v in slow]}
    res = per_format(ds["videos"], grp)
    s, l = res["shorts"], res["long"]
    summary = (f"Shorts median {s['baseline']:,}/day "
               f"({len(s['fastest'])} above 2×, {len(s['slowest'])} below 0.5×) · "
               f"Long-form median {l['baseline']:,}/day "
               f"({len(l['fastest'])} above 2×, {len(l['slowest'])} below 0.5×)")
    return {"name": "Velocity outliers (views/day vs niche median)", "cost": 0,
            "summary": summary, "result": res}


def _presence_tool(name, pred):
    """Factory: how often a title trait appears in fastest vs slowest videos."""
    def tool(ds):
        def grp(vids):
            top, bot = top_bottom(vids)
            def items(vs):
                return [{"title": v["title"],
                         "url": v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
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


def _numeric_tool(name, fn, unit=""):
    """Factory: median of a numeric trait in fastest vs slowest, with per-video values."""
    def tool(ds):
        def grp(vids):
            top, bot = top_bottom(vids)
            def items(vs):
                return [{"title": v["title"],
                         "url": v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
                         "views": v["views"], "value": round(fn(v), 1)}
                        for v in vs]
            return {"top": _med(top, fn), "bottom": _med(bot, fn),
                    "top_n": len(top), "bottom_n": len(bot),
                    "top_items": items(top), "bottom_items": items(bot)}
        res = per_format(ds["videos"], grp)
        s = res["shorts"]
        verdict = _verdict(s["top"], s["bottom"])
        summary = (f"Shorts: {verdict} — fastest {s['top']:.1f}{unit} vs "
                   f"slowest {s['bottom']:.1f}{unit} "
                   f"(based on {s['top_n']}+{s['bottom_n']} videos)")
        return {"name": name, "cost": 0, "summary": summary, "result": res}
    return tool


def tool_title_hook(ds):
    """Most common opening words among top performers."""
    def grp(vids):
        top, _ = top_bottom(vids)
        firsts = [v["title"].split()[0].lower() for v in top if v["title"].split()]
        return {"common_openers": Counter(firsts).most_common(5),
                "top_videos": top, "n": len(top)}
    res = per_format(ds["videos"], grp)
    s = res["shorts"]["common_openers"][:3]
    summary = "Top Shorts often open with: " + ", ".join(f"'{w}'" for w, _ in s)
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


def tool_small_breakouts(ds):
    """Videos that massively beat their channel's subscriber count."""
    def grp(vids):
        ranked = sorted([v for v in vids if v.get("views_per_sub", 0) > 0],
                        key=lambda v: -v["views_per_sub"])
        return {"top": ranked[:8], "n": len(vids)}
    res = per_format(ds["videos"], grp)
    top = res["shorts"]["top"]
    lead = f"{top[0]['views_per_sub']}x subs" if top else "n/a"
    summary = f"Best small-channel Short breakout: {lead}"
    return {"name": "Small-channel breakouts", "cost": 0,
            "summary": summary, "result": res}


def tool_saturation(ds):
    """How crowded the niche is: channel concentration."""
    vids = ds["videos"]
    chans = Counter(v["channel"] for v in vids)
    distinct = len(chans)
    top_share = chans.most_common(1)[0][1] / len(vids) if vids else 0
    summary = (f"{distinct} distinct channels across {len(vids)} videos; "
               f"top channel holds {top_share:.0%} of results")
    return {"name": "Niche saturation", "cost": 0, "summary": summary,
            "result": {"distinct_channels": distinct,
                       "top_channels": chans.most_common(5),
                       "concentration": round(top_share, 2)}}


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
    summary = f"Shorts languages present: {langs}"
    return {"name": "Language / region split", "cost": 0,
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
        return {"overperformed": over[:8], "underperformed": under[:8], "n": len(vids)}
    res = per_format(ds["videos"], grp)
    summary = (f"Shorts beating their own channel avg: "
               f"{len(res['shorts']['overperformed'])}")
    return {"name": "Per-channel over/under", "cost": 0,
            "summary": summary, "result": res}


def tool_cadence(ds):
    """Upload frequency vs reach: the 1-video-3M vs 10-video-500K question."""
    if not ds["videos"] or "channel_uploads_per_month" not in ds["videos"][0]:
        return {"name": "Upload cadence vs reach", "cost": 0,
                "summary": "Run 'channel stats' fetch first (this tool needs it).",
                "result": {}}
    seen = {}
    for v in ds["videos"]:
        seen[v["channel"]] = {
            "uploads_per_month": v.get("channel_uploads_per_month", 0),
            "avg_views": v.get("channel_avg_views", 0),
            "views_per_month": v.get("channel_views_per_month", 0),
        }
    ranked = sorted(seen.items(), key=lambda kv: -kv[1]["views_per_month"])
    summary = (f"Top reach: {ranked[0][0]} "
               f"({ranked[0][1]['uploads_per_month']}/mo, "
               f"{ranked[0][1]['views_per_month']:,} views/mo)" if ranked else "n/a")
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
    For the channels in THIS search, show each channel's average views,
    how many videos they had here, and how many of those beat their OWN
    average (a consistency signal). Shorts and long-form kept separate.
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
            # "beats typical" only meaningful with enough videos
            above = sorted([v for v in cvids if v["views"] > statistics.median(views)],
                           key=lambda v: -v["views"])
            above_videos = [{
                "title": v["title"],
                "url": v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
                "views": v["views"],
            } for v in above]
            rows.append({"channel": chan, "n": n, "typical_views": typical,
                         "single_video": n == 1,
                         "above_count": len(above_videos),
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


def _collect_signals(ds):
    """Run the free analysis tools and gather their one-line summaries for Claude."""
    have_cs = bool(ds["videos"]) and "channel_avg_views" in ds["videos"][0]
    lines = []
    for key, spec in TOOLS.items():
        if key == "ai_summary":
            continue
        if spec["needs_channel_stats"] and not have_cs:
            continue
        try:
            out = spec["func"](ds)
            lines.append(f"- {out['name']}: {out['summary']}")
        except Exception:
            pass
    return "\n".join(lines)


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
    topic = ds.get("topic", "(unknown)")

    prompt = f"""You are a blunt, practical YouTube strategy analyst AND a QA reviewer \
auditing an automated niche-research tool. Do not flatter. Be concrete.

Topic searched: "{topic}"
Sample size: {n} videos ({ns} Shorts, {n - ns} long-form).
Note: "velocity" = views per day. Shorts and long-form are analysed separately.

Computed signals from the tool:
{signals}

Distribution data (from the charts):
{distributions}

Respond in markdown with EXACTLY these four sections:

## Strategy brief
2-4 sentences: what kind of content wins in this niche and what the user should make next.

## Per-signal read
One short line per signal above: what it suggests, and whether it's a real signal or noise.

## Worth following, or noise?
Be blunt about reliability given the sample size. If comparisons rest on very few \
videos (e.g. 1 vs 1), say plainly the findings are NOT yet trustworthy and state roughly \
how many videos would be needed to trust them.

## Developer notes (data accuracy & feature ideas)
You are auditing the TOOL itself, not just the niche. Flag anything that looks like a \
data error, a misleading metric, a statistically unsound comparison, or a likely bug. \
Then suggest 2-3 concrete features or fixes the developer should add. Be specific."""

    try:
        res = _call_claude(prompt)
    except Exception as e:
        return {"name": "AI summary (Claude)", "cost": 0,
                "summary": f"Claude call failed: {e}",
                "result": {"text": "", "error": str(e)}}

    out_tok = res["usage"].get("output_tokens", "?")
    return {"name": "AI summary (Claude)", "cost": 0,
            "claude_cost_usd": res["cost_usd"], "tokens": res["usage"],
            "summary": f"AI brief generated — ~${res['cost_usd']:.4f}, {out_tok} output tokens",
            "result": {"text": res["text"]}}


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
                                          lambda v: caps_words(v["title"])),
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
                    "func": _numeric_tool("Like rate", lambda v: v["like_rate"] * 100, "%"),
                    "needs_channel_stats": False},
    "comment_rate": {"label": "Comment-per-view rate", "cat": "Engagement",
                     "func": _numeric_tool("Comment rate",
                                           lambda v: v["comment_rate"] * 100, "%"),
                     "needs_channel_stats": False},
    "breakouts":   {"label": "Small-channel breakouts", "cat": "Channel",
                    "func": tool_small_breakouts, "needs_channel_stats": False},
    "saturation":  {"label": "Niche saturation", "cat": "Niche",
                    "func": tool_saturation, "needs_channel_stats": False},
    "language":    {"label": "Language / region split", "cat": "Niche",
                    "func": tool_language_split, "needs_channel_stats": False},
    "chan_outlier": {"label": "Per-channel over/under", "cat": "Channel",
                     "func": tool_channel_outlier, "needs_channel_stats": True},
    "cadence":     {"label": "Upload cadence vs reach", "cat": "Channel",
                    "func": tool_cadence, "needs_channel_stats": True},
    "channels":    {"label": "Channels in niche (avg views + consistency)",
                    "cat": "Channel",
                    "func": tool_channels, "needs_channel_stats": False},
    "ai_summary":  {"label": "AI summary (Claude) — costs credit", "cat": "AI",
                    "func": tool_ai_summary, "needs_channel_stats": False},
    "charts":      {"label": "Distribution charts", "cat": "Visual",
                    "func": tool_charts, "needs_channel_stats": False},
}


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