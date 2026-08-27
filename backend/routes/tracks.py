"""
Direct HTTP + WebSocket bridge between inference and the dashboard.
No broker (matches PROJECT_CONTEXT.md section 3: "no message queue").

One WebSocket connection per camera: /ws/tracks/{camera_id}.
Each dashboard tile subscribes only to its own camera's track stream.

Flow:
    inference --POST /tracks--> backend --broadcast (this camera only)--> dashboard
"""

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("ibvap.tracks")
router = APIRouter()

# Connected dashboard clients, grouped by camera_id — a client watching
# CAM-01 should never receive CAM-02's frames.
_ws_clients: dict[str, list[WebSocket]] = defaultdict(list)

_last_seen: dict[str, float] = {}
_frame_counts: dict[str, int] = defaultdict(int)


@router.websocket("/ws/tracks/{camera_id}")
async def ws_tracks(websocket: WebSocket, camera_id: str) -> None:
    await websocket.accept()
    _ws_clients[camera_id].append(websocket)
    logger.info(f"[{camera_id}] dashboard client connected (total={len(_ws_clients[camera_id])})")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_clients[camera_id].remove(websocket)
        logger.info(f"[{camera_id}] dashboard client disconnected (total={len(_ws_clients[camera_id])})")


@router.post("/tracks")
async def post_tracks(payload: dict) -> dict:
    camera_id = payload.get("camera_id", "unknown")
    now = time.monotonic()

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

    clients = _ws_clients.get(camera_id, [])
    dead: list[WebSocket] = []
    for ws in clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.remove(ws)

    return {"status": "ok", "clients_notified": len(clients) - len(dead)}