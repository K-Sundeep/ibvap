"""
inference/rules/night_mode.py

Night-time detection support (PS 26187 capability #7). Combines a
motion mask (background subtraction) with the existing human/vehicle
detector to recover detections that are too faint/low-confidence for
the detector alone in low light — without just lowering the confidence
threshold globally, which would flood daytime streams with false
positives.

How it works, per frame:
  1. Check if the frame is "dark enough" to be night mode (mean pixel
     brightness below a threshold). If not, run detection completely
     normally — night-mode logic never touches daytime frames.
  2. If dark: enhance contrast (CLAHE) before running the detector, and
     run the detector at a LOWER confidence floor to get a superset of
     candidate boxes (confident + borderline).
  3. Confident detections (>= normal threshold) are kept outright.
  4. Borderline detections (below normal threshold but above the low
     floor) are kept ONLY if they overlap a motion blob from background
     subtraction — motion is used as corroborating evidence to rescue
     real-but-faint detections, not as a detector on its own. A
     borderline box with no motion behind it is almost always noise
     and is discarded.

This is a single detector inference pass per frame (on the enhanced
frame when dark), not two — running the model twice per frame would
hurt the target end-to-end latency budget for no real benefit, since
the low-threshold pass is already a superset of the high-threshold one.

Tunable thresholds (see NightModeProcessor.__init__) are defaults, not
verified numbers — see the note at the bottom of this file about why.
"""

from typing import Callable, List, Set, Tuple

import cv2
import numpy as np

BBox = List[float]


