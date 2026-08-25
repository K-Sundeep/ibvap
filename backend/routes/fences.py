"""
Virtual fence storage (Phase 2 — THE FLOOR).

One fence polygon per camera. Operator draws it in the frontend FenceEditor;
inference's rules/ module loads it to check crossing.
"""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import get_connection

router = APIRouter()


class FenceIn(BaseModel):
    camera_id: str
    polygon: list[list[float]]  # [[x, y], [x, y], ...]


@router.post("/fences")
def save_fence(fence: FenceIn) -> dict:
    if len(fence.polygon) < 3:
        raise HTTPException(status_code=400, detail="polygon needs at least 3 points")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO fences (camera_id, polygon)
        VALUES (?, ?)
        ON CONFLICT(camera_id) DO UPDATE SET
            polygon = excluded.polygon,
            created_at = CURRENT_TIMESTAMP
        """,
        (fence.camera_id, json.dumps(fence.polygon)),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "camera_id": fence.camera_id}


@router.get("/fences/{camera_id}")
def get_fence(camera_id: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT camera_id, polygon, created_at FROM fences WHERE camera_id = ?",
        (camera_id,),
    ).fetchone()
    conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=f"no fence saved for camera_id={camera_id}")

    return {
        "camera_id": row["camera_id"],
        "polygon": json.loads(row["polygon"]),
        "created_at": row["created_at"],
    }
