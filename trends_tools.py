"""
trends_tools.py — engine for Tool 3 (Trend Discovery)
=====================================================
The honest engine here is velocity + clustering, reusing Tool 1 (Plan §4).
Two modes:
  Snapshot — what's FAST right now (works day one). build_trends_from_videos().
  Trend    — what's ACCELERATING vs a previous snapshot (needs stored history).
             diff_trends(); the storage layer accumulates the history.

Reliability carried over (Plan §6):
  - age-fair velocity (engine._age_fair_scores) so "fast" isn't just "young".
  - effective-n per trend (engine.channel_clustering) so a "trend" that's really
    one channel says so.

PURE (unit-tested): normalize_title, title_ngrams, cluster_by_ngrams,
                    build_trends_from_videos, diff_trends, opportunity_score
LIVE (needs key): snapshot, category_trending
"""

import math
import re
import statistics
from collections import Counter

import yt_dashboard as engine

_STOP = {"the", "a", "an", "is", "of", "to", "in", "on", "my", "with", "for", "and",
         "vs", "how", "new", "best", "top", "you", "your", "it", "this", "that",
         "i", "we", "are", "be", "at", "by", "or", "as", "but", "not", "all"}
_WORD = re.compile(r"[a-z0-9]+")


def normalize_title(title, extra_stop=()):
    """Lowercase word tokens, minus stopwords and any topic words passed in."""
    stop = _STOP | {w.lower() for w in extra_stop}
    toks = _WORD.findall((title or "").lower())
    return [t for t in toks if t not in stop and len(t) > 1]


def title_ngrams(tokens, n=2):
    if n <= 1:
        return list(tokens)
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def cluster_by_ngrams(videos, topic="", min_cluster=3, n=2):
    """Greedy clustering: count title n-grams across the pool, treat frequent ones as
    trend seeds, and assign each video to the most-frequent seed n-gram it contains.
    Returns list of {key, videos} for clusters of >= min_cluster videos, plus the
    leftover 'unclustered' count. Deterministic."""
    extra = normalize_title(topic)
    grams_per_video = []
    df = Counter()
    for v in videos:
        toks = normalize_title(v.get("title", ""), extra_stop=extra)
        grams = set(title_ngrams(toks, n)) or set(toks)   # fall back to unigrams
        grams_per_video.append(grams)
        df.update(grams)

    # seeds = n-grams that appear in enough distinct videos, most frequent first
    seeds = [g for g, c in df.most_common() if c >= min_cluster]
    seed_rank = {g: i for i, g in enumerate(seeds)}

    buckets = {g: [] for g in seeds}
    unclustered = 0
    for v, grams in zip(videos, grams_per_video):
        cand = [g for g in grams if g in seed_rank]
        if not cand:
            unclustered += 1
            continue
        # assign to the highest-frequency (lowest-rank) seed for stability
        best = min(cand, key=lambda g: seed_rank[g])
        buckets[best].append(v)

    clusters = [{"key": g, "videos": vs} for g, vs in buckets.items()
                if len(vs) >= min_cluster]
    return clusters, unclustered


def opportunity_score(heat, n_videos):
    """velocity ÷ saturation, as a heuristic (Plan §4 'opportunity score'): reward high
    age-fair heat, penalise crowding. sqrt keeps it from collapsing on big clusters.
    Labelled as a heuristic in the UI, never a precise measure."""
    if n_videos <= 0:
        return 0.0
    return round(heat / math.sqrt(n_videos), 3)


def _trend_stats(cluster_videos):
    """Per-trend numbers. Assumes each video already has _pattern_score attached by the
    pool-wide age-fair pass (so heat is age-fair)."""
    vc = engine.channel_clustering(cluster_videos)
    views = [v.get("views", 0) for v in cluster_videos]
    ages = [v.get("age_days", 0) for v in cluster_videos]
    heat = statistics.median(v.get("_pattern_score", 0) for v in cluster_videos)
    n = len(cluster_videos)
    top1_share = (vc["top_channels"][0][1] / n) if vc.get("top_channels") and n else 0
    if n <= 6 and heat >= 1.3:
        stage = "emerging (few videos, fast) — opportunity"
    elif n >= 15:
        stage = "saturated (crowded)"
    else:
        stage = "developing"
    examples = sorted(cluster_videos, key=lambda v: v.get("_pattern_score", 0),
                      reverse=True)[:3]
    return {
        "n_videos": n,
        "median_views": int(statistics.median(views)) if views else 0,
        "total_views": sum(views),
        "median_age_days": int(statistics.median(ages)) if ages else 0,
        "channels": vc["channels"],
        "effective_n": vc["effective_n"],
        "top1_share": round(top1_share, 2),
        "heat": round(heat, 2),
        "opportunity": opportunity_score(heat, n),
        "stage": stage,
        "examples": [{"title": v.get("title"),
                      "url": v.get("url", f"https://www.youtube.com/watch?v={v.get('id','')}"),
                      "views": v.get("views"),
                      "score": round(v.get("_pattern_score", 0), 2)} for v in examples],
    }


