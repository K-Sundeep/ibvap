"""
ANPR blacklist enrollment + lookup (Phase 3 — ANPR wow module, locked per
PROJECT_CONTEXT.md section 5 status notes; face-watchlist descoped).

Plates are normalized (uppercase, whitespace stripped) on both enrollment
and lookup so OCR noise/casing differences don't cause false negatives.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import get_connection

router = APIRouter()


def _normalize(plate_text: str) -> str:
    return plate_text.strip().upper().replace(" ", "")


class BlacklistIn(BaseModel):
    plate_text: str
    label: Optional[str] = None


@router.post("/blacklist")
def enroll_plate(entry: BlacklistIn) -> dict:
    plate = _normalize(entry.plate_text)
    if not plate:
        raise HTTPException(status_code=400, detail="plate_text cannot be empty")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO blacklist (plate_text, label)
        VALUES (?, ?)
        ON CONFLICT(plate_text) DO UPDATE SET label = excluded.label
        """,
        (plate, entry.label),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "plate_text": plate}


@router.get("/blacklist")
def list_blacklist() -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT plate_text, label, enrolled_at FROM blacklist ORDER BY enrolled_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@router.get("/blacklist/check/{plate_text}")
def check_plate(plate_text: str) -> dict:
    """
    For inference's anpr_module.py: check an OCR'd plate against the
    blacklist to decide whether to fire a "plate_match" event.
    """
    plate = _normalize(plate_text)
    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT plate_text, label, enrolled_at FROM blacklist WHERE plate_text = ?",
        (plate,),
    ).fetchone()
    conn.close()
    if row is None:
        return {"matched": False, "plate_text": plate}
    return {"matched": True, **dict(row)}
