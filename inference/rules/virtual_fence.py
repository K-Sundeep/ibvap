"""
inference/rules/virtual_fence.py

Virtual fence / intrusion detection.

Core requirement (PS 26187, capability #5): detect when a tracked
object crosses an operator-defined polygon boundary — the "virtual
fence" — and emit a crossing event.

Deliberately kept SIMPLE, not clever: this is the Phase 2 floor
requirement and needs to be reliably correct in a live demo, not the
most sophisticated geometry. See the "Known limitation" note at the
bottom before trying to make this fancier — don't add smoothing or
prediction before reading that.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

Point = Tuple[float, float]
Polygon = List[Point]


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """
    Standard ray-casting point-in-polygon test.

    Casts a horizontal ray from `point` toward +infinity in x and counts
    how many polygon edges it crosses. Odd crossing count = inside,
    even = outside.

    Assumes `polygon` is simple (non-self-intersecting), which is what
    an operator-drawn fence editor produces. Works for convex and
    concave polygons alike.
    """
    x, y = point
    n = len(polygon)
    inside = False

    x1, y1 = polygon[0]
    for i in range(1, n + 1):
        x2, y2 = polygon[i % n]
        if y > min(y1, y2) and y <= max(y1, y2) and x <= max(x1, x2):
            if y1 != y2:
                x_intersect = (y - y1) * (x2 - x1) / (y2 - y1) + x1
            else:
                x_intersect = x1
            if x1 == x2 or x <= x_intersect:
                inside = not inside
        x1, y1 = x2, y2

    return inside


@dataclass
class CrossingEvent:
    track_id: int
    camera_id: str
    fence_id: str
    timestamp: float
    direction: str                   # "entering" | "exiting"
    class_name: Optional[str] = None
    point: Optional[Point] = None    # centroid at the moment of crossing
    confidence: Optional[float] = None       # detection confidence of the track at crossing time
    snapshot_path: Optional[str] = None      # filled in by the caller, not by VirtualFence —
                                              # this module has no frame data, only geometry


class VirtualFence:
    """
    One instance per (camera_id, polygon). Tracks each object's last
    known inside/outside state and fires a CrossingEvent on the frame
    that state flips.

    State is keyed by track_id — this must stay in sync with the
    tracker's lifecycle (see remove_track). A stale entry for a
    track_id that ByteTrack later recycles for a *different* object
    would produce a bogus crossing event; call remove_track when the
    tracker drops an ID.
    """

    def __init__(self, polygon: Polygon, camera_id: str, fence_id: str = "fence_1"):
        if len(polygon) < 3:
            raise ValueError("A polygon needs at least 3 points")
        self.polygon = polygon
        self.camera_id = camera_id
        self.fence_id = fence_id
        self._track_inside: Dict[int, bool] = {}

    def update(
        self,
        track_id: int,
        centroid: Point,
        timestamp: float,
        class_name: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> Optional[CrossingEvent]:
        """
        Call once per frame for each currently-tracked object. Returns
        a CrossingEvent only on the frame the track's inside/outside
        state changes; otherwise returns None.

        First sighting of a track_id: records its initial state but
        never fires an event — we don't know which side it "crossed
        from" if we've never seen it before, so treating the first
        sighting as a crossing would false-alert on every object
        already inside/near the fence when tracking starts.
        """
        current_inside = point_in_polygon(centroid, self.polygon)
        previous_inside = self._track_inside.get(track_id)

        self._track_inside[track_id] = current_inside

        if previous_inside is None:
            return None  # first sighting — establish baseline only

        if previous_inside == current_inside:
            return None  # no state change this frame

        direction = "entering" if current_inside else "exiting"

        return CrossingEvent(
            track_id=track_id,
            camera_id=self.camera_id,
            fence_id=self.fence_id,
            timestamp=timestamp,
            direction=direction,
            class_name=class_name,
            point=centroid,
            confidence=confidence,
            # snapshot_path deliberately left None here — VirtualFence only
            # ever sees a centroid, never the actual frame pixels, so it
            # can't capture an image. The caller (the service loop, which
            # already has the raw frame in hand) sets this right after
            # receiving the event. See inference/snapshot.py.
        )

    def remove_track(self, track_id: int) -> None:
        """Call when the tracker drops a track_id (occlusion timeout, left frame)."""
        self._track_inside.pop(track_id, None)

    def reset(self) -> None:
        """Clear all track state — call on stream restart/reconnect."""
        self._track_inside.clear()


# --- Known limitation (documented on purpose, not fixed here) ---
# This checks the CURRENT centroid only, not the full segment between
# the previous and current centroid. An object moving fast enough to
# fully cross a narrow polygon within a single frame gap (enters AND
# exits between two consecutive samples) would be missed, since we only
# ever sample two points: before and after, both outside.
#
# At the sprint's target latency (near real-time, ~20-30 FPS) and
# realistic pedestrian/vehicle speeds relative to a border virtual
# fence's width, this is very unlikely to matter for the demo. If it
# ever does, the fix is a segment-vs-polygon-edge intersection test
# using the previous and current centroid — not a smarter point test.
# Flagging this rather than pre-building it: untested complexity here
# is a bigger demo risk than a rare missed frame.
