"""
inference/rules/test_virtual_fence.py

Standalone test: does virtual-fence crossing detection actually fire
correctly on a real clip, before wiring it into the live service loop?

Run:
  python3 test_virtual_fence.py --source sample_clip.mp4 --out fence_test_output.mp4

What it does:
  - Runs detector + tracker, reusing the SAME modules as the live
    pipeline (not reimplementing them), so this test proves the actual
    integration path, not just the fence math in isolation.
  - Applies a hardcoded test polygon (see TEST_POLYGON_FRACTIONS below).
  - Prints every CrossingEvent to stdout as it fires.
  - Draws the polygon + track boxes on each frame (polygon flashes red
    for ~0.5s after a crossing fires) and saves an annotated video, so
    you can visually confirm correctness rather than trusting logs alone.

Assumes it's run from inference/rules/ with inference/ on the path so it
can import detector.py and tracker.py from the parent directory.
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
from ibvap.inference.rules.virtual_fence import VirtualFence, Polygon

# Defined as FRACTIONS of frame width/height (0.0-1.0), not raw pixels,
# so the same test polygon works regardless of the test clip's actual
# resolution — scaled to real pixel coords once frame size is known.
# Default: a vertical "trip strip" across the middle third of the
# frame. Adjust these fractions to match where subjects actually walk
# or drive through in your specific sample clip.
TEST_POLYGON_FRACTIONS: Polygon = [
    (0.40, 0.0),
    (0.60, 0.0),
    (0.60, 1.0),
    (0.40, 1.0),
]


def scale_polygon(fractions: Polygon, width: int, height: int) -> Polygon:
    return [(x * width, y * height) for x, y in fractions]


def main():
    parser = argparse.ArgumentParser(description="Standalone virtual fence crossing test")
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", default="fence_test_output.mp4")
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--conf", type=float, default=0.35)
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open source: {args.source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    polygon = scale_polygon(TEST_POLYGON_FRACTIONS, width, height)
    print(f"Test polygon (pixels): {polygon}")

    model = load_model(args.model)
    tracker = ObjectTracker(frame_rate=int(fps))
    fence = VirtualFence(polygon=polygon, camera_id="test_cam", fence_id="test_fence")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.out, fourcc, fps, (width, height))

    frame_idx = 0
    event_count = 0
    flash_frames_remaining = 0  # highlight the polygon red for a moment after an event

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        detections = detect(frame, model, conf=args.conf)
        tracked = tracker.update(detections)

        fired_this_frame = False
        for obj in tracked:
            event = fence.update(
                track_id=obj.track_id,
                centroid=obj.centroid,
                timestamp=time.time(),
                class_name=obj.class_name,
            )
            if event:
                event_count += 1
                fired_this_frame = True
                print(
                    f"[frame {frame_idx}] CROSSING event #{event_count}: "
                    f"track_id={event.track_id} class={event.class_name} "
                    f"direction={event.direction} point={event.point}"
                )

        if fired_this_frame:
            flash_frames_remaining = max(1, int(fps * 0.5))

        # --- draw for visual confirmation ---
        poly_color = (0, 0, 255) if flash_frames_remaining > 0 else (0, 200, 0)
        poly_pts = np.array([(int(x), int(y)) for x, y in polygon], dtype=np.int32)
        cv2.polylines(frame, [poly_pts], isClosed=True, color=poly_color, thickness=3)
        if flash_frames_remaining > 0:
            flash_frames_remaining -= 1

        for obj in tracked:
            x1, y1, x2, y2 = [int(v) for v in obj.bbox]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 200, 0), 2)
            cv2.putText(
                frame, f"ID {obj.track_id} {obj.class_name}", (x1, max(0, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1,
            )

        writer.write(frame)

    cap.release()
    writer.release()
    print(f"\nDone. {event_count} crossing event(s) detected over {frame_idx} frames.")
    print(f"Annotated output saved to: {args.out}")
    print("Watch the output video to visually confirm the flashes line up with real crossings.")


if __name__ == "__main__":
    main()
