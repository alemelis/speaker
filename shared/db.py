"""Shared SQLite module for FOMO tag management and play tracking."""

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
    tag_id  TEXT PRIMARY KEY,
    kind    TEXT NOT NULL CHECK (kind IN ('track', 'album')),
    query   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plays (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id    TEXT NOT NULL,
    kind      TEXT NOT NULL,
    query     TEXT NOT NULL,
    played_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    source    TEXT NOT NULL DEFAULT 'nfc'
);

CREATE INDEX IF NOT EXISTS idx_plays_tag ON plays(tag_id);
CREATE INDEX IF NOT EXISTS idx_plays_at  ON plays(played_at);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    return conn


def get_tag(conn, tag_id):
    row = conn.execute(
        "SELECT tag_id, kind, query FROM tags WHERE tag_id = ?", (str(tag_id),)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def all_tags(conn):
    rows = conn.execute(
        "SELECT tag_id, kind, query FROM tags ORDER BY tag_id"
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_tag(conn, tag_id, kind, query):
    conn.execute(
        "INSERT INTO tags (tag_id, kind, query) VALUES (?, ?, ?) "
        "ON CONFLICT(tag_id) DO UPDATE SET kind = excluded.kind, query = excluded.query",
        (str(tag_id), kind, query),
    )
    conn.commit()


def delete_tag(conn, tag_id):
    cur = conn.execute("DELETE FROM tags WHERE tag_id = ?", (str(tag_id),))
    conn.commit()
    return cur.rowcount > 0


def log_play(conn, tag_id, kind, query, source="nfc"):
    conn.execute(
        "INSERT INTO plays (tag_id, kind, query, source) VALUES (?, ?, ?, ?)",
        (str(tag_id), kind, query, source),
    )
    conn.commit()


def recent_plays(conn, limit=50):
    rows = conn.execute(
        "SELECT id, tag_id, kind, query, played_at, source FROM plays "
        "ORDER BY played_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def play_counts(conn, limit=20):
    rows = conn.execute(
        "SELECT query, kind, COUNT(*) as count, MAX(played_at) as last_played "
        "FROM plays GROUP BY query, kind ORDER BY count DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
