"""
inference/anpr_module.py

ANPR (Automatic Number Plate Recognition) — the Phase 3 differentiator
module. Scoped to ONE camera/zone only (see ANPRZone below) — this must
NOT run on every stream; OCR is comparatively expensive and this is a
controlled-zone demo capability, not a general-purpose capability.

Pipeline per triggered vehicle track:
  1. Zone trigger: vehicle track enters a defined polygon zone (reuses
     the same point-in-polygon logic as virtual_fence.py — one geometry
     implementation, not two parallel ones).
  2. Plate ROI: heuristic crop of the lower-center portion of the
     vehicle's bounding box (plates are front/rear-center on virtually
     every vehicle body style; no dedicated plate-detector model exists
     pretrained for this, and training one is out of scope/time budget).
  3. Perspective correction: find the most plate-like quadrilateral
     contour inside the ROI and warp it to a fixed rectangle. Falls
     back to the raw (uncorrected) ROI if no good quadrilateral is
     found — a skipped correction is far better than a failed read.
  4. OCR: EasyOCR (chosen over PaddleOCR for this module — lighter
     install, no separate PaddlePaddle framework dependency, good
     enough accuracy for demo-scale, alphanumeric plate text).
  5. Normalize: uppercase, strip anything that isn't A-Z/0-9.
  6. Blacklist/whitelist check — INTERFACE ONLY below (see
     `check_plate()` and the TODO block). Actual backend contract not
     yet defined — see my question at the end of this turn before
     wiring this up for real.

Requirements to add: easyocr
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from ibvap.inference.rules.virtual_fence import VirtualFence, Polygon, Point

# --- OCR backend ---
# Lazily imported/initialized: EasyOCR loads a ~50-100MB recognition
# model onto GPU/CPU at construction time, so we don't want that cost
# paid by every camera worker — only the one this module is enabled on.
_easyocr_reader = None


def _get_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        # gpu=True if a CUDA device is available; EasyOCR auto-detects,
        # but being explicit here avoids a silent CPU fallback mid-demo.
        _easyocr_reader = easyocr.Reader(["en"], gpu=True)
    return _easyocr_reader


@dataclass
class PlateReadResult:
    raw_text: str
    normalized_text: str
    ocr_confidence: float
    perspective_corrected: bool


@dataclass
class PlateMatchEvent:
    track_id: int
    camera_id: str
    zone_id: str
    timestamp: float
    plate_text: str
    ocr_confidence: float
    list_match: Optional[str] = None   # "blacklist" | "whitelist" | None (no match / not checked yet)
    snapshot_path: Optional[str] = None


# ---------------------------------------------------------------------
# 1. Zone trigger
# ---------------------------------------------------------------------

class ANPRZone:
    """
    Fires once per track, the frame it first enters the zone — not
    every frame it's inside. Deliberately reuses VirtualFence's
    point-in-polygon + inside/outside state machine rather than
    reimplementing zone-entry detection: it's the exact same geometry
    problem virtual_fence.py already solves, we just only care about
    the "entering" direction and only for vehicle-category tracks.
    """

    def __init__(self, polygon: Polygon, camera_id: str, zone_id: str = "anpr_zone_1"):
        self._fence = VirtualFence(polygon=polygon, camera_id=camera_id, fence_id=zone_id)
        self.zone_id = zone_id
        self.camera_id = camera_id

    def check_entry(
        self,
        track_id: int,
        centroid: Point,
        category: str,
        timestamp: float,
    ) -> bool:
        """Returns True on the single frame a vehicle track enters the zone."""
        if category != "vehicle":
            return False
        event = self._fence.update(track_id=track_id, centroid=centroid, timestamp=timestamp)
        return event is not None and event.direction == "entering"


# ---------------------------------------------------------------------
# 2. Plate ROI extraction (heuristic, no dedicated plate detector)
# ---------------------------------------------------------------------

def extract_plate_roi(frame: np.ndarray, vehicle_bbox: List[float]) -> np.ndarray:
    """
    Crops the lower-center band of a vehicle's bounding box, where
    plates sit on essentially every vehicle body style/angle likely to
    appear in a controlled ANPR zone (front-on or rear-on traffic).

    Not a learned detector — a fixed heuristic region. This is a known
    simplification: it assumes a roughly front/rear view of the vehicle
    (true for a controlled checkpoint zone with a fixed camera angle),
    not an arbitrary side/oblique view.
    """
    x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
    w = x2 - x1
    h = y2 - y1

    # Lower 45% of the box height, middle 70% of the box width.
    roi_y1 = y1 + int(h * 0.55)
    roi_y2 = y2
    roi_x1 = x1 + int(w * 0.15)
    roi_x2 = x2 - int(w * 0.15)

    roi_y1, roi_y2 = max(0, roi_y1), max(0, roi_y2)
    roi_x1, roi_x2 = max(0, roi_x1), max(0, roi_x2)

    return frame[roi_y1:roi_y2, roi_x1:roi_x2]


# ---------------------------------------------------------------------
# 3. Perspective correction (best-effort; falls back to raw ROI)
# ---------------------------------------------------------------------

def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # top-left: smallest x+y
    rect[2] = pts[np.argmax(s)]   # bottom-right: largest x+y
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right: smallest y-x
    rect[3] = pts[np.argmax(diff)]  # bottom-left: largest y-x
    return rect


def correct_perspective(roi: np.ndarray, output_size: Tuple[int, int] = (300, 100)) -> Tuple[np.ndarray, bool]:
    """
    Finds the most plate-like quadrilateral contour in the ROI and
    warps it to a fixed rectangle. Returns (image, corrected: bool) —
    if no suitable quadrilateral is found, returns the original ROI
    unchanged with corrected=False. A skipped correction still gets
    OCR'd; a botched correction (warping the wrong contour) would hurt
    accuracy more than leaving a mildly skewed plate as-is.
    """
    if roi.size == 0:
        return roi, False

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    roi_area = roi.shape[0] * roi.shape[1]
    best_quad = None
    best_area = 0.0

    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4:
            continue

        area = cv2.contourArea(approx)
        if area < 0.15 * roi_area or area > 0.95 * roi_area:
            continue  # too small to be a real plate region, or basically the whole ROI (likely noise)

        x, y, w, h = cv2.boundingRect(approx)
        if h == 0:
            continue
        aspect_ratio = w / h
        if not (1.8 <= aspect_ratio <= 5.5):
            continue  # real plates are wide rectangles; reject near-square/near-line contours

        if area > best_area:
            best_area = area
            best_quad = approx.reshape(4, 2)

    if best_quad is None:
        return roi, False  # fall back to raw ROI — no confident plate contour found

    rect = _order_corners(best_quad.astype("float32"))
    out_w, out_h = output_size
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype="float32")

    matrix = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(roi, matrix, (out_w, out_h))
    return warped, True


# ---------------------------------------------------------------------
# 4 & 5. OCR + normalization
# ---------------------------------------------------------------------

def normalize_plate_text(raw_text: str) -> str:
    """Uppercase, strip anything that isn't A-Z or 0-9."""
    return "".join(ch for ch in raw_text.upper() if ch.isalnum())


