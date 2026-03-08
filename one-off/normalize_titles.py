#!/usr/bin/env python3
"""
One-off script: resolve exact owntone titles for all tags in fomo.db.

Usage:
    python normalize_titles.py fomo.db http://localhost:3689/api
"""

import sys
import time

import requests

sys.path.insert(0, "shared")
import db


def resolve(owntone_api, kind, query):
    owntone_type = "tracks" if kind == "track" else "albums"
    try:
        resp = requests.get(
            f"{owntone_api}/search",
            params={"type": owntone_type, "query": query, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get(owntone_type, {}).get("items", [])
        if not items:
            return None
        item = items[0]
        return item["title"] if kind == "track" else item["name"]
    except Exception as e:
        print(f"  ERROR searching {kind} {query!r}: {e}")
        return None


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} fomo.db http://owntone-host:3689/api", file=sys.stderr)
        sys.exit(1)

    db_path, owntone_api = sys.argv[1], sys.argv[2].rstrip("/")
    conn = db.connect(db_path)
    tags = db.all_tags(conn)
    print(f"Found {len(tags)} tags.\n")

    updated = skipped = failed = 0
    for row in tags:
        tag_id, kind, query = row["tag_id"], row["kind"], row["query"]
        exact = resolve(owntone_api, kind, query)
        if exact is None:
            print(f"  FAIL  [{tag_id}] {kind}: {query!r} — no result")
            failed += 1
        elif exact == query:
            print(f"  SAME  [{tag_id}] {kind}: {query!r}")
            skipped += 1
        else:
            print(f"  FIX   [{tag_id}] {kind}: {query!r} → {exact!r}")
            db.upsert_tag(conn, tag_id, kind, exact)
            updated += 1
        time.sleep(0.05)  # be gentle with owntone

    print(f"\nDone. Updated: {updated}, unchanged: {skipped}, failed: {failed}")


if __name__ == "__main__":
    main()
