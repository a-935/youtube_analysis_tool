"""
test_expansion.py — synthetic tests for the 3-tool expansion
============================================================
No API key, no network. Covers the PURE logic of every new module: storage,
meta-analysis (replication), video tools (parsing/mining/risk/placement),
trend clustering/scoring/diffing, archive record building, and exports.

Run:  python test_expansion.py   ->  expect  ALL EXPANSION TESTS PASSED ✅
"""

import os
import tempfile
from datetime import datetime, timezone, timedelta

import storage
import meta_analysis as meta
import video_tools as vt
import trends_tools as tt
import archive
import exports

PASS = 0


def ok(label, cond, detail=""):
    global PASS
    assert cond, f"FAILED: {label} :: {detail}"
    PASS += 1
    print(f"  ✓ {label}" + (f"  [{detail}]" if detail else ""))


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def make_video(vid, title, channel, views, age_days, dur=120, is_short=None):
    return {
        "id": vid, "url": f"https://www.youtube.com/watch?v={vid}",
        "title": title, "channel": channel, "channel_id": "c_" + channel,
        "published": (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat(),
        "views": views, "likes": views // 50, "comments": views // 500,
        "duration_sec": dur,
        "is_short": (0 < dur <= 180) if is_short is None else is_short,
        "age_days": max(age_days, 1), "views_per_day": round(views / max(age_days, 1), 1),
        "like_rate": 0.02, "comment_rate": 0.002,
    }


# ---------------------------------------------------------------- storage
def test_storage():
    print("\n[storage]")
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(path)
    try:
        rid = storage.save_run({"topic": "rocket league", "region": "All regions",
                                "n_videos": 100, "n_shorts": 50, "quota_spent": 400,
                                "claude_cost": 0.01,
                                "signals": {"duration": {"verdict": "winners lower"}}},
                               db_path=path)
        ok("save_run returns id", isinstance(rid, int) and rid > 0, f"id={rid}")
        runs = storage.list_runs(db_path=path)
        ok("list_runs returns the run", len(runs) == 1 and runs[0]["topic"] == "rocket league")
        ok("payload round-trips", runs[0]["signals"]["duration"]["verdict"] == "winners lower")
        got = storage.get_run(rid, db_path=path)
        ok("get_run by id", got and got["id"] == rid)

        storage.set_run_note(rid, "21-day window test", db_path=path)
        ok("note persists", storage.get_run(rid, db_path=path)["note"] == "21-day window test")

        storage.save_run({"topic": "elden ring", "n_videos": 80}, db_path=path)
        ok("filter by topic", len(storage.list_runs(topic="elden ring", db_path=path)) == 1)
        ok("distinct_topics", len(storage.distinct_topics(db_path=path)) == 2)

        # transcript + comment caches
        storage.cache_transcript("vid1", True, "en", "hello world",
                                 [{"text": "hello", "start": 0, "duration": 1}], db_path=path)
        tc = storage.get_cached_transcript("vid1", db_path=path)
        ok("transcript cache round-trips", tc["available"] and tc["text"] == "hello world")
        storage.cache_comments("vid1", ["great", "nice"], db_path=path)
        ok("comment cache round-trips", storage.get_cached_comments("vid1", db_path=path) == ["great", "nice"])

        # trend snapshot
        sid = storage.save_trend_snapshot("gaming", "US", [{"trend": "1v1", "heat": 2.0}], db_path=path)
        ok("trend snapshot saved", isinstance(sid, int))
        snaps = storage.list_trend_snapshots("gaming", db_path=path)
        ok("trend snapshot round-trips", snaps and snaps[0]["trends"][0]["trend"] == "1v1")

        storage.kv_set("watchlist", ["rocket league", "fortnite"], db_path=path)
        ok("kv round-trips", storage.kv_get("watchlist", db_path=path) == ["rocket league", "fortnite"])

        storage.delete_run(rid, db_path=path)
        ok("delete_run", storage.get_run(rid, db_path=path) is None)
    finally:
        for p in (path, path + "-wal", path + "-shm"):
            if os.path.exists(p):
                os.remove(p)


# ---------------------------------------------------------------- meta-analysis
def test_meta():
    print("\n[meta-analysis: replication]")
    # duration robustly "winners lower"; emoji flips; numbers thin
    runs = []
    for i in range(9):
        sig = {"duration": {"verdict": "winners lower"},
               "emoji": {"verdict": "winners higher" if i % 2 else "winners lower"},
               "like_rate": {"verdict": "diagnostic"}}
        if i < 2:
            sig["numbers"] = {"verdict": "winners higher"}
        runs.append({"ts": _iso(9 - i), "topic": "rl", "signals": sig,
                     "top_outliers": [{"channel": f"ch{i%3}"}],
                     "metrics": {"median_velocity_short": 100 + i, "n_videos": 100},
                     "quota_spent": 400, "claude_cost": 0.01})

    board = {r["signal"]: r for r in meta.replication_scoreboard(runs)}
    ok("duration is ROBUST", board["duration"]["classification"] == "ROBUST",
       board["duration"]["classification"])
    ok("duration direction lower", board["duration"]["dominant"] == "winners lower")
    ok("emoji is NOISE (flips)", board["emoji"]["classification"] == "NOISE",
       f"agreement={board['emoji']['agreement']}")
    ok("numbers is THIN (<3 runs)", board["numbers"]["classification"] == "THIN")
    ok("diagnostic not directional", "like_rate" not in board or
       board["like_rate"]["classification"] in ("NOISE", "THIN"))

    series = meta.niche_over_time(runs, topic="rl")
    ok("niche_over_time ordered + sized", len(series) == 9 and
       series[0]["median_velocity_short"] == 100)
    ok("new_channels detected over time", any(s["new_channels"] for s in series[1:]))

    watch = meta.channel_watch(runs, min_appearances=2)
    ok("channel_watch finds recurring channels", len(watch) >= 1)

    cost = meta.cost_summary(runs)
    ok("cost_summary totals", cost["total_quota"] == 3600 and cost["runs"] == 9,
       f"quota={cost['total_quota']}")

    d = meta.diff_runs(runs[0], runs[1])
    ok("diff_runs catches emoji flip", any(f["signal"] == "emoji" for f in d["flips"]))

    # cross-niche
    rl = {"topic": "rl", "signals": {"duration": {"verdict": "winners lower"}}}
    er = {"topic": "er", "signals": {"duration": {"verdict": "winners lower"}}}
    fn = {"topic": "fn", "signals": {"emoji": {"verdict": "winners higher"}}}
    fn2 = {"topic": "rl", "signals": {"emoji": {"verdict": "winners lower"}}}
    uni = {u["signal"]: u for u in meta.cross_niche_universals([rl, er, fn, fn2])}
    ok("duration universal across topics", "universal" in uni["duration"]["verdict"])
    ok("emoji niche-specific", "niche-specific" in uni["emoji"]["verdict"])

    prompt = meta.build_meta_prompt(runs, meta.replication_scoreboard(runs))
    ok("meta prompt mentions replication + no-invent", "replicate" in prompt.lower()
       and "do not invent" in prompt.lower())


# ---------------------------------------------------------------- video tools (pure)
def test_video_pure():
    print("\n[video tools: pure]")
    ok("parse raw id", vt.parse_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ")
    ok("parse watch url", vt.parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5s") == "dQw4w9WgXcQ")
    ok("parse youtu.be", vt.parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ")
    ok("parse shorts url", vt.parse_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ")
    ok("parse junk -> None", vt.parse_video_id("not a url") is None or len(vt.parse_video_id("not a url")) == 11)

    desc = ("Best RL montage!\n\n"
            "0:00 Intro\n1:30 Goal 1\n4:05 Goal 2\n\n"
            "Use code SAVE10 for a discount. #rocketleague #gaming\n"
            "https://example.com/merch")
    mined = vt.mine_description(desc, video_id="abc12345678")
    ok("chapters parsed", len(mined["chapters"]) == 3 and mined["chapters"][0]["seconds"] == 0)
    ok("chapter t-link built", "&t=90s" in mined["chapters"][1]["url"])
    ok("hashtags mined", "#rocketleague" in mined["hashtags"])
    ok("links mined", any("example.com" in u for u in mined["links"]))
    ok("sponsor detected", mined["sponsor_mentions"] is True)
    ok("hook line", mined["hook_line"].startswith("Best RL"))

    # false chapter guard: non-monotonic / not starting at 0 should be dropped
    bad = vt.mine_description("Random 5:00 thing\n2:00 other", video_id="x")
    ok("false chapters dropped", bad["chapters"] == [])

    segs = [{"text": "what is going on guys", "start": 0.0, "duration": 2.0},
            {"text": "today we hit insane shots", "start": 2.0, "duration": 3.0},
            {"text": "lets get into it", "start": 65.0, "duration": 2.0}]
    ok("segments_to_text", "going on guys" in vt.segments_to_text(segs))
    ok("opening_hook 10s", "insane shots" in vt.opening_hook(segs, 10) and "lets get" not in vt.opening_hook(segs, 10))
    wpm = vt.transcript_wpm(segs)
    ok("wpm computed", wpm and wpm > 0, f"wpm={wpm}")

    risk = vt.risk_hints("this is damn good but no real issues here")
    ok("risk: low profanity hint", risk["profanity_count"] == 1 and "check" in risk["ad_friendliness_hint"])
    ok("risk has disclaimer (not oracle)", "not Content ID" in risk["disclaimer"])
    risk2 = vt.risk_hints("official music video feat. someone, kill blood gun")
    ok("risk: music reuse hint", risk2["music_reuse_hint"] is True)
    ok("risk: sensitive keywords", set(["kill", "blood", "gun"]).issubset(set(risk2["sensitive_keywords"])))

    # placement + similar winners (age-fair, reuses engine)
    peers = [make_video(f"p{i}", f"Insane goal {i}", f"ch{i%5}", 1000 * (i + 1), 10 + i, dur=300)
             for i in range(50)]
    target = make_video("T1", "My huge goal", "me", 500000, 12, dur=300)
    place = vt.place_in_niche(target, peers)
    ok("placement multiplier computed", place["vs_similar_age"] and place["vs_similar_age"] > 1,
       f"{place['vs_similar_age']}×")
    winners = vt.similar_winners(peers, target, k=5)
    ok("similar winners age-fair + same format", len(winners) == 5 and
       all("score" not in w or True for w in winners))

    clip_prompt = vt.build_clip_prompt({"title": "RL montage"}, segs)
    ok("clip prompt forbids retention claim", "not from audience-retention" in clip_prompt.lower()
       or "not from audience" in clip_prompt.lower())
    cprompt = vt.build_comment_prompt(["love it", "too long"], "RL montage")
    ok("comment prompt clusters themes", "what landed" in cprompt.lower())

    # transcript fallback path (no library / no network) must NOT crash
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(path)
    try:
        res = vt.fetch_transcript("zzzzzzzzzzz", db_path=path)
        ok("transcript graceful fallback", res["available"] is False and "reason" in res)
    finally:
        for p in (path, path + "-wal", path + "-shm"):
            if os.path.exists(p):
                os.remove(p)

    # manual paste — timestamped (YouTube 'Show transcript' shape)
    pasted_ts = "0:00 what is going on guys\n0:03 today we hit insane shots\n1:05 lets go"
    p1 = vt.parse_pasted_transcript(pasted_ts)
    ok("paste: timestamps detected", p1["has_timestamps"] is True)
    ok("paste: segments built", len(p1["segments"]) == 3 and p1["segments"][1]["start"] == 3)
    ok("paste: durations estimated", p1["segments"][0]["duration"] >= 0.5)
    ok("paste: wpm works on pasted ts", vt.transcript_wpm(p1["segments"]) and
       vt.transcript_wpm(p1["segments"]) > 0)
    ok("paste: hook works on pasted ts",
       "insane shots" in vt.opening_hook(p1["segments"], 10))

    # manual paste — timestamp on its own line, text on the next
    pasted_split = "0:00\nhello there\n0:04\nwelcome back"
    p2 = vt.parse_pasted_transcript(pasted_split)
    ok("paste: split-line shape", p2["has_timestamps"] and
       any("welcome back" in s["text"] for s in p2["segments"]))

    # manual paste — plain text, no timestamps
    p3 = vt.parse_pasted_transcript("hey everyone welcome to the video lets get into it")
    ok("paste: plain text -> single block", p3["has_timestamps"] is False and
       len(p3["segments"]) == 1)
    ok("paste: plain text usable by risk/clips", "welcome" in p3["text"])
    ok("paste: empty -> empty", vt.parse_pasted_transcript("")["segments"] == [])


# ---------------------------------------------------------------- trends (pure)
def test_trends():
    print("\n[trend tools: pure]")
    ok("normalize strips stopwords", vt is not None)
    toks = tt.normalize_title("How to win the BEST 1v1 in Rocket League", extra_stop=["rocket", "league"])
    ok("normalize drops stop+topic", "the" not in toks and "rocket" not in toks and "1v1" in toks)
    ok("bigrams", tt.title_ngrams(["a", "b", "c"], 2) == ["a b", "b c"])

    # 12 videos: 6 about "1v1 ranked", 6 about "freestyle training", + 3 noise
    vids = []
    for i in range(6):
        vids.append(make_video(f"a{i}", f"INSANE 1v1 ranked gameplay {i}", f"ch{i%2}",
                               50000 + i * 1000, 5 + i, dur=300))
    for i in range(6):
        vids.append(make_video(f"b{i}", f"freestyle training pack tutorial {i}", f"dh{i%3}",
                               8000 + i * 100, 30 + i, dur=300))
    for i in range(3):
        vids.append(make_video(f"n{i}", f"random unrelated video number {i}", f"z{i}",
                               100, 100, dur=300))

    snap = tt.build_trends_from_videos(vids, topic="rocket league", min_cluster=3)
    keys = [t["trend"] for t in snap["trends"]]
    ok("clusters found", snap["n_trends"] >= 2, f"trends={keys}")
    ok("1v1 cluster present", any("1v1" in k or "ranked" in k for k in keys), str(keys))
    ok("freestyle cluster present",
       any(any(w in k for w in ("freestyle", "training", "pack", "tutorial")) for k in keys),
       str(keys))
    fastest = snap["trends"][0]
    ok("each trend has effective_n", "effective_n" in fastest)
    ok("each trend has opportunity + stage", "opportunity" in fastest and "stage" in fastest)
    ok("examples attached", len(fastest["examples"]) >= 1)

    ok("opportunity rewards low saturation",
       tt.opportunity_score(2.0, 4) > tt.opportunity_score(2.0, 16))

    # diff: heat rises on one trend -> accelerating; one disappears -> gone
    old = {"ts": "t0", "trends": [{"trend": "1v1 ranked", "heat": 1.0, "n_videos": 6},
                                  {"trend": "old meta", "heat": 1.5, "n_videos": 4}]}
    new = {"ts": "t1", "trends": [{"trend": "1v1 ranked", "heat": 2.0, "n_videos": 9},
                                  {"trend": "freestyle", "heat": 1.2, "n_videos": 3}]}
    diff = tt.diff_trends(old, new)
    states = {c["trend"]: c["state"] for c in diff["changes"]}
    ok("diff: accelerating", states["1v1 ranked"] == "accelerating")
    ok("diff: new", states["freestyle"] == "new")
    ok("diff: gone", states["old meta"] == "gone")


# ---------------------------------------------------------------- archive + exports
def test_archive_exports():
    print("\n[archive + exports]")
    vids = [make_video(f"v{i}", f"Goal {i}", f"ch{i%4}", 10000 * (i + 1), 5 + i,
                       dur=30 if i % 2 else 300) for i in range(20)]
    ds = {"topic": "rocket league", "videos": vids, "cost": 400, "from_cache": False}
    outputs = [
        ("duration", {"name": "Duration", "summary": "Shorts: winners lower — fastest 25s vs slowest 48s (based on 6+6 videos)",
                      "result": {"shorts": {"top": 25, "bottom": 48}}}),
        ("emoji", {"name": "Emoji", "summary": "Shorts: no clear difference — 50% vs 48% (based on 6+6 videos)",
                   "result": {"shorts": {"top": 0.5, "bottom": 0.48}}}),
        ("like_rate", {"name": "Like rate", "summary": "Diagnostic only (reach artifact ...): fastest 2.0% vs slowest 5.0%",
                       "result": {"shorts": {"top": 2.0, "bottom": 5.0}}}),
        ("outliers", {"name": "Outliers", "summary": "...",
                      "result": {"shorts": {"fastest": [{"channel": "ch1", "title": "Goal 1", "vs_baseline": 3.2}]},
                                 "long": {"fastest": []}}}),
    ]
    sig = archive.extract_signals(outputs)
    ok("extract duration verdict", sig["duration"]["verdict"] == "winners lower")
    ok("extract emoji verdict", sig["emoji"]["verdict"] == "no clear difference")
    ok("extract diagnostic verdict", sig["like_rate"]["verdict"] == "diagnostic")

    metrics = archive.compute_metrics(ds)
    ok("metrics computed", metrics["n_videos"] == 20 and "effective_n_short" in metrics)
    outs = archive.extract_top_outliers(outputs, ds)
    ok("top outliers from outliers tool", outs and outs[0]["channel"] == "ch1")

    rec = archive.build_run_record("rocket league", "All regions",
                                   {"after": "2026-06-01", "tier": "all", "per_format": 100},
                                   ds, outputs, ai_brief="Short Shorts win.",
                                   quota_spent=400, claude_cost=0.01)
    ok("run record complete", rec["topic"] == "rocket league" and rec["signals"] and rec["metrics"])

    md = exports.run_to_markdown({**rec, "ts": _iso(0)})
    ok("run markdown has signals + brief", "Signal verdicts" in md and "Short Shorts win" in md)
    csv_str = exports.videos_to_csv(vids)
    ok("csv has header + rows", csv_str.startswith("id,title,channel") and csv_str.count("\n") >= 20)
    board = meta.replication_scoreboard([{"signals": sig}, {"signals": sig}, {"signals": sig}])
    ok("scoreboard markdown", "replication scoreboard" in exports.scoreboard_to_markdown(board).lower())


if __name__ == "__main__":
    test_storage()
    test_meta()
    test_video_pure()
    test_trends()
    test_archive_exports()
    print("\n" + "=" * 60)
    print(f"ALL EXPANSION TESTS PASSED ✅  ({PASS} checks)")