def read_plate(plate_image: np.ndarray, perspective_corrected: bool) -> Optional[PlateReadResult]:
    """
    Runs OCR on a (hopefully) plate-cropped image and returns the
    highest-confidence alphanumeric result, or None if nothing readable
    was found.
    """
    if plate_image.size == 0:
        return None

    reader = _get_reader()
    # allowlist restricts OCR to plate-plausible characters, cutting
    # down on noise reads from background text/logos caught in the crop
    results = reader.readtext(
        plate_image,
        allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        detail=1,
    )

    if not results:
        return None

    # Pick the highest-confidence text region rather than concatenating
    # everything found — a plate crop occasionally catches a second
    # smaller text blob (a sticker, a state code plate frame) and we
    # want the main plate string, not a merge of both.
    best = max(results, key=lambda r: r[2])  # r = (bbox, text, confidence)
    _, raw_text, confidence = best

    normalized = normalize_plate_text(raw_text)
    if not normalized:
        return None

    return PlateReadResult(
        raw_text=raw_text,
        normalized_text=normalized,
        ocr_confidence=float(confidence),
        perspective_corrected=perspective_corrected,
    )


# ---------------------------------------------------------------------
# 6. Blacklist / whitelist check
# ---------------------------------------------------------------------

def _edit_distance_at_most_one(a: str, b: str) -> bool:
    """
    True if the Levenshtein edit distance between a and b is 0 or 1.

    Deliberately not full Levenshtein DP — we only ever need a yes/no
    answer for distance <= 1, so this does it in O(n): same-length
    strings just need a single-position mismatch count; different
    lengths (by exactly 1) walk both strings together and allow exactly
    one skip. Early-exits on length difference > 1, which is the
    common case for genuine non-matches.
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False

    if len(a) == len(b):
        mismatches = sum(1 for x, y in zip(a, b) if x != y)
        return mismatches == 1

    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    i = j = 0
    skipped_once = False
    while i < len(longer) and j < len(shorter):
        if longer[i] == shorter[j]:
            i += 1
            j += 1
        else:
            if skipped_once:
                return False
            skipped_once = True
            i += 1  # skip one character in the longer string
    return True


def check_plate(plate_text: str, watchlist: Dict[str, str], fuzzy: bool = True) -> Optional[str]:
    """
    watchlist: {plate_text: "blacklist" | "whitelist"}, as produced by
    watchlist_client.WatchlistCache.snapshot().

    Exact match first (fast path — a plain dict lookup). If nothing
    exact and fuzzy=True, falls back to allowing a single-character
    edit (one substitution, insertion, or deletion) against every
    watchlist entry: OCR misreads a single character often enough
    (0/O, 1/I, 8/B, 5/S) that exact-only matching would miss real
    blacklist hits.

    The fuzzy fallback is O(n) in watchlist size per plate checked —
    fine at hackathon/demo scale (a watchlist of tens to low hundreds
    of entries); a much larger deployed watchlist would need indexing
    (e.g. by length + first two characters) before this fallback scan.
    """
    exact = watchlist.get(plate_text)
    if exact is not None:
        return exact

    if not fuzzy:
        return None

    for candidate, list_type in watchlist.items():
        if _edit_distance_at_most_one(plate_text, candidate):
            return list_type

    return None


# ---------------------------------------------------------------------
# End-to-end helper for one vehicle track, one frame
# ---------------------------------------------------------------------

def process_vehicle_for_anpr(
    frame: np.ndarray,
    track_id: int,
    vehicle_bbox: List[float],
    camera_id: str,
    zone_id: str,
    timestamp: float,
    watchlist: Dict[str, str],
) -> Optional[PlateMatchEvent]:
    """
    Runs the full ROI -> perspective correction -> OCR -> normalize ->
    watchlist pipeline for one vehicle, once (called only on zone
    entry, by the service loop — see main.py integration).
    """
    roi = extract_plate_roi(frame, vehicle_bbox)
    corrected_image, was_corrected = correct_perspective(roi)
    read_result = read_plate(corrected_image, was_corrected)

    if read_result is None:
        return None  # nothing readable — no event fired, not an error

    match = check_plate(read_result.normalized_text, watchlist)

    return PlateMatchEvent(
        track_id=track_id,
        camera_id=camera_id,
        zone_id=zone_id,
        timestamp=timestamp,
        plate_text=read_result.normalized_text,
        ocr_confidence=read_result.ocr_confidence,
        list_match=match,
    )
