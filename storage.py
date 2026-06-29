"""
storage.py — one SQLite layer shared by every tool
===================================================
The foundation for the expansion (Expansion Plan §2, §5). It persists:

  runs            — every niche-analysis run (the "summary archive"). Cross-run
                    replication is the validity test, so we store the per-signal
                    verdicts, the AI brief, diagnostics and top outliers.
  trend_snapshots — Tool 3 trend snapshots over time (so "rising vs last week"
                    can be computed once history accumulates).
  transcripts     — Tool 2 transcript cache ("never pay twice; survive restarts").
  comments        — Tool 2 top-comments cache.
  kv              — generic key/value scratch (watchlists etc.).

Design notes:
- Columns we want to *query on* (topic, ts, n_videos…) are real columns. The full,
  free-form record rides along in a JSON `payload` column. Best of both.
- Everything is defensive: a missing DB file is created; a corrupt row is skipped,
  never crashed on (graceful degradation, Plan §5).
- No engine import here — storage knows nothing about YouTube. Keeps it testable
  with plain dicts and a temp DB.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yt_store.db")


def _now():
    return datetime.now(timezone.utc).isoformat()


def connect(db_path=DEFAULT_DB):
    """Open (creating if needed) the DB and ensure the schema exists."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            topic TEXT, region TEXT,
            after TEXT, before TEXT, age_days INTEGER,
            tier TEXT, per_format INTEGER,
            n_videos INTEGER, n_shorts INTEGER,
            quota_spent INTEGER, claude_cost REAL,
            note TEXT,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_topic ON runs(topic);
        CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts);

        CREATE TABLE IF NOT EXISTS trend_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            genre TEXT, region TEXT,
            n_trends INTEGER,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trends_genre ON trend_snapshots(genre);

        CREATE TABLE IF NOT EXISTS transcripts (
            video_id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            available INTEGER,
            lang TEXT,
            text TEXT,
            segments TEXT
        );

        CREATE TABLE IF NOT EXISTS comments (
            video_id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            payload TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS kv (
            key TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()


# ---------------------------------------------------------------- runs (archive)
# A "run" dict is whatever Tool 1 wants to persist. We pull a few fields up into
# columns for querying; the rest is preserved verbatim in payload. Expected keys:
#   topic, region, after, before, age_days, tier, per_format,
#   n_videos, n_shorts, quota_spent, claude_cost,
#   signals (dict: signal_key -> {verdict, top, bottom, ...}),
#   ai_brief (str), diagnostics (str/dict), top_outliers (list), distributions (dict)
def save_run(run, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        ts = run.get("ts") or _now()
        cur = conn.execute(
            """INSERT INTO runs
               (ts, topic, region, after, before, age_days, tier, per_format,
                n_videos, n_shorts, quota_spent, claude_cost, note, payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ts, run.get("topic"), run.get("region"),
             run.get("after"), run.get("before"), run.get("age_days"),
             run.get("tier"), run.get("per_format"),
             run.get("n_videos"), run.get("n_shorts"),
             run.get("quota_spent"), run.get("claude_cost"),
             run.get("note"), json.dumps(run)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _row_to_run(row):
    try:
        payload = json.loads(row["payload"])
    except Exception:
        payload = {}
    payload["id"] = row["id"]
    payload["ts"] = row["ts"]
    if row["note"] is not None:
        payload["note"] = row["note"]
    return payload


def list_runs(topic=None, limit=200, db_path=DEFAULT_DB):
    """Newest-first. Returns full run dicts (payload merged with id/ts/note)."""
    conn = connect(db_path)
    try:
        if topic:
            rows = conn.execute(
                "SELECT * FROM runs WHERE topic=? ORDER BY ts DESC LIMIT ?",
                (topic, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_run(r) for r in rows]
    finally:
        conn.close()


def get_run(run_id, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None
    finally:
        conn.close()


def delete_run(run_id, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
        conn.commit()
    finally:
        conn.close()


def set_run_note(run_id, note, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute("UPDATE runs SET note=? WHERE id=?", (note, run_id))
        conn.commit()
    finally:
        conn.close()


def distinct_topics(db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT topic, COUNT(*) c FROM runs GROUP BY topic ORDER BY c DESC"
        ).fetchall()
        return [(r["topic"], r["c"]) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------- trend snapshots
def save_trend_snapshot(genre, region, trends, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        payload = {"genre": genre, "region": region, "trends": trends, "ts": _now()}
        cur = conn.execute(
            "INSERT INTO trend_snapshots (ts, genre, region, n_trends, payload) "
            "VALUES (?,?,?,?,?)",
            (payload["ts"], genre, region, len(trends), json.dumps(payload)))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_trend_snapshots(genre=None, limit=100, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        if genre:
            rows = conn.execute(
                "SELECT * FROM trend_snapshots WHERE genre=? ORDER BY ts DESC LIMIT ?",
                (genre, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trend_snapshots ORDER BY ts DESC LIMIT ?",
                (limit,)).fetchall()
        out = []
        for r in rows:
            try:
                p = json.loads(r["payload"])
            except Exception:
                continue
            p["id"] = r["id"]
            out.append(p)
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------- transcript cache
def cache_transcript(video_id, available, lang=None, text="", segments=None,
                     db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO transcripts "
            "(video_id, ts, available, lang, text, segments) VALUES (?,?,?,?,?,?)",
            (video_id, _now(), 1 if available else 0, lang, text,
             json.dumps(segments or [])))
        conn.commit()
    finally:
        conn.close()


def get_cached_transcript(video_id, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        r = conn.execute("SELECT * FROM transcripts WHERE video_id=?",
                         (video_id,)).fetchone()
        if not r:
            return None
        try:
            segs = json.loads(r["segments"])
        except Exception:
            segs = []
        return {"video_id": r["video_id"], "ts": r["ts"],
                "available": bool(r["available"]), "lang": r["lang"],
                "text": r["text"], "segments": segs}
    finally:
        conn.close()


# ---------------------------------------------------------------- comment cache
def cache_comments(video_id, payload, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO comments (video_id, ts, payload) VALUES (?,?,?)",
            (video_id, _now(), json.dumps(payload)))
        conn.commit()
    finally:
        conn.close()


def get_cached_comments(video_id, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        r = conn.execute("SELECT * FROM comments WHERE video_id=?",
                         (video_id,)).fetchone()
        if not r:
            return None
        try:
            return json.loads(r["payload"])
        except Exception:
            return None
    finally:
        conn.close()


# ---------------------------------------------------------------- generic kv
def kv_set(key, value, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute("INSERT OR REPLACE INTO kv (key, ts, value) VALUES (?,?,?)",
                     (key, _now(), json.dumps(value)))
        conn.commit()
    finally:
        conn.close()


def kv_get(key, default=None, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        r = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not r:
            return default
        try:
            return json.loads(r["value"])
        except Exception:
            return default
    finally:
        conn.close()
