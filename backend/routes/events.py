"""
Event creation (Phase 2 — THE FLOOR).

POST /events is called by inference when a rule fires (fence crossing,
loitering, etc). Row shape matches the event schema in PROJECT_CONTEXT.md
section 3 exactly — do not add fields here without updating that file first.

On creation, this also:
- saves a snapshot to local disk if snapshot_base64 is provided (schema field
  itself is still just snapshot_path — the path to what got saved)
- broadcasts the full event over the /ws/alerts WebSocket immediately
- fires a Telegram alert for type="intrusion" events (soft-fails if Telegram
  isn't configured — see alerting/telegram_bot.py)
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from models import insert_event, get_event
from snapshot_storage import save_snapshot
from routes.alerts import broadcast_alert
from alerting.telegram_bot import maybe_send_intrusion_alert

router = APIRouter()


class EventIn(BaseModel):
    camera_id: str
    type: str
    track_id: Optional[str] = None
    confidence: Optional[float] = None
    snapshot_path: Optional[str] = None
    snapshot_base64: Optional[str] = None  # if set, saved to disk; overrides snapshot_path
    clip_path: Optional[str] = None
    metadata_json: Optional[str] = None


@router.post("/events")
async def create_event(event: EventIn) -> dict:
    snapshot_path = event.snapshot_path
    if event.snapshot_base64:
        snapshot_path = save_snapshot(event.camera_id, event.snapshot_base64)

    new_id = insert_event(
        camera_id=event.camera_id,
        type=event.type,
        track_id=event.track_id,
        confidence=event.confidence,
        snapshot_path=snapshot_path,
        clip_path=event.clip_path,
        metadata_json=event.metadata_json,
    )

    row = get_event(new_id)
    await broadcast_alert(row)

    if event.type == "intrusion":
        await maybe_send_intrusion_alert(row)

    return {"status": "ok", "id": new_id, "snapshot_path": snapshot_path}
