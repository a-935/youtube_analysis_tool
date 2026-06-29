"""
Test the dashboard's analysis logic with FAKE data (no API key needed).
We build videos with KNOWN traits, then check each tool reports them correctly.
"""
import sys
sys.argv = ["test"]  # stop the __main__ demo from running on import

import importlib.util
spec = importlib.util.spec_from_file_location("ytd", "yt_dashboard.py")
ytd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ytd)


def make_video(vid, title, views, dur, age_days, subs, likes=None, comments=None,
               weekday="Mon", channel="ChanA"):
    likes = likes if likes is not None else views // 20
    comments = comments if comments is not None else views // 100
    return {
        "id": vid, "title": title, "channel": channel, "channel_id": "c_" + channel,
        "published": "2025-01-01T00:00:00Z", "thumbnail": "x",
        "views": views, "likes": likes, "comments": comments,
        "duration_sec": dur, "is_short": 0 < dur <= ytd.SHORTS_MAX_SECONDS,
        "age_days": age_days, "views_per_day": round(views / age_days, 1),
        "like_rate": round(likes / views, 4) if views else 0,
        "comment_rate": round(comments / views, 4) if views else 0,
        "weekday": weekday, "hour": 12,
        "subs": subs, "views_per_sub": round(views / subs, 2) if subs else 0,
    }


# Build a controlled dataset:
# SHORTS: high performers have emoji + are short; low performers don't.
# LONG-FORM: high performers are ~10 min; low are very long & old.
videos = [
    # --- Shorts (dur <= 180) ---
    make_video("s1", "Insane goal 😭🔥", 3_000_000, 30, 10, 50_000, weekday="Fri"),   # fast, emoji
    make_video("s2", "Best moments 🤯", 2_500_000, 45, 12, 80_000, weekday="Fri"),
    make_video("s3", "Top 5 plays 😎", 2_000_000, 60, 15, 5_000, weekday="Sat"),       # small chan breakout
    make_video("s4", "ranked grind clip", 900_000, 50, 400, 2_000_000, weekday="Mon"),  # slow, no emoji
    make_video("s5", "just a clip", 700_000, 40, 500, 3_000_000, weekday="Tue"),         # slow, no emoji
    make_video("s6", "random short", 600_000, 35, 600, 1_500_000, weekday="Wed"),
    # --- Long-form (dur > 180) ---
    make_video("l1", "I Tried Ranked for 24 Hours $1000", 5_000_000, 600, 20, 500_000, weekday="Sat"),
    make_video("l2", "Can He Hit This Shot?", 4_000_000, 720, 25, 600_000, weekday="Sat"),
    make_video("l3", "Funny RL Moments Compilation", 3_500_000, 540, 30, 400_000, weekday="Sun"),
    make_video("l4", "Greatest Goals of All Time", 1_000_000, 800, 1500, 800_000, weekday="Mon"),  # old coaster
    make_video("l5", "long boring analysis", 800_000, 1800, 1200, 900_000, weekday="Tue"),
    make_video("l6", "old tutorial", 700_000, 1500, 1400, 700_000, weekday="Wed"),
]

ds = {"topic": "rocket league", "videos": videos, "cost": 0, "from_cache": True}

print("=" * 60)
print("TEST 1: format split")
shorts, longform = ytd.by_format(videos)
print(f"  Shorts: {len(shorts)} (expect 6), Long: {len(longform)} (expect 6)")
assert len(shorts) == 6 and len(longform) == 6

print("\nTEST 2: outliers — fastest should be the high-velocity ones")
out = ytd.tool_outliers(ds)
sw = [v["title"] for v in out["result"]["shorts"]["fastest"]]
lw = [v["title"] for v in out["result"]["long"]["fastest"]]
print(f"  Short fastest: {sw}")
print(f"  Long fastest:  {lw}")
print(f"  Summary: {out['summary']}")

