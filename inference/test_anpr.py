"""
inference/test_anpr.py

Standalone ANPR test: run detector + tracker + ANPRZone + the plate
pipeline on a real clip of a few vehicles passing through a defined
zone, and report what got read.

I can't run this myself and hand you real accuracy numbers — I don't
have your clip, a GPU, or network access to EasyOCR's model downloads
in this environment (same reason the Day-1 detection+tracking POC had
to be run on your Kaggle/RunPod box, not here). This script is built to
make reporting accuracy on your end as easy as possible: run it, then
either eyeball the printed reads against the annotated output video, or
pass --ground-truth for an automatic accuracy number.

Run (no ground truth — just inspect the reads):
  python3 test_anpr.py --source zone_clip.mp4 --out anpr_test_output.mp4

Run (with ground truth for an accuracy %):
  python3 test_anpr.py --source zone_clip.mp4 --ground-truth truth.json

  truth.json format — one entry per vehicle that passes through the
  zone, in the order they enter it:
    ["KA05MN1234", "MH12AB4321", "DL3CAA0001"]

Zone polygon: same fractions-of-frame convention as
rules/test_virtual_fence.py, hardcoded below — adjust to where vehicles
actually cross in your clip.
"""

import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.append(os.path.dirname(__file__))
from ibvap.inference.detector import load_model, detect
from ibvap.inference.tracker import ObjectTracker
from ibvap.inference.anpr_module import ANPRZone, process_vehicle_for_anpr

# Fractions of frame width/height — a zone roughly across the middle of
# the frame. Adjust to match where vehicles pass through in your clip.
TEST_ZONE_FRACTIONS = [
    (0.30, 0.35),
    (0.70, 0.35),
    (0.70, 0.75),
    (0.30, 0.75),
]


def scale_polygon(fractions, width, height):
    return [(x * width, y * height) for x, y in fractions]


def main():
    parser = argparse.ArgumentParser(description="Standalone ANPR test")
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", default="anpr_test_output.mp4")
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--ground-truth", default=None, help="Path to a JSON list of expected plate strings, in entry order")
    args = parser.parse_args()

    ground_truth = None
    if args.ground_truth:
        with open(args.ground_truth) as f:
            ground_truth = json.load(f)

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open source: {args.source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    polygon = scale_polygon(TEST_ZONE_FRACTIONS, width, height)
    print(f"ANPR test zone (pixels): {polygon}")

    model = load_model(args.model)
    tracker = ObjectTracker(frame_rate=int(fps))
    zone = ANPRZone(polygon=polygon, camera_id="test_cam", zone_id="test_anpr_zone")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.out, fourcc, fps, (width, height))

    reads = []  # in the order vehicles were read, for ground-truth comparison
    frame_idx = 0
    watchlist = {}  # empty — this test is about OCR accuracy, not watchlist matching

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        timestamp = time.time()

        detections = detect(frame, model, conf=args.conf)
        tracked = tracker.update(detections)

        for obj in tracked:
            if obj.category != "vehicle":
                continue

            entered = zone.check_entry(
                track_id=obj.track_id, centroid=obj.centroid, category=obj.category, timestamp=timestamp
            )
            if entered:
                event = process_vehicle_for_anpr(
                    frame=frame,
                    track_id=obj.track_id,
                    vehicle_bbox=obj.bbox,
                    camera_id="test_cam",
                    zone_id="test_anpr_zone",
                    timestamp=timestamp,
                    watchlist=watchlist,
                )
                if event:
                    reads.append(event.plate_text)
                    print(
                        f"[frame {frame_idx}] READ track_id={obj.track_id} "
                        f"plate='{event.plate_text}' confidence={event.ocr_confidence:.2f}"
                    )
                else:
                    reads.append(None)
                    print(f"[frame {frame_idx}] track_id={obj.track_id} entered zone but NO readable plate")

        # --- draw for visual confirmation ---
        poly_pts = np.array([(int(x), int(y)) for x, y in polygon], dtype=np.int32)
        cv2.polylines(frame, [poly_pts], isClosed=True, color=(0, 200, 200), thickness=3)
        for obj in tracked:
            x1, y1, x2, y2 = [int(v) for v in obj.bbox]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 200, 0), 2)
        writer.write(frame)

    cap.release()
    writer.release()

    print(f"\nDone. {len(reads)} vehicle(s) entered the zone.")
    print(f"Reads: {reads}")
    print(f"Annotated output saved to: {args.out}")

    if ground_truth is not None:
        correct = sum(1 for r, gt in zip(reads, ground_truth) if r == gt)
        total = len(ground_truth)
        if len(reads) != len(ground_truth):
            print(
                f"\nWARNING: {len(reads)} reads vs {total} ground-truth entries — "
                f"counts don't match (missed a vehicle entry, or a false zone trigger). "
                f"Accuracy below is computed pairwise up to the shorter list only."
            )
        accuracy = (correct / total * 100) if total else 0.0
        print(f"\nExact-match accuracy on readable-plate attempts: {correct}/{total} = {accuracy:.1f}%")
    else:
        print(
            "\nNo --ground-truth provided — compare the 'Reads' list above against the "
            "actual plates visible in the clip / output video to judge accuracy manually."
        )


if __name__ == "__main__":
    main()
