#!/usr/bin/env python3
"""One-shot migration: tags.yaml -> fomo.db"""

import sqlite3
import sys
from urllib.parse import unquote_plus

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

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

TRACK_PREFIX = "tracks&query="
ALBUM_PREFIX = "albums&query="


def parse_entry(raw):
    if raw.startswith(TRACK_PREFIX):
        return "track", unquote_plus(raw[len(TRACK_PREFIX):])
    if raw.startswith(ALBUM_PREFIX):
        return "album", unquote_plus(raw[len(ALBUM_PREFIX):])
    return None, None


def migrate(yaml_path, db_path):
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)

    ok = skipped = 0
    for tag_id, raw in data.items():
        kind, query = parse_entry(str(raw))
        if kind is None:
            print(f"  SKIP {tag_id}: unrecognised format: {raw!r}")
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO tags (tag_id, kind, query) VALUES (?, ?, ?) "
            "ON CONFLICT(tag_id) DO UPDATE SET kind=excluded.kind, query=excluded.query",
            (str(tag_id), kind, query),
        )
        print(f"  OK   {tag_id} -> {kind}: {query}")
        ok += 1

    conn.commit()
    conn.close()
    print(f"\nMigrated {ok} tags, skipped {skipped}. DB: {db_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} tags.yaml fomo.db", file=sys.stderr)
        sys.exit(1)
    migrate(sys.argv[1], sys.argv[2])
