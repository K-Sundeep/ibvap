"""
inference/rules/loitering.py

Loitering detection (PS 26187 "suspicious activity detection" support).
If a track's centroid stays inside a defined polygon zone continuously
for more than N seconds, emit a loitering event.

Reuses the same point_in_polygon test as virtual_fence.py — one
geometry implementation, not a parallel one — for the same reason
anpr_module.py's ANPRZone does.

Kept deliberately simple (per the "simple, not clever" standard from
virtual_fence.py): dwell time is tracked as a single continuous
in-zone interval per track, reset entirely the moment the track's
centroid leaves the zone. See the "Known limitation" note at the
bottom before adding grace periods or hysteresis.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from ibvap.inference.rules.virtual_fence import point_in_polygon, Point, Polygon


@dataclass
class LoiteringEvent:
    track_id: int
    camera_id: str
    zone_id: str
    timestamp: float
    dwell_seconds: float
    class_name: Optional[str] = None
    point: Optional[Point] = None


class LoiteringZone:
    """
    One instance per (camera_id, polygon, threshold). State is keyed by
    track_id: {"entry_time": float, "alerted": bool}. Must stay in sync
    with the tracker's lifecycle — call remove_track when the tracker
    drops an ID, same reasoning as VirtualFence and ANPRZone.
    """

    def __init__(
        self,
        polygon: Polygon,
        camera_id: str,
        zone_id: str = "loiter_zone_1",
        threshold_seconds: float = 30.0,
    ):
        if len(polygon) < 3:
            raise ValueError("A polygon needs at least 3 points")
        self.polygon = polygon
        self.camera_id = camera_id
        self.zone_id = zone_id
        self.threshold_seconds = threshold_seconds
        self._dwell_state: Dict[int, dict] = {}  # track_id -> {"entry_time": float, "alerted": bool}

    def update(
        self,
        track_id: int,
        centroid: Point,
        timestamp: float,
        class_name: Optional[str] = None,
    ) -> Optional[LoiteringEvent]:
        """
        Call once per frame for each currently-tracked object. Returns
        a LoiteringEvent the single frame dwell time first crosses
        threshold_seconds for a track; None on every other frame
        (including all frames after that one, for the same continuous
        stay — see should_alert reasoning in night_mode.py, same idea).
        """
        inside = point_in_polygon(centroid, self.polygon)

        if not inside:
            # Leaving the zone resets the dwell clock entirely — see
            # Known limitation below.
            self._dwell_state.pop(track_id, None)
            return None

        state = self._dwell_state.get(track_id)
        if state is None:
            self._dwell_state[track_id] = {"entry_time": timestamp, "alerted": False}
            return None

        if state["alerted"]:
            return None  # already fired for this continuous stay

        dwell_seconds = timestamp - state["entry_time"]
        if dwell_seconds < self.threshold_seconds:
            return None

        state["alerted"] = True
        return LoiteringEvent(
            track_id=track_id,
            camera_id=self.camera_id,
            zone_id=self.zone_id,
            timestamp=timestamp,
            dwell_seconds=dwell_seconds,
            class_name=class_name,
            point=centroid,
        )

    def remove_track(self, track_id: int) -> None:
        """Call when the tracker drops a track_id (occlusion timeout, left frame)."""
        self._dwell_state.pop(track_id, None)

    def reset(self) -> None:
        """Clear all dwell state — call on stream restart/reconnect."""
        self._dwell_state.clear()


# --- Known limitation (documented on purpose, not fixed here) ---
# Any single frame where the centroid tests as outside the polygon
# resets the dwell timer completely — including a one-frame flicker
# caused by detector/tracker jitter right at the zone boundary, not a
# real exit. For a person standing still near the edge of a zone, this
# could delay or prevent a real loitering alert if their centroid
# jitters in and out across the boundary.
#
# Not fixed here because a grace period (e.g. "still counts as inside
# if it was inside within the last K frames") is exactly the kind of
# untested complexity this sprint's rules have been avoiding — it would
# need real jitter data from an actual test clip to tune K correctly,
# and a wrong K is worse than the current simple-but-occasionally-early
# reset. If testing shows this actually happens on your clips, the fix
# is a short tolerance window here, not a rewrite.
