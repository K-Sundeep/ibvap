"""
SQLite schema for IBVAP.

`events` table matches the event schema in PROJECT_CONTEXT.md section 3 exactly:
    id, camera_id, type, timestamp, track_id, confidence,
    snapshot_path, clip_path, metadata_json

`cameras` table is NOT defined in PROJECT_CONTEXT.md (only the event schema is
given there). The fields below (camera_id, name, rtsp_url, location, created_at)
are a placeholder assumption — confirm/adjust before Phase 1 wires up real ingest.

`events.camera_id` and `fences.camera_id` are plain TEXT with no FK to `cameras`:
nothing writes to `cameras` yet (ingest hasn't been built), so an enforced FK
would block fence/event creation entirely until camera registration exists.
Revisit once ingest registers real cameras.
"""

import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "ibvap.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()

    # Placeholder fields — not part of the PROJECT_CONTEXT.md schema, flagged above.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cameras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT UNIQUE NOT NULL,
            name TEXT,
            rtsp_url TEXT,
            location TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Exact match to the event schema in PROJECT_CONTEXT.md section 3.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT NOT NULL,
            type TEXT NOT NULL,
            timestamp REAL NOT NULL,
            track_id TEXT,
            confidence REAL,
            snapshot_path TEXT,
            clip_path TEXT,
            metadata_json TEXT
        )
        """
    )
    # Phase 2 — virtual fence storage. One fence polygon per camera (latest
    # save wins; not versioned). polygon is stored as a JSON array of
    # [x, y] points, e.g. "[[10,10],[500,10],[500,400],[10,400]]".
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS fences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT UNIQUE NOT NULL,
            polygon TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Phase 3 — ANPR blacklist. plate_text is normalized (uppercase, no
    # whitespace) on write so OCR noise/casing doesn't cause false negatives
    # on lookup.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL DEFAULT 'plate',
            value TEXT NOT NULL,
            list_type TEXT NOT NULL DEFAULT 'blacklist',
            note TEXT,
            created_at REAL NOT NULL,
            UNIQUE(kind, value)
        )
        """
    )

    conn.commit()
    conn.close()




def insert_event(
    camera_id: str,
    type: str,
    track_id: str | None = None,
    confidence: float | None = None,
    snapshot_path: str | None = None,
    clip_path: str | None = None,
    metadata_json: str | None = None,
) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO events (camera_id, type, timestamp, track_id, confidence, snapshot_path, clip_path, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (camera_id, type, time.time(), track_id, confidence, snapshot_path, clip_path, metadata_json),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_event(event_id: int) -> dict | None:
    """Fetch a single event row as a dict (used to broadcast/alert right after insert)."""
    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


if __name__ == "__main__":
    init_db()
    print(f"IBVAP DB initialized at {os.path.abspath(DB_PATH)}")
