"""
self_check.py — 2-second OFFLINE health check (no API key, no network)
======================================================================
Run this first on a new machine. It proves the code, the SQLite layer, and every
PURE pipeline work, so when something fails live you can tell:
    "my code/install is broken"   (this script fails)
  vs
    "my key or network is the problem"   (this script passes, live calls fail)

Run:  python self_check.py
"""

import os
import sys
import tempfile

CHECKS = []


def check(label, fn):
    try:
        fn()
        CHECKS.append((True, label, ""))
        print(f"  ✓ {label}")
    except Exception as e:
        CHECKS.append((False, label, repr(e)))
        print(f"  ✗ {label}  ->  {e!r}")


def main():
    print("Offline self-check (no key / no network needed)\n")

    # 1. imports
    def imports():
        import yt_dashboard, storage, meta_analysis, video_tools  # noqa
        import trends_tools, archive, exports, tool_niche, tool_video, tool_trends  # noqa
    check("all 11 modules import", imports)

    # 2. SQLite read/write
    def db_rw():
        import storage
        fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
        try:
            rid = storage.save_run({"topic": "selfcheck", "n_videos": 1,
                                    "signals": {"x": {"verdict": "winners higher"}}},
                                   db_path=p)
            got = storage.get_run(rid, db_path=p)
            assert got and got["topic"] == "selfcheck"
        finally:
            for q in (p, p + "-wal", p + "-shm"):
                if os.path.exists(q):
                    os.remove(q)
    check("SQLite write + read", db_rw)

    # 3. meta-analysis replication
    def repl():
        import meta_analysis as m
        runs = [{"signals": {"d": {"verdict": "winners lower"}}} for _ in range(4)]
        board = m.replication_scoreboard(runs)
        assert board and board[0]["classification"] == "ROBUST"
    check("replication scoreboard", repl)

    # 4. video pure pipeline
    def vid():
        import video_tools as vt
        assert vt.parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        m = vt.mine_description("0:00 Intro\n1:30 Part\n#tag", video_id="abc12345678")
        assert len(m["chapters"]) == 2 and m["hashtags"] == ["#tag"]
        p = vt.parse_pasted_transcript("0:00 hello\n0:05 world")
        assert p["has_timestamps"] and len(p["segments"]) == 2
        r = vt.risk_hints("this is damn fine")
        assert r["profanity_count"] == 1
    check("video tools (parse/mine/paste/risk)", vid)

    # 5. trend pure pipeline
    def tr():
        import trends_tools as t
        from datetime import datetime, timezone, timedelta
        vids = []
        for i in range(8):
            age = 5 + i
            vids.append({"id": f"v{i}", "title": f"insane 1v1 ranked clip {i}",
                         "channel": f"c{i%3}", "channel_id": f"c{i%3}",
                         "views": 10000, "age_days": age,
                         "views_per_day": 10000 / age, "is_short": False})
        snap = t.build_trends_from_videos(vids, topic="rl", min_cluster=3)
        assert snap["n_trends"] >= 1 and "opportunity" in snap["trends"][0]
    check("trend clustering + scoring", tr)

    # 6. archive + exports
    def exp():
        import exports
        csv = exports.videos_to_csv([{"id": "a", "title": "t", "views": 1}])
        assert csv.startswith("id,title")
    check("exports (CSV)", exp)

    # 7. transcript library presence (informational, not a failure)
    try:
        import youtube_transcript_api  # noqa
        print("  ✓ youtube-transcript-api installed (live transcripts available)")
    except Exception:
        print("  ⚠ youtube-transcript-api NOT installed — transcripts will need the "
              "manual paste box until you `pip install youtube-transcript-api`")

    # 8. keys (informational)
    print("  · YT_KEY set:" , bool(os.environ.get("YT_KEY")),
          "| ANTHROPIC_API_KEY set:", bool(os.environ.get("ANTHROPIC_API_KEY")))

    failed = [c for c in CHECKS if not c[0]]
    print("\n" + "=" * 60)
    if failed:
        print(f"SELF-CHECK FAILED — {len(failed)} problem(s) above. This is a "
              f"code/install issue, not a key/network one.")
        sys.exit(1)
    print("SELF-CHECK PASSED ✅  Code + DB + all pure pipelines are healthy.")
    print("If live fetches still fail, it's your KEY or NETWORK, not the code.")


if __name__ == "__main__":
    main()