print("\nTEST 3: emoji impact — top Shorts should have MORE emoji than bottom")
em = ytd.TOOLS["emoji"]["func"](ds)
print(f"  {em['summary']}")
assert em["result"]["shorts"]["top"] >= em["result"]["shorts"]["bottom"]

print("\nTEST 4: duration — long-form top vs bottom seconds")
du = ytd.TOOLS["duration"]["func"](ds)
print(f"  {du['summary']}")

print("\nTEST 5: numbers/$ in title")
nu = ytd.TOOLS["numbers"]["func"](ds)
print(f"  {nu['summary']}")

print("\nTEST 6: small-channel breakouts — s3 (5k subs, 2M views) should lead")
bo = ytd.tool_small_breakouts(ds)
top = bo["result"]["shorts"]["top"][0]
print(f"  Top breakout: {top['title']} ({top['views_per_sub']}x subs)")
assert top["id"] == "s3"

print("\nTEST 7: saturation")
sa = ytd.tool_saturation(ds)
print(f"  {sa['summary']}")

print("\nTEST 8: language split (all Latin here)")
la = ytd.tool_language_split(ds)
print(f"  {la['summary']}")

print("\nTEST 9: upload timing")
ti = ytd.tool_upload_timing(ds)
print(f"  {ti['summary']}")

print("\nTEST 10: title length, caps, like rate, comment rate, hook")
for k in ["title_len", "caps", "like_rate", "comment_rate", "hook"]:
    o = ytd.TOOLS[k]["func"](ds)
    print(f"  {o['name']}: {o['summary']}")

print("\nTEST 11: channel-stat tools should ask for fetch when missing")
co = ytd.tool_channel_outlier(ds)
print(f"  {co['summary']}")
assert "channel stats" in co["summary"]

print("\nTEST 12: tier filter")
small = ytd.by_tier(videos, "small")
large = ytd.by_tier(videos, "large")
print(f"  Small (<100k subs): {[v['id'] for v in small]} (expect s1,s2,s3)")
print(f"  Large (>1M subs):   {[v['id'] for v in large]}")
assert {v["id"] for v in small} == {"s1", "s2", "s3"}

print("\nTEST 13: channel-stat tools work once stats present")
for v in videos:
    v["channel_avg_views"] = 1_000_000
    v["channel_uploads_per_month"] = 4
    v["channel_views_per_month"] = 4_000_000
co2 = ytd.tool_channel_outlier(ds)
print(f"  {co2['summary']}")
cad = ytd.tool_cadence(ds)
print(f"  {cad['summary']}")

print("\nTEST 14: niche freshness — these test videos are old, so NOT a spike")
fr = ytd.tool_freshness(ds)
print(f"  {fr['summary']}")
assert "TREND SPIKE" not in fr["summary"]

print("\nTEST 15: data_warning fires on tiny comparison groups")
w = ytd.data_warning("emoji", ytd.TOOLS["emoji"]["func"](ds))
print(f"  emoji warning: {w}")
assert w is not None and "Small sample" in w
# a descriptive tool with no threshold should never warn
assert ytd.data_warning("saturation", ytd.tool_saturation(ds)) is None
print("  saturation warning: None (correct — no threshold)")

print("\nTEST 16: refresh_ages recomputes age/velocity from 'published', not the frozen value")
from datetime import datetime, timezone, timedelta
pub_dt = datetime.now(timezone.utc) - timedelta(days=4)
fresh = [{
    "id": "r1", "published": pub_dt.isoformat().replace("+00:00", "Z"),
    "views": 40_000, "age_days": 1, "views_per_day": 40_000,   # deliberately stale
}]
ytd.refresh_ages(fresh)
print(f"  age_days recomputed: {fresh[0]['age_days']} (expect ~4), "
      f"views/day: {fresh[0]['views_per_day']} (expect ~10,000)")
