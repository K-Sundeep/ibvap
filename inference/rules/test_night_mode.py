"""
inference/rules/test_night_mode.py

Standalone test: run BOTH plain detection and night-mode-enhanced
detection on the same dark/night clip, frame by frame, so you can
compare them directly and judge false-positive/false-negative behavior
yourself.

I can't report real FP/FN numbers from this end — no GPU, no network
access to download YOLO weights, and no copy of your actual dark test
clip in this sandbox (same limitation as the detection POC and the
ANPR OCR test earlier this sprint). What this script gives you instead:
two annotated output videos (baseline vs night-mode) to eyeball side by
side, plus per-run detection counts, so judging "is this good enough
for the demo" is a quick visual check rather than reading through logs.

Run:
  python3 test_night_mode.py --source dark_clip.mp4

Outputs:
  night_test_baseline.mp4    — plain detect(), fixed conf threshold
  night_test_nightmode.mp4   — NightModeProcessor-enhanced detection
  stdout summary of detection counts + is_night frame count
"""

import argparse
import os
import sys

import cv2
import numpy as np

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from ibvap.inference.detector import load_model, detect
from ibvap.inference.rules.night_mode import NightModeProcessor


def draw_detections(frame, detections, color):
    for d in detections:
        x1, y1, x2, y2 = [int(v) for v in d.bbox]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            frame, f"{d.class_name} {d.confidence:.2f}", (x1, max(0, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1,
        )
    return frame


def main():
    parser = argparse.ArgumentParser(description="Baseline vs night-mode detection comparison")
    parser.add_argument("--source", required=True)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--conf", type=float, default=0.35, help="Baseline detector confidence (also night_mode's base_conf)")
    parser.add_argument("--brightness-threshold", type=float, default=60.0)
    parser.add_argument("--low-conf", type=float, default=0.15)
    parser.add_argument("--motion-overlap-threshold", type=float, default=0.15)
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open source: {args.source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    model = load_model(args.model)
    night_processor = NightModeProcessor(
        brightness_threshold=args.brightness_threshold,
        low_conf=args.low_conf,
        base_conf=args.conf,
        motion_overlap_threshold=args.motion_overlap_threshold,
    )

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    baseline_writer = cv2.VideoWriter("night_test_baseline.mp4", fourcc, fps, (width, height))
    nightmode_writer = cv2.VideoWriter("night_test_nightmode.mp4", fourcc, fps, (width, height))

    frame_idx = 0
    night_frame_count = 0
    baseline_total_detections = 0
    nightmode_total_detections = 0
    brightness_samples = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        gray_mean = float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())
        brightness_samples.append(gray_mean)

        baseline_dets = detect(frame.copy(), model, conf=args.conf)
        nightmode_dets, is_night = night_processor.process(frame.copy(), model, detect)

        if is_night:
            night_frame_count += 1
        baseline_total_detections += len(baseline_dets)
        nightmode_total_detections += len(nightmode_dets)

        if frame_idx % 30 == 0:
            print(
                f"[frame {frame_idx}] brightness={gray_mean:.1f} night={is_night} "
                f"baseline_dets={len(baseline_dets)} nightmode_dets={len(nightmode_dets)}"
            )

        baseline_frame = draw_detections(frame.copy(), baseline_dets, (0, 200, 0))
        nightmode_frame = draw_detections(frame.copy(), nightmode_dets, (0, 0, 255))
        cv2.putText(nightmode_frame, f"NIGHT={is_night}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        baseline_writer.write(baseline_frame)
        nightmode_writer.write(nightmode_frame)

    cap.release()
    baseline_writer.release()
    nightmode_writer.release()

    print("\n=== Summary ===")
    print(f"Total frames:              {frame_idx}")
    print(f"Frames flagged as night:   {night_frame_count} ({100 * night_frame_count / max(1, frame_idx):.1f}%)")
    print(f"Brightness range observed: min={min(brightness_samples):.1f} max={max(brightness_samples):.1f} "
          f"mean={np.mean(brightness_samples):.1f}")
    print(f"Baseline total detections:  {baseline_total_detections}")
    print(f"Night-mode total detections:{nightmode_total_detections}")
    print(
        "\nIf night-mode detections are meaningfully higher than baseline on frames you know "
        "contain visible people, that's the false-negative reduction working. Watch both output "
        "videos side by side for false POSITIVES (boxes with nothing there) introduced by night mode — "
        "those would mean motion_overlap_threshold or low_conf need to go up."
    )
    print("\nOutputs: night_test_baseline.mp4, night_test_nightmode.mp4")


if __name__ == "__main__":
    main()