def build_trends_from_videos(videos, topic="", min_cluster=3):
    """The core (pure given enriched videos). Age-fair-scores the whole pool, clusters by
    title n-grams, computes per-trend stats, and sorts by opportunity. This is Snapshot
    mode's brain — testable without any network."""
    engine._age_fair_scores(videos)   # attaches _pattern_score using pool-wide age bands
    clusters, unclustered = cluster_by_ngrams(videos, topic=topic, min_cluster=min_cluster)
    trends = []
    for c in clusters:
        stats = _trend_stats(c["videos"])
        stats["trend"] = c["key"]
        trends.append(stats)
    trends.sort(key=lambda t: t["opportunity"], reverse=True)
    return {
        "topic": topic,
        "n_videos": len(videos),
        "n_trends": len(trends),
        "unclustered": unclustered,
        "trends": trends,
        "note": ("Snapshot = what's FAST right now, not necessarily RISING. Run again "
                 "later and use Trend mode to see acceleration."),
    }


def diff_trends(old_snapshot, new_snapshot):
    """Trend mode: compare two snapshots of the same genre. Matches trends by key and
    classifies accelerating / cooling / new / gone. PURE — feed it two stored snapshots."""
    old = {t["trend"]: t for t in (old_snapshot or {}).get("trends", [])}
    new = {t["trend"]: t for t in (new_snapshot or {}).get("trends", [])}
    rows = []
    for key in sorted(set(old) | set(new)):
        o, nw = old.get(key), new.get(key)
        if o and nw:
            dv = round(nw["heat"] - o["heat"], 2)
            dn = nw["n_videos"] - o["n_videos"]
            if dv >= 0.3:
                state = "accelerating"
            elif dv <= -0.3:
                state = "cooling"
            else:
                state = "steady"
            rows.append({"trend": key, "state": state, "heat_delta": dv,
                         "videos_delta": dn, "heat_now": nw["heat"]})
        elif nw and not o:
            rows.append({"trend": key, "state": "new", "heat_delta": None,
                         "videos_delta": nw["n_videos"], "heat_now": nw["heat"]})
        else:
            rows.append({"trend": key, "state": "gone", "heat_delta": None,
                         "videos_delta": -o["n_videos"], "heat_now": 0})
    order = {"accelerating": 0, "new": 1, "steady": 2, "cooling": 3, "gone": 4}
    rows.sort(key=lambda r: (order[r["state"]], -(r["heat_delta"] or 0)))
    return {"from_ts": (old_snapshot or {}).get("ts"),
            "to_ts": (new_snapshot or {}).get("ts"), "changes": rows}


# ----------------------------------------------------------------- LIVE
def snapshot(genre, per_format=50, region_label="All regions", min_cluster=3):
    """LIVE. Fetch recent videos for a genre/seed and build the trend snapshot."""
    ds = engine.fetch_dataset(genre, balanced=True, videos_per_format=per_format,
                              region_label=region_label)
    result = build_trends_from_videos(ds["videos"], topic=genre, min_cluster=min_cluster)
    result["cost"] = ds.get("cost", 0)
    result["from_cache"] = ds.get("from_cache", False)
    return result


# YouTube's broad video categories (mostPopular chart). Coarse but real (§4a).
CATEGORY_IDS = {
    "Film & Animation": "1", "Autos & Vehicles": "2", "Music": "10",
    "Pets & Animals": "15", "Sports": "17", "Gaming": "20", "People & Blogs": "22",
    "Comedy": "23", "Entertainment": "24", "News & Politics": "25",
    "Howto & Style": "26", "Education": "27", "Science & Tech": "28",
}


def category_trending(region_code="US", category_id=None, limit=20):
    """LIVE. YouTube's mostPopular chart per region/category. Returns enriched videos."""
    params = {"part": "snippet,statistics,contentDetails", "chart": "mostPopular",
              "regionCode": region_code, "maxResults": min(limit, 50)}
    if category_id:
        params["videoCategoryId"] = category_id
    data = engine._get("videos", params)
    vids = []
    for item in data.get("items", []):
        st = item["statistics"]
        dur = engine.parse_duration(item["contentDetails"]["duration"])
        vids.append({
            "id": item["id"],
            "url": f"https://www.youtube.com/watch?v={item['id']}",
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "channel_id": item["snippet"]["channelId"],
            "published": item["snippet"]["publishedAt"],
            "views": int(st.get("viewCount", 0)),
            "likes": int(st.get("likeCount", 0)),
            "comments": int(st.get("commentCount", 0)),
            "duration_sec": dur,
            "is_short": 0 < dur <= engine.SHORTS_MAX_SECONDS,
        })
    engine.enrich(vids)
    return vids