assert fresh[0]["age_days"] == 4
assert abs(fresh[0]["views_per_day"] - 10_000) < 1
# a junk date must not crash and must leave the stored values intact
junk = [{"id": "r2", "published": "not-a-date", "views": 5, "age_days": 9, "views_per_day": 1}]
ytd.refresh_ages(junk)
assert junk[0]["age_days"] == 9
print("  junk date left untouched (no crash)")

print("\nTEST 17: cadence ignores channels with only ONE video in the search (brand filter)")
brand_ds = {"topic": "rocket league", "from_cache": True, "cost": 0, "videos": [
    # endemic creator: 2 videos in-search, modest reach
    {**make_video("e1", "clip A", 500_000, 30, 5, 40_000, channel="CreatorX"),
     "channel_avg_views": 300_000, "channel_uploads_per_month": 8,
     "channel_views_per_month": 2_400_000},
    {**make_video("e2", "clip B", 400_000, 28, 6, 40_000, channel="CreatorX"),
     "channel_avg_views": 300_000, "channel_uploads_per_month": 8,
     "channel_views_per_month": 2_400_000},
    # non-endemic brand: ONE tangential video, enormous channel-wide reach
    {**make_video("b1", "we sponsor esports", 9_000, 40, 3, 5_000_000, channel="MegaBrand"),
     "channel_avg_views": 1_000_000, "channel_uploads_per_month": 20,
     "channel_views_per_month": 240_000_000},
]}
cad = ytd.tool_cadence(brand_ds)
ranked_names = [name for name, _ in cad["result"]["channels"]]
print(f"  ranked channels: {ranked_names}  |  {cad['summary']}")
assert "MegaBrand" not in ranked_names, "brand with 1 video should be excluded"
assert "CreatorX" in ranked_names
print("  MegaBrand correctly excluded; CreatorX kept ✅")

print("\nTEST 18: comment_rate verdict — small min_base lets the real range show, but the")
print("          default floor still protects proportion metrics (emoji) from false signals")
# comment-rate values live ~0.02-0.05; slow draw ~3x more comments per view (reach artifact)
assert ytd._verdict(0.019, 0.054, min_base=0.01) == "winners lower"
# emoji-style proportions (0-1) must STILL read 'no clear difference' at a 14-pt gap
assert ytd._verdict(0.65, 0.51) == "no clear difference"
# and two near-equal comment rates must NOT manufacture a signal
assert ytd._verdict(0.030, 0.031, min_base=0.01) == "no clear difference"
print("  0.019 vs 0.054 (floor 0.01) -> winners lower; 0.65 vs 0.51 -> no clear difference ✅")

print("\nTEST 19: ALL-CAPS tool carries its weak/format-dependent caveat in the summary")
caps_out = ytd.TOOLS["caps"]["func"](ds)
print(f"  {caps_out['summary']}")
assert "weak, Shorts-only" in caps_out["summary"]

print("\nTEST 20: channels 'above' count uses the ALL-TIME median, or is omitted without it")
# without channel stats -> above_count is None (no tautological ~half count)
no_cs = ytd.tool_channels({"topic": "rl", "from_cache": True, "cost": 0, "videos": [
    make_video("c1", "a", 900_000, 30, 5, 40_000, channel="Chan1"),
    make_video("c2", "b", 300_000, 30, 6, 40_000, channel="Chan1"),
    make_video("c3", "c", 100_000, 30, 7, 40_000, channel="Chan1"),
]})
row = no_cs["result"]["shorts"][0]
print(f"  no channel stats -> above_count={row['above_count']} (expect None)")
assert row["above_count"] is None
# with an all-time median of 250k, only the 900k and 300k videos beat it -> 2
with_cs = ytd.tool_channels({"topic": "rl", "from_cache": True, "cost": 0, "videos": [
    {**make_video("d1", "a", 900_000, 30, 5, 40_000, channel="Chan2"), "channel_avg_views": 250_000},
    {**make_video("d2", "b", 300_000, 30, 6, 40_000, channel="Chan2"), "channel_avg_views": 250_000},
    {**make_video("d3", "c", 100_000, 30, 7, 40_000, channel="Chan2"), "channel_avg_views": 250_000},
]})
row2 = with_cs["result"]["shorts"][0]
print(f"  all-time median 250k -> {row2['above_count']} of {row2['n']} beat it (expect 2 of 3)")
assert row2["above_count"] == 2

