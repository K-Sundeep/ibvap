"""
inference/detector.py

Loads a pretrained YOLOv8/v10 model and exposes a single function,
`detect()`, that takes one frame and returns detections filtered to
human + vehicle classes only.

Pretrained only — per project convention, nothing here is trained from
scratch. Swap MODEL_PATH to try yolov8s.pt / yolov10n.pt / etc.

This module owns detection only. It does not track objects across frames
(see tracker.py) and does not write to the DB or call the backend
(see the service loop in main.py / backend_client.py) — kept stateless
and independently testable, per the architecture doc.
"""

from dataclasses import dataclass
from typing import List

import numpy as np
from ultralytics import YOLO

# --- COCO class IDs we care about for this project ---
# Pretrained YOLO uses COCO's 80 classes. We don't have custom
# "human"/"vehicle" classes trained, so we map the closest COCO
# equivalents and filter everything else out at inference time.
PERSON_CLASSES = {0: "person"}
VEHICLE_CLASSES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}
ALLOWED_CLASSES = {**PERSON_CLASSES, **VEHICLE_CLASSES}


@dataclass
class Detection:
    bbox: List[float]      # [x1, y1, x2, y2] in pixel coords
    confidence: float
    class_id: int
    class_name: str         # "person" | "car" | "motorcycle" | "bus" | "truck"
    category: str           # "human" | "vehicle" (what IBVAP actually cares about)


def _category_for(class_id: int) -> str:
    return "human" if class_id in PERSON_CLASSES else "vehicle"


def load_model(model_path: str = "yolov8n.pt", device=None) -> YOLO:
    """
    Load a pretrained YOLOv8/v10 model. Weights auto-download on first
    run if not already cached locally.

    device: 0 for first GPU, "cpu" for CPU, or None to let ultralytics
    pick automatically.
    """
    model = YOLO(model_path)
    if device is not None:
        model.to(device)
    return model


def detect(
    frame: np.ndarray,
    model: YOLO,
    conf: float = 0.35,
    iou: float = 0.45,
) -> List[Detection]:
    """
    Run detection on a single frame (BGR numpy array, as read by
    OpenCV / handed off from the ingest service).

    Returns a list of Detection objects filtered to ALLOWED_CLASSES only
    (human + vehicle). Anything else YOLO detects (COCO has 80 classes)
    is dropped here so downstream modules never see out-of-scope objects.
    """
    results = model.predict(
        source=frame,
        conf=conf,
        iou=iou,
        classes=list(ALLOWED_CLASSES.keys()),  # filter at inference time
        verbose=False,
    )

    detections: List[Detection] = []
    if not results:
        return detections

    result = results[0]
    if result.boxes is None:
        return detections

    for box in result.boxes:
        class_id = int(box.cls[0])
        if class_id not in ALLOWED_CLASSES:
            continue  # belt-and-suspenders, classes= filter above should already guarantee this

        x1, y1, x2, y2 = box.xyxy[0].tolist()
        confidence = float(box.conf[0])

        detections.append(
            Detection(
                bbox=[x1, y1, x2, y2],
                confidence=confidence,
                class_id=class_id,
                class_name=ALLOWED_CLASSES[class_id],
                category=_category_for(class_id),
            )
        )

    return detections


if __name__ == "__main__":
    # Quick standalone smoke test: python3 detector.py <image_or_video_frame_path>
    import sys
    import cv2

    if len(sys.argv) < 2:
        print("Usage: python3 detector.py <path_to_image>")
        raise SystemExit(1)

    test_model = load_model("yolov8n.pt")
    test_frame = cv2.imread(sys.argv[1])
    if test_frame is None:
        raise SystemExit(f"Could not read image: {sys.argv[1]}")

    dets = detect(test_frame, test_model)
    print(f"Found {len(dets)} detections:")
    for d in dets:
        print(f"  {d.category:8s} {d.class_name:12s} conf={d.confidence:.2f} bbox={d.bbox}")
