"""
inference/tracker.py

Wraps ByteTrack: takes the per-frame detections produced by detector.py
and returns tracked objects with a stable track_id and trajectory
history (centroid path over time, per track).

Uses the `supervision` library's ByteTrack implementation
(pip install supervision) rather than a standalone `bytetrack` pip
package. Reasoning: it's actively maintained (Roboflow), has a clean
public update_with_detections() API, and — critically for this split —
it decouples tracking from detection cleanly, since detector.py and
tracker.py need to be separate, independently testable modules here
(unlike the Day-1 POC, which used ultralytics' combined model.track()).

Add to requirements.txt: supervision
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Tuple

import numpy as np
import supervision as sv

from ibvap.inference.detector import Detection


@dataclass
class TrackedObject:
    track_id: int
    class_id: int
    class_name: str
    category: str            # "human" | "vehicle"
    bbox: List[float]        # [x1, y1, x2, y2]
    confidence: float
    centroid: Tuple[float, float]
    trajectory: List[Tuple[float, float]]  # recent centroid history, oldest -> newest
    confirmed: bool           # True once seen for >= min_hits consecutive frames — see ObjectTracker


class ObjectTracker:
    """
    Stateful wrapper around sv.ByteTrack. One instance per camera stream
    — tracker state (track IDs, motion history) is per-camera and must
    not be shared across streams, or track IDs will collide/drift.
    """

    def __init__(
        self,
        frame_rate: int = 25,
        track_activation_threshold: float = 0.35,
        lost_track_buffer: int = 30,
        trajectory_length: int = 50,
        min_hits: int = 3,
    ):
        """
        frame_rate: expected FPS of the source stream (affects ByteTrack's
            internal timing assumptions).
        track_activation_threshold: min detection confidence to start a
            new track (kept in sync with detector.py's conf threshold).
        lost_track_buffer: frames to keep a track alive with no matching
            detection before dropping it (handles brief occlusion).
        trajectory_length: how many past centroids to retain per track_id
            for downstream rules (e.g. loitering, direction-of-travel).
        min_hits: consecutive frames a track_id must appear in before
            it's marked `confirmed=True`. Added this sprint for
            reliability: a 1-2 frame flicker track (a momentary false
            detection, or a real object that ByteTrack loses and
            reassigns a new ID to) would otherwise trigger a fence
            crossing, loitering timer, or night-movement alert exactly
            as readily as a real, stable track. Callers (main.py) are
            expected to gate all alert-producing rule checks on
            `confirmed` — this class only computes the flag, it doesn't
            enforce anything on its own.
        """
        self._tracker = sv.ByteTrack(
            frame_rate=frame_rate,
            track_activation_threshold=track_activation_threshold,
            lost_track_buffer=lost_track_buffer,
        )
        self._trajectory_length = trajectory_length
        self._trajectories: Dict[int, Deque[Tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=self._trajectory_length)
        )
        self.min_hits = min_hits
        self._hit_counts: Dict[int, int] = defaultdict(int)

    @staticmethod
    def _to_sv_detections(detections: List[Detection]) -> sv.Detections:
        if not detections:
            return sv.Detections.empty()

        xyxy = np.array([d.bbox for d in detections], dtype=np.float32)
        confidence = np.array([d.confidence for d in detections], dtype=np.float32)
        class_id = np.array([d.class_id for d in detections], dtype=int)

        return sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)

    def update(self, detections: List[Detection]) -> List[TrackedObject]:
        """
        Feed one frame's detections in, get back tracked objects with
        stable track_ids and updated trajectory history.

        Must be called once per frame, in order — ByteTrack is stateful
        and assumes sequential frames from a single stream.
        """
        sv_detections = self._to_sv_detections(detections)
        tracked = self._tracker.update_with_detections(sv_detections)

        # Rebuild class_name/category lookup since sv.Detections only
        # carries class_id, not our original Detection metadata.
        class_lookup = {d.class_id: (d.class_name, d.category) for d in detections}

        results: List[TrackedObject] = []
        for i in range(len(tracked)):
            track_id = int(tracked.tracker_id[i])
            class_id = int(tracked.class_id[i])
            bbox = tracked.xyxy[i].tolist()
            confidence = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
            class_name, category = class_lookup.get(class_id, ("unknown", "unknown"))

            x1, y1, x2, y2 = bbox
            centroid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

            self._trajectories[track_id].append(centroid)
            self._hit_counts[track_id] += 1
            confirmed = self._hit_counts[track_id] >= self.min_hits

            results.append(
                TrackedObject(
                    track_id=track_id,
                    class_id=class_id,
                    class_name=class_name,
                    category=category,
                    bbox=bbox,
                    confidence=confidence,
                    centroid=centroid,
                    trajectory=list(self._trajectories[track_id]),
                    confirmed=confirmed,
                )
            )

        return results

    def get_trajectory(self, track_id: int) -> List[Tuple[float, float]]:
        """Return the retained centroid history for a given track_id, if any."""
        return list(self._trajectories.get(track_id, []))

    def reset(self) -> None:
        """Clear all track state — call when a stream restarts/reconnects."""
        self._tracker.reset()
        self._trajectories.clear()
        self._hit_counts.clear()

    # Note (not fixed today — parameter tuning only, no structural
    # change): _hit_counts, like _trajectories, is never pruned for an
    # individual track_id that ByteTrack quietly drops after
    # lost_track_buffer frames — only reset() clears it, on a full
    # stream restart. Same growth profile as _trajectories already had;
    # fine for a demo run, worth a cleanup pass for a long-running
    # deployment.


if __name__ == "__main__":
    # Quick standalone smoke test with fabricated detections (no video needed).
    from ibvap.inference.detector import Detection

    tracker = ObjectTracker(frame_rate=25, min_hits=3)

    fake_frame_1 = [
        Detection(bbox=[100, 100, 150, 200], confidence=0.9, class_id=0,
                   class_name="person", category="human"),
    ]
    fake_frame_2 = [
        Detection(bbox=[105, 102, 155, 202], confidence=0.88, class_id=0,
                   class_name="person", category="human"),
    ]
    fake_frame_3 = [
        Detection(bbox=[110, 104, 160, 204], confidence=0.87, class_id=0,
                   class_name="person", category="human"),
    ]

    out1 = tracker.update(fake_frame_1)
    out2 = tracker.update(fake_frame_2)
    out3 = tracker.update(fake_frame_3)

    print("Frame 1 tracks:", out1, "-> confirmed should be False (hit 1)")
    print("Frame 2 tracks:", out2, "-> confirmed should be False (hit 2)")
    print("Frame 3 tracks:", out3, "-> confirmed should be True (hit 3, min_hits=3)")