print("\nTEST 21: baseline min-views floor — a near-dead VOD does NOT drag the niche median")
base_vids = [make_video(f"v{i}", "real", 200_000, 600, 100, 500_000) for i in range(5)]
clean = ytd.tool_outliers({"topic": "rl", "from_cache": True, "cost": 0, "videos": base_vids})
clean_base = clean["result"]["long"]["baseline"]
polluted = ytd.tool_outliers({"topic": "rl", "from_cache": True, "cost": 0,
                              "videos": base_vids + [make_video("dead", "VOD", 30, 600, 100, 500_000)]})
polluted_base = polluted["result"]["long"]["baseline"]
print(f"  baseline without floor would drop; with floor: clean={clean_base}, +deadVOD={polluted_base}")
assert clean_base == polluted_base, "a sub-500-view VOD must not change the baseline"

print("\nTEST 22: age-fair baseline — fresh videos are judged against fresh peers, not one")
print("          age-blind median that decayed old videos would deflate")
# 40 OLD long videos: age 120, ~120k views -> 1,000 views/day (lifetime-average, decayed)
# 40 FRESH long videos: age 2,  ~10k  views -> 5,000 views/day (caught at peak)
old_vids  = [make_video(f"o{i}", "old",  120_000, 600, 120, 500_000) for i in range(40)]
fresh_vids = [make_video(f"f{i}", "fresh", 10_000, 600,   2, 500_000) for i in range(40)]
banded = ytd._age_banded_baseline(old_vids + fresh_vids)
band_fn, bands, overall = banded
print(f"  bands: {[(b['min_age'], b['max_age'], round(b['median'])) for b in bands]}")
print(f"  overall (age-blind) median = {round(overall)}")
assert len(bands) == 2, "80 videos -> 2 bands of ~40"
fresh_bar = band_fn({"age_days": 2})
old_bar = band_fn({"age_days": 120})
print(f"  fresh video compared to {round(fresh_bar):,}/day; old video to {round(old_bar):,}/day")
assert abs(fresh_bar - 5000) < 1 and abs(old_bar - 1000) < 1
# the age-blind median (~3000) would have rated a fresh video 5000/3000=1.7x; age-fair = 1.0x
assert fresh_bar > overall > old_bar, "banding must separate fresh from old; blind median sits between"
print("  fresh judged vs ~5000 not the blended ~3000 -> no fake inflation ✅")

print("\nTEST 23: small samples fall back to ONE band (= the old whole-niche median)")
tiny = [make_video(f"t{i}", "v", 200_000, 600, 50, 500_000) for i in range(6)]
_, tiny_bands, tiny_overall = ytd._age_banded_baseline(tiny)
print(f"  6 videos -> {len(tiny_bands)} band (expect 1), median {round(tiny_overall):,}")
assert len(tiny_bands) == 1, "below ~40 videos there must be a single band (old behaviour)"

