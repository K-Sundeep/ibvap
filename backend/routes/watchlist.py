"""
Watchlist enrollment + lookup — currently plates only (Phase 3, ANPR).
`kind` is stored so face entries can reuse this table later without a
new endpoint, per frontend/app/lib/watchlistApi.js's contract.
"""

from typing import Optional
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import get_connection

router = APIRouter()


def _normalize(value: str) -> str:
    return value.strip().upper().replace(" ", "").replace("-", "")


class WatchlistIn(BaseModel):
    kind: str = "plate"
    value: str
    list_type: str = "blacklist"
    note: Optional[str] = None


@router.post("/watchlist", status_code=201)
def add_entry(entry: WatchlistIn) -> dict:
    value = _normalize(entry.value)
    if not value:
        raise HTTPException(status_code=400, detail="value cannot be empty")

    conn = get_connection()
    cur = conn.cursor()
    
    ...
    cur.execute(
        """
        INSERT INTO watchlist (kind, value, list_type, note, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (entry.kind, value, entry.list_type, entry.note, time.time()),
    )
    new_id = cur.lastrowid
    conn.commit()
    row = cur.execute("SELECT * FROM watchlist WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return dict(row)


@router.get("/watchlist")
def list_entries(kind: str = "plate") -> dict:
    conn = get_connection()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM watchlist WHERE kind = ? ORDER BY created_at DESC", (kind,)
    ).fetchall()
    conn.close()
    return {"entries": [dict(row) for row in rows]}


@router.delete("/watchlist/{entry_id}", status_code=204)
def delete_entry(entry_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM watchlist WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()


@router.get("/watchlist/check/{value}")
def check_value(value: str, kind: str = "plate") -> dict:
    """For inference/anpr_module.py — check an OCR'd plate against the list."""
    normalized = _normalize(value)
    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM watchlist WHERE kind = ? AND value = ?", (kind, normalized)
    ).fetchone()
    conn.close()
    if row is None:
        return {"matched": False, "value": normalized}
    return {"matched": True, **dict(row)}