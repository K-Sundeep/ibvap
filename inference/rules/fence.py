"""
Virtual fence crossing rule (Phase 2 — THE FLOOR).

Loads a camera's fence polygon from the backend, checks each track's bbox
center against it, and fires an "intrusion" event (via backend_client.post_event)
the moment a track transitions from outside -> inside the fence.

Call `check_crossings(camera_id, tracks)` once per processed frame/batch,
right after `post_tracks()`.
"""

import json
import logging

import httpx

from backend_client import BACKEND_URL, post_event

logger = logging.getLogger("ibvap.inference.rules.fence")

# camera_id -> polygon (list of [x, y] points)
_fence_cache: dict[str, list[list[float]]] = {}

# (camera_id, track_id) -> was the track last seen inside the fence?
_track_state: dict[tuple[str, str], bool] = {}

_client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=httpx.Timeout(2.0))


async def load_fence(camera_id: str) -> list[list[float]] | None:
    """Fetch and cache a camera's fence polygon from the backend. Returns None if none saved."""
    try:
        resp = await _client.get(f"/fences/{camera_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        polygon = resp.json()["polygon"]
        _fence_cache[camera_id] = polygon
        return polygon
    except httpx.HTTPError as exc:
        logger.warning(f"[{camera_id}] failed to load fence: {exc}")
        return _fence_cache.get(camera_id)


def _point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Standard ray-casting point-in-polygon test."""
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (
            x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1
        ):
            inside = not inside
    return inside


def _bbox_center(bbox: list[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


async def check_crossings(camera_id: str, tracks: list[dict]) -> None:
    """
    tracks: same list passed to post_tracks() —
        [{"track_id": str, "class": str, "bbox": [x1,y1,x2,y2], "confidence": float}, ...]
    """
    polygon = _fence_cache.get(camera_id)
    if polygon is None:
        polygon = await load_fence(camera_id)
    if not polygon:
        return  # no fence configured for this camera yet

    for track in tracks:
        track_id = track["track_id"]
        center = _bbox_center(track["bbox"])
        is_inside = _point_in_polygon(center, polygon)

        key = (camera_id, track_id)
        was_inside = _track_state.get(key, False)

        if is_inside and not was_inside:
            # Outside -> inside transition: fence crossed.
            await post_event(
                camera_id=camera_id,
                type="intrusion",
                track_id=track_id,
                confidence=track.get("confidence"),
                metadata_json=json.dumps(
                    {"rule": "virtual_fence", "class": track.get("class")}
                ),
            )

        _track_state[key] = is_inside
