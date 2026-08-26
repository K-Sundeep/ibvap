#!/usr/bin/env python3
"""
IBVAP — query_events.py
Read-only sanity check against db/ibvap.db for Phase 2 fence-crossing testing.
Confirms an intrusion event exists with the right camera_id/type/track_id, and
that its snapshot file actually exists on disk (not just a path string).

Doesn't touch backend/inference — just reads the SQLite file directly, so it
works even if the backend API itself isn't fully wired for querying yet.

Usage:
    python scripts/query_events.py
    python scripts/query_events.py --camera_id cam1 --type intrusion --since_minutes 15
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

DB_PATH_DEFAULT = "db/ibvap.db"


def main():
    p = argparse.ArgumentParser(description="Query IBVAP events table for testing")
    p.add_argument("--db", default=DB_PATH_DEFAULT, help="path to SQLite db (default: %(default)s)")
    p.add_argument("--camera_id", default=None, help="filter to one camera, e.g. cam1")
    p.add_argument("--type", default="intrusion", help="event type filter (default: %(default)s), use '' for any")
    p.add_argument("--since_minutes", type=int, default=30, help="only events in the last N minutes")
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args()

    if not os.path.exists(args.db):
        print(f"DB not found at '{args.db}'. Has the backend run at least once (it creates the file "
              f"on first startup from backend/models.py)? Pass --db if it lives elsewhere.")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Confirm the table exists before assuming the schema in the project doc was
    # implemented as-is — backend lead may have named it differently.
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r["name"] for r in cur.fetchall()]
    if "event" not in tables:
        print(f"No 'event' table found. Tables present in this DB: {tables}")
        print("If the backend lead used a different table name, rerun with the right one hardcoded, "
              "or tell me the actual name and I'll adjust this script.")
        sys.exit(1)

    since_ts = (datetime.utcnow() - timedelta(minutes=args.since_minutes)).isoformat()

    query = "SELECT * FROM event WHERE timestamp >= ?"
    params = [since_ts]
    if args.camera_id:
        query += " AND camera_id = ?"
        params.append(args.camera_id)
    if args.type:
        query += " AND type = ?"
        params.append(args.type)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(args.limit)

    cur.execute(query, params)
    rows = cur.fetchall()

    if not rows:
        print(f"No events found (camera_id={args.camera_id or 'any'}, type={args.type or 'any'}, "
              f"last {args.since_minutes} min).")
        print("If you just triggered a test crossing: check inference logs for a 'crossing detected' "
              "line and backend logs for the POST before assuming this script is wrong — the gap "
              "could be anywhere upstream of the DB.")
        sys.exit(1)

    print(f"{len(rows)} event(s) found:\n")
    ok_count = 0
    for r in rows:
        row = dict(r)
        snapshot = row.get("snapshot_path")
        snapshot_exists = bool(snapshot) and os.path.exists(snapshot)

        print(f"id={row.get('id')}  camera_id={row.get('camera_id')}  type={row.get('type')}  "
              f"track_id={row.get('track_id')}  confidence={row.get('confidence')}")
        print(f"    timestamp     = {row.get('timestamp')}")
        print(f"    snapshot_path = {snapshot}  (exists on disk: {snapshot_exists})")
        print(f"    clip_path     = {row.get('clip_path')}")
        meta = row.get("metadata_json")
        if meta:
            try:
                print(f"    metadata      = {json.loads(meta)}")
            except (TypeError, ValueError):
                print(f"    metadata (raw)= {meta}")
        print()

        if row.get("camera_id") and row.get("type") == (args.type or row.get("type")) \
                and row.get("track_id") is not None and snapshot_exists:
            ok_count += 1

    print(f"Summary: {ok_count}/{len(rows)} event(s) have camera_id + correct type + track_id "
          f"+ a snapshot file that actually exists on disk.")
    if ok_count == 0:
        print("None of the events fully pass — see per-row detail above for what's missing "
              "(most likely candidate: snapshot_path is null or the file was never written).")
        sys.exit(1)


if __name__ == "__main__":
    main()
