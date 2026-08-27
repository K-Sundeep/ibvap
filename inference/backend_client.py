"""
Direct HTTP client for pushing track batches from inference to backend.
No broker in between (matches PROJECT_CONTEXT.md section 3).

Call `post_tracks()` from tracker.py once ByteTrack/BoT-SORT is wired in
(Phase 1) — one call per processed frame/batch, per camera.
"""

import logging
import os
import time

import httpx

logger = logging.getLogger("ibvap.inference.backend_client")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
_TIMEOUT = httpx.Timeout(2.0)

_client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=_TIMEOUT)


async def post_tracks(
    camera_id: str,
    tracks: list[dict],
    frame_width: int,
    frame_height: int,
    frame_id: int,
    fps: float | None = None,
    latency_ms: float | None = None,
) -> None:
    """
    tracks: list of {"track_id": int|str, "cls": str, "conf": float,
                      "bbox_px": [x1, y1, x2, y2]}   <- raw pixel corners
            (detector.py/tracker.py should produce this shape)

    Converts pixel bboxes to normalized [x, y, w, h] (0-1 fractions) before
    sending, per the contract in frontend/app/hooks/useTrackStream.js —
    the overlay is resolution-independent by design, so normalization has
    to happen here, the only place that knows the frame's actual size.
    """
    normalized_tracks = []
    for t in tracks:
        x1, y1, x2, y2 = t["bbox_px"]
        normalized_tracks.append({
            "track_id": t["track_id"],
            "cls": t["cls"],
            "conf": t["conf"],
            "bbox": [
                x1 / frame_width,
                y1 / frame_height,
                (x2 - x1) / frame_width,
                (y2 - y1) / frame_height,
            ],
        })

    payload = {
        "camera_id": camera_id,
        "frame_id": frame_id,
        "ts": time.time(),
        "fps": fps,
        "latency_ms": latency_ms,
        "tracks": normalized_tracks,
    }
    start = time.monotonic()
    try:
        resp = await _client.post("/tracks", json=payload)
        resp.raise_for_status()
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(f"[{camera_id}] posted {len(tracks)} tracks in {elapsed_ms:.1f}ms")
    except httpx.HTTPError as exc:
        logger.warning(f"[{camera_id}] failed to post tracks to backend: {exc}")

async def post_event(
    camera_id: str,
    type: str,
    track_id: str | None = None,
    confidence: float | None = None,
    metadata_json: str | None = None,
) -> None:
    """
    Create an event row in the backend's `events` table (schema per
    PROJECT_CONTEXT.md section 3). Called by rules/ when a rule fires
    (e.g. fence crossing -> type="intrusion").
    """
    payload = {
        "camera_id": camera_id,
        "type": type,
        "track_id": track_id,
        "confidence": confidence,
        "metadata_json": metadata_json,
    }
    try:
        resp = await _client.post("/events", json=payload)
        resp.raise_for_status()
        logger.info(f"[{camera_id}] event created: type={type} track_id={track_id}")
    except httpx.HTTPError as exc:
        logger.warning(f"[{camera_id}] failed to post event to backend: {exc}")