print("\nTEST 24: top_bottom is AGE-FAIR — 'fast' is no longer just 'young'")
# Two age bands. Fresh videos have higher RAW velocity than old ones, so raw ranking would
# put ALL fresh on top. Age-fair ranking should put the high-velocity videos from BOTH ages
# in the 'fast' group.
fresh_hi = [make_video(f"fh{i}", "fresh fast", 20_000, 30, 2, 500_000) for i in range(20)]
fresh_lo = [make_video(f"fl{i}", "fresh slow", 10_000, 30, 2, 500_000) for i in range(20)]
old_hi   = [make_video(f"oh{i}", "old fast",  100_000, 30, 100, 500_000) for i in range(20)]
old_lo   = [make_video(f"ol{i}", "old slow",   50_000, 30, 100, 500_000) for i in range(20)]
mixed = fresh_hi + fresh_lo + old_hi + old_lo
top_fair, bot_fair = ytd.top_bottom(mixed)                    # default = age-fair
top_raw, bot_raw = ytd.top_bottom(mixed, metric="views_per_day")  # old behaviour
fair_ages = {("fresh" if v["age_days"] < 50 else "old") for v in top_fair}
raw_ages  = {("fresh" if v["age_days"] < 50 else "old") for v in top_raw}
print(f"  age-fair 'fast' group contains: {fair_ages} (expect both)")
print(f"  raw 'fast' group contains: {raw_ages} (expect fresh only)")
assert fair_ages == {"fresh", "old"}, "age-fair split must include winners of BOTH ages"
assert raw_ages == {"fresh"}, "raw split is the young-biased behaviour we're fixing"

print("\nTEST 25: channel clustering / effective-n (Kish)")
# 48 from one channel + 4 channels of 1 each = 52 videos, 5 channels, but effective << 52
clustered = ([make_video(f"z{i}", "v", 100_000, 30, 10, 50_000, channel="ZeeVoke") for i in range(48)]
             + [make_video(f"x{i}", "v", 100_000, 30, 10, 50_000, channel=f"Chan{i}") for i in range(4)])
cl = ytd.channel_clustering(clustered)
print(f"  {cl['videos']} videos, {cl['channels']} channels, top5={cl['top5_share']:.0%}, "
      f"effective_n={cl['effective_n']}")
assert cl["channels"] == 5
assert cl["effective_n"] < 5, "one channel dominating must crush the effective sample below the channel count"

print("\nTEST 26: breakouts evict '- Topic' auto-channels")
bo_ds = {"topic": "x", "from_cache": True, "cost": 0, "videos": [
    {**make_video("auto", "ART TRACK", 200_000, 30, 30, 99, channel="KLEAVE - Topic"),
     "views_per_sub": 2020.2},
    {**make_video("real", "real clip", 500_000, 30, 30, 5_000, channel="RealCreator"),
     "views_per_sub": 100.0},
]}
bo = ytd.tool_small_breakouts(bo_ds)
top_names = [v["channel"] for v in bo["result"]["shorts"]["top"]]
print(f"  breakout channels: {top_names}")
assert "KLEAVE - Topic" not in top_names, "'- Topic' auto-channel must be filtered out"
assert "RealCreator" in top_names

print("\nTEST 27: like/comment-rate demoted to diagnostics (no winners verdict)")
lr = ytd.TOOLS["like_rate"]["func"](ds)
print(f"  {lr['summary']}")
assert "Diagnostic" in lr["summary"] and "winners" not in lr["summary"].lower()

print("\nTEST 28: saturation reports PER-FORMAT effective-n (pooled would double-count)")
# 'Both' posts in both formats; pooled clustering would treat it as 2 independent voices.
sat_vids = (
    [make_video(f"s{i}", "short", 100_000, 30, 10, 50_000, channel="Both") for i in range(10)]
    + [make_video(f"l{i}", "long", 100_000, 600, 10, 50_000, channel="Both") for i in range(10)]
    + [make_video(f"o{i}", "short", 100_000, 30, 10, 50_000, channel=f"C{i}") for i in range(10)]
)
sat = ytd.tool_saturation({"topic": "x", "from_cache": True, "cost": 0, "videos": sat_vids})
r = sat["result"]
print(f"  {sat['summary']}")
assert "effective_n_shorts" in r and "effective_n_long" in r, "must expose per-format effective-n"
assert "effective_n" not in r, "pooled single effective_n should be gone"
# Long is all one channel ('Both') -> effective 1; pooled would have looked larger
assert r["effective_n_long"] == 1.0
print(f"  Shorts eff-n={r['effective_n_shorts']}, Long eff-n={r['effective_n_long']} (per-format ✅)")

print("\n" + "=" * 60)
print("ALL TESTS PASSED ✅")