class NightModeProcessor:
    """
    One instance per camera stream — the background subtractor builds
    up a model of the static scene over time, so state must not be
    shared across cameras (or reset every frame).
    """

    def __init__(
        self,
        brightness_threshold: float = 60.0,
        low_conf: float = 0.15,
        base_conf: float = 0.35,
        motion_overlap_threshold: float = 0.15,
        min_motion_area: int = 150,
        bg_history: int = 300,
        bg_var_threshold: int = 16,
    ):
        """
        brightness_threshold: mean grayscale pixel value (0-255) below
            which a frame is treated as "night". ~60 is a starting
            point for dusk/night CCTV footage — needs checking against
            your actual test clip's lighting (see bottom-of-file note).
        low_conf: confidence floor for the night-mode detector pass —
            below this, even motion corroboration won't rescue a box;
            it's almost certainly noise.
        base_conf: the normal (daytime) detector confidence threshold —
            kept in sync with detector.py's default so night mode only
            changes behavior for the borderline confidence band, not
            the whole pipeline.
        motion_overlap_threshold: fraction of a candidate detection's
            own box area that must be covered by a motion blob for the
            detection to be "motion-corroborated". Deliberately measured
            against the detection box's area, not IoU against the
            motion blob — a motion blob from a moving human often
            merges with nearby motion (swaying branches, etc.) and can
            be much larger than the person; IoU would unfairly penalize
            a correct detection sitting inside a bigger blob.
        min_motion_area: motion blobs smaller than this (in pixels) are
            treated as sensor/compression noise, not real motion.
        bg_history / bg_var_threshold: passed straight to
            cv2.createBackgroundSubtractorMOG2 — see OpenCV docs if
            tuning further.
        """
        self.brightness_threshold = brightness_threshold
        self.low_conf = low_conf
        self.base_conf = base_conf
        self.motion_overlap_threshold = motion_overlap_threshold
        self.min_motion_area = min_motion_area

        # detectShadows=False: MOG2's shadow detection marks shadow
        # pixels with a separate gray value (127) that would need extra
        # mask handling. Night scenes rarely produce crisp, high-contrast
        # shadows the way bright daylight does, so disabling this keeps
        # mask thresholding simpler without losing much.
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=bg_history, varThreshold=bg_var_threshold, detectShadows=False
        )

        # Tracks which track_ids have already fired a night_movement
        # alert, so a lingering track doesn't re-alert every frame.
        # Cleared per-track via remove_track(), not automatically.
        self._alerted_tracks: Set[int] = set()

    def is_night(self, frame: np.ndarray) -> bool:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) < self.brightness_threshold

    def _enhance(self, frame: np.ndarray) -> np.ndarray:
        """CLAHE contrast enhancement on the L channel only, to boost
        visibility without blowing out color balance."""
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l_enhanced = clahe.apply(l_channel)
        enhanced_lab = cv2.merge((l_enhanced, a_channel, b_channel))
        return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    def _get_motion_boxes(self, frame: np.ndarray) -> List[BBox]:
        """
        Runs background subtraction on the RAW frame (not the enhanced
        one — CLAHE can introduce high-frequency artifacts that confuse
        the background model). Always called, even in daytime, so the
        background model is already warmed up by the time it gets dark
        rather than starting cold at dusk.
        """
        fg_mask = self._bg_subtractor.apply(frame)
        kernel = np.ones((5, 5), np.uint8)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)   # remove speckle noise
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)  # fill small gaps in a blob

        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in contours:
            if cv2.contourArea(c) < self.min_motion_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            boxes.append([float(x), float(y), float(x + w), float(y + h)])
        return boxes

    @staticmethod
    def _overlap_ratio(detection_box: BBox, motion_box: BBox) -> float:
        """Intersection area as a fraction of the DETECTION box's area (not IoU — see class docstring)."""
        x1 = max(detection_box[0], motion_box[0])
        y1 = max(detection_box[1], motion_box[1])
        x2 = min(detection_box[2], motion_box[2])
        y2 = min(detection_box[3], motion_box[3])
        if x2 <= x1 or y2 <= y1:
            return 0.0
        intersection = (x2 - x1) * (y2 - y1)
        box_area = (detection_box[2] - detection_box[0]) * (detection_box[3] - detection_box[1])
        return intersection / box_area if box_area > 0 else 0.0

    def process(self, frame: np.ndarray, model, detect_fn: Callable) -> Tuple[list, bool]:
        """
        detect_fn: pass detector.detect directly. Kept as a parameter
        (rather than importing detector.py here) so this module has no
        hard dependency on detector.py's import path — the caller wires
        them together. Returns detections of the SAME type detect_fn
        normally returns (detector.py's Detection dataclass), so
        tracker.py and main.py need no changes to consume night-mode
        output either way.

        Returns (detections, is_night) — the is_night flag is what
        main.py uses to decide whether a detection is alert-worthy as
        "night_movement", not just a normal detection.
        """
        night = self.is_night(frame)
        # Always update the motion model, night or day, so it's warmed
        # up by the time lighting actually drops.
        motion_boxes = self._get_motion_boxes(frame)

        if not night:
            return detect_fn(frame, model, conf=self.base_conf), False

        enhanced = self._enhance(frame)
        candidates = detect_fn(enhanced, model, conf=self.low_conf)

        kept = []
        for det in candidates:
            if det.confidence >= self.base_conf:
                kept.append(det)
                continue
            for mbox in motion_boxes:
                if self._overlap_ratio(det.bbox, mbox) >= self.motion_overlap_threshold:
                    kept.append(det)
                    break

        return kept, True

    def should_alert(self, track_id: int) -> bool:
        """
        Returns True the first time it's called for a given track_id,
        False every time after — so a track that stays visible at night
        for many frames fires one night_movement event, not one per
        frame. Call this only when night==True for the current frame.
        """
        if track_id in self._alerted_tracks:
            return False
        self._alerted_tracks.add(track_id)
        return True

    def remove_track(self, track_id: int) -> None:
        """Call when the tracker drops a track_id, so a later different object reusing that ID can alert again."""
        self._alerted_tracks.discard(track_id)


# --- On the threshold values above, and why I can't hand you verified numbers ---
# I don't have a GPU, your dark/night test clip, or network access to
# download YOLO weights in this sandbox (same limitation as the
# detection/tracking POC and the ANPR OCR test earlier this sprint) —
# so brightness_threshold=60, low_conf=0.15, and
# motion_overlap_threshold=0.15 above are reasonable STARTING POINTS
# from how MOG2 + CLAHE are typically tuned for CCTV-style footage, not
# numbers verified against your actual clip. See test_night_mode.py —
# run it on your dark clip and adjust these three first if behavior is
# off:
#   - Too many false positives (phantom detections in dark, empty
#     areas): raise motion_overlap_threshold, or raise low_conf.
#   - Still missing real people in the dark: lower low_conf further, or
#     lower motion_overlap_threshold (but expect more false positives
#     as a trade-off — this is inherently a precision/recall knob).
#   - Night mode triggering during daytime or never triggering at
#     night: adjust brightness_threshold — print gray.mean() on a few
#     known day/night frames from your clip to calibrate this number
#     directly rather than guessing.
