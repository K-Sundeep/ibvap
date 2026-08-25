"""
Direct HTTP + WebSocket bridge between inference and the dashboard.
No broker (matches PROJECT_CONTEXT.md section 3: "no message queue").

Flow:
    inference --POST /tracks--> backend --broadcast--> dashboard (WebSocket /ws/tracks)

Track payload contract (confirmed with user):
{
  "camera_id": "cam_01",
  "timestamp": "2026-08-26T10:15:32.451Z",
  "tracks": [
    {"track_id": "17", "class": "human", "bbox": [x1, y1, x2, y2], "confidence": 0.91}
  ]
}
"""

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("ibvap.tracks")
router = APIRouter()

# Connected dashboard clients
_ws_clients: list[WebSocket] = []

# Backend-side per-camera stream stats — kept independent of whatever
# inference logs on its own end, so the two numbers can be cross-checked.
_last_seen: dict[str, float] = {}
_frame_counts: dict[str, int] = defaultdict(int)


@router.websocket("/ws/tracks")
async def ws_tracks(websocket: WebSocket) -> None:
    await websocket.accept()
    _ws_clients.append(websocket)
    logger.info(f"dashboard client connected (total={len(_ws_clients)})")
    try:
        while True:
            # Dashboard doesn't need to send anything; this just keeps the
            # connection open and detects disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_clients.remove(websocket)
        logger.info(f"dashboard client disconnected (total={len(_ws_clients)})")


@router.post("/tracks")
async def post_tracks(payload: dict) -> dict:
    camera_id = payload.get("camera_id", "unknown")
    now = time.monotonic()

    # --- Backend-side FPS / latency logging ---
    _frame_counts[camera_id] += 1
    last = _last_seen.get(camera_id)
    if last is not None:
        gap = now - last
        fps = 1.0 / gap if gap > 0 else 0.0
        logger.info(
            f"[{camera_id}] backend-observed fps={fps:.2f} "
            f"gap={gap * 1000:.1f}ms frame_count={_frame_counts[camera_id]}"
        )
    _last_seen[camera_id] = now

    # --- Broadcast to connected dashboard clients ---
    dead: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)

    return {"status": "ok", "clients_notified": len(_ws_clients) - len(dead)}
