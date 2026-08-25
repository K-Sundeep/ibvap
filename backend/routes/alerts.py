"""
Live alert push (Phase 2 extension).

Every event created via POST /events (see events.py) is pushed to connected
alert clients immediately over WebSocket — no polling. Direct HTTP/WebSocket
only, no broker, consistent with PROJECT_CONTEXT.md section 3.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("ibvap.alerts")
router = APIRouter()

_ws_clients: list[WebSocket] = []


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    await websocket.accept()
    _ws_clients.append(websocket)
    logger.info(f"alert client connected (total={len(_ws_clients)})")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_clients.remove(websocket)
        logger.info(f"alert client disconnected (total={len(_ws_clients)})")


async def broadcast_alert(event: dict) -> None:
    """Call this right after inserting a new event row (see events.py)."""
    dead: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)
