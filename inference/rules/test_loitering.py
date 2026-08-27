"""
inference/rules/test_loitering.py

Standalone test: does loitering detection fire correctly on a clip
where someone stands around in a defined zone?

Uses a much shorter threshold_seconds by default (5s, via --threshold)
than the production default (30s) — most test clips are short, and
waiting for a real 30s dwell in a test recording is impractical. Set
--threshold 30 explicitly to test the real production value if you have
a long enough clip.

Run:
  python3 test_loitering.py --source loiter_clip.mp4 --threshold 5
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from ibvap.inference.detector import load_model, detect
from ibvap.inference.tracker import ObjectTracker
from ibvap.inference.rules.loitering import LoiteringZone

# Fractions of frame width/height — adjust to where the person actually
# stands/loiters in your test clip.
TEST_ZONE_FRACTIONS = [
    (0.25, 0.25),
    (0.75, 0.25),
    (0.75, 0.85),
    (0.25, 0.85),
]


def scale_polygon(fractions, width, height):
    return [(x * width, y * height) for x, y in fractions]


def main():
    parser = argparse.ArgumentParser(description="Standalone loitering test")
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", default="loiter_test_output.mp4")
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--threshold", type=float, default=5.0, help="Dwell threshold in seconds (default 5 for quick clip testing)")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open source: {args.source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    polygon = scale_polygon(TEST_ZONE_FRACTIONS, width, height)
    print(f"Test zone (pixels): {polygon}")
    print(f"Dwell threshold: {args.threshold}s")

    model = load_model(args.model)
    tracker = ObjectTracker(frame_rate=int(fps))
    zone = LoiteringZone(polygon=polygon, camera_id="test_cam", zone_id="test_loiter_zone", threshold_seconds=args.threshold)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.out, fourcc, fps, (width, height))

    # Use a synthetic clock derived from frame index / fps rather than
    # wall-clock time.time() — this test runs through the clip far
    # faster than real time (no live camera to wait on), so wall-clock
    # timestamps would make dwell time meaningless. The live pipeline
    # (main.py) uses real timestamps since it genuinely runs in real
    # time against a live stream.
    frame_idx = 0
    event_count = 0
    flash_frames_remaining = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        synthetic_timestamp = frame_idx / fps

        detections = detect(frame, model, conf=args.conf)
        tracked = tracker.update(detections)

        fired_this_frame = False
        for obj in tracked:
            event = zone.update(
                track_id=obj.track_id,
                centroid=obj.centroid,
                timestamp=synthetic_timestamp,
                class_name=obj.class_name,
            )
            if event:
                event_count += 1
                fired_this_frame = True
                print(
                    f"[frame {frame_idx} t={synthetic_timestamp:.1f}s] LOITERING event #{event_count}: "
                    f"track_id={event.track_id} class={event.class_name} dwell={event.dwell_seconds:.1f}s"
                )

        if fired_this_frame:
            flash_frames_remaining = int(fps * 1.0)

        poly_color = (0, 0, 255) if flash_frames_remaining > 0 else (0, 200, 200)
        poly_pts = np.array([(int(x), int(y)) for x, y in polygon], dtype=np.int32)
        cv2.polylines(frame, [poly_pts], isClosed=True, color=poly_color, thickness=3)
        if flash_frames_remaining > 0:
            flash_frames_remaining -= 1

        for obj in tracked:
            x1, y1, x2, y2 = [int(v) for v in obj.bbox]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 200, 0), 2)
            cv2.putText(frame, f"ID {obj.track_id}", (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)

        writer.write(frame)

    cap.release()
    writer.release()
    print(f"\nDone. {event_count} loitering event(s) over {frame_idx} frames ({frame_idx / fps:.1f}s of clip).")
    print(f"Annotated output saved to: {args.out}")


if __name__ == "__main__":
    main()
