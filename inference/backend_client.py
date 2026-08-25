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


async def post_tracks(camera_id: str, tracks: list[dict]) -> None:
    """
    tracks: list of {"track_id": str, "class": str, "bbox": [x1,y1,x2,y2], "confidence": float}
    """
    payload = {
        "camera_id": camera_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "tracks": tracks,
    }
    start = time.monotonic()
    try:
        resp = await _client.post("/tracks", json=payload)
        resp.raise_for_status()
        elapsed_ms = (time.monotonic() - start) * 1000
        # Inference-side timing, independent of backend's own FPS/latency log,
        # so the two can be cross-checked per the sanity-check requirement.
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
