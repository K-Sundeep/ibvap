"""
inference/run_pipeline_report.py

End-to-end pipeline report: runs detector -> night_mode -> tracker ->
fence/loitering rules directly against a video file (no ingest/backend
services needed) and prints a summary formatted to drop straight into
the PPT's "Feasibility & risk mitigation" or "Technical approach" slide.

I CANNOT hand you real numbers from this end — no GPU, no network
access to download YOLO weights, and no copy of your test clips exist
in this sandbox (same limitation as every other test script this
sprint). This script is the last mile: run it on your GPU box against
your actual clips, and the printed report below is what goes in the
slide.

Run (detection + tracking only):
  python3 run_pipeline_report.py --source test_clip.mp4

Run (with a fence and a loitering zone, both as fractions of frame 0-1,
x1,y1,x2,y2,... in order):
  python3 run_pipeline_report.py --source test_clip.mp4 \\
      --fence 0.4,0,0.6,0,0.6,1,0.4,1 \\
      --loiter-zone 0.25,0.25,0.75,0.25,0.75,0.85,0.25,0.85 --loiter-threshold 5

What gets measured (and what it's a proxy for):
  - Detection: total + per-class detection counts, avg per frame —
    "detection accuracy" without ground-truth labels is necessarily a
    rough estimate; this gives you the raw counts to sanity-check
    against what you know is actually in the clip (see the printed
    caveat).
  - Tracking stability: unique track_ids seen vs. how many ever reached
    `confirmed` (>= --min-hits consecutive frames). A high
    never-confirmed ratio means lots of 1-2 frame flicker tracks —
    exactly what min_hits is meant to suppress; if that ratio is still
    high in your real clips, min_hits may need raising further.
  - Alerts: count fired per event type.
  - Latency: PER-FRAME processing time (detect+track+rules) in ms —
    mean/median/p95/max. IMPORTANT CAVEAT printed at the end: this is
    processing latency on whatever machine you run this script on, not
    true end-to-end latency across ingest -> inference -> backend ->
    dashboard as separate services/network hops. Use this number as
    the "inference stage" component of the PPT's latency claim, not the
    whole pipeline's number, unless you also measure the other hops.
"""

import argparse
import sys
import time
from collections import Counter, defaultdict

import cv2
import numpy as np

from ibvap.inference.detector import load_model, detect
from ibvap.inference.tracker import ObjectTracker
from ibvap.inference.rules.night_mode import NightModeProcessor
from ibvap.inference.rules.virtual_fence import VirtualFence
from ibvap.inference.rules.loitering import LoiteringZone


def parse_polygon(arg: str, width: int, height: int):
    """'x1,y1,x2,y2,...' as fractions of frame -> [(px, py), ...]."""
    values = [float(v) for v in arg.split(",")]
    if len(values) % 2 != 0 or len(values) < 6:
        raise SystemExit("Polygon must have an even number of values, at least 3 points (6 numbers)")
    points = list(zip(values[0::2], values[1::2]))
    return [(x * width, y * height) for x, y in points]


def percentile(values, p):
    if not values:
        return 0.0
    return float(np.percentile(values, p))


def main():
    parser = argparse.ArgumentParser(description="End-to-end IBVAP pipeline report")
    parser.add_argument("--source", required=True)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--min-hits", type=int, default=3)
    parser.add_argument("--fence", default=None, help="Fence polygon as 'x1,y1,x2,y2,...' fractions of frame")
    parser.add_argument("--loiter-zone", default=None, help="Loitering zone polygon, same format as --fence")
    parser.add_argument("--loiter-threshold", type=float, default=30.0)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open source: {args.source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Source: {args.source} | {width}x{height} @ {fps:.1f} FPS | ~{total_frame_count} frames")
    print(f"Model: {args.model} | conf={args.conf} | min_hits={args.min_hits}")

    model = load_model(args.model, device=args.device)
    tracker = ObjectTracker(frame_rate=int(fps), min_hits=args.min_hits)
    night_processor = NightModeProcessor(base_conf=args.conf)

    fence = None
    if args.fence:
        fence = VirtualFence(polygon=parse_polygon(args.fence, width, height), camera_id="report_cam", fence_id="report_fence")

    loiter_zone = None
    if args.loiter_zone:
        loiter_zone = LoiteringZone(
            polygon=parse_polygon(args.loiter_zone, width, height),
            camera_id="report_cam",
            zone_id="report_loiter_zone",
            threshold_seconds=args.loiter_threshold,
        )

    # --- accumulators ---
    frame_idx = 0
    night_frame_count = 0
    detection_class_counts = Counter()
    total_detections = 0
    seen_track_ids = set()
    ever_confirmed_track_ids = set()
    event_type_counts = Counter()
    latencies_ms = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        timestamp = frame_idx / fps  # synthetic clock — see test scripts' note on why

        t0 = time.time()

        detections, is_night = night_processor.process(frame, model, detect)
        if is_night:
            night_frame_count += 1
        total_detections += len(detections)
        for d in detections:
            detection_class_counts[d.class_name] += 1

        tracked = tracker.update(detections)
        for obj in tracked:
            seen_track_ids.add(obj.track_id)
            if obj.confirmed:
                ever_confirmed_track_ids.add(obj.track_id)
            else:
                continue  # same reliability gate as main.py — unconfirmed tracks don't fire alerts

            if is_night and night_processor.should_alert(obj.track_id):
                event_type_counts["night_movement"] += 1

            if loiter_zone is not None:
                loiter_event = loiter_zone.update(obj.track_id, obj.centroid, timestamp, obj.class_name)
                if loiter_event:
                    event_type_counts["loitering"] += 1

            if fence is not None:
                fence_event = fence.update(obj.track_id, obj.centroid, timestamp, obj.class_name, obj.confidence)
                if fence_event:
                    event_type_counts["intrusion"] += 1

        latencies_ms.append((time.time() - t0) * 1000)

        if frame_idx % 60 == 0:
            print(f"  ...processed {frame_idx} frames")

    cap.release()

    never_confirmed = seen_track_ids - ever_confirmed_track_ids

    print("\n" + "=" * 60)
    print("IBVAP PIPELINE REPORT")
    print("=" * 60)

    print(f"\nClip: {args.source}")
    print(f"Frames processed: {frame_idx} ({frame_idx / fps:.1f}s of footage)")
    print(f"Frames flagged as night: {night_frame_count} ({100 * night_frame_count / max(1, frame_idx):.1f}%)")

    print(f"\n--- Detection ---")
    print(f"Total detections: {total_detections}  (avg {total_detections / max(1, frame_idx):.2f} per frame)")
    for class_name, count in detection_class_counts.most_common():
        print(f"  {class_name:12s}: {count}")
    print(
        "NOTE: these are raw counts, not accuracy against ground truth — I have no labeled "
        "clip to compute precision/recall against. For a PPT-ready 'accuracy' figure, manually "
        "count actual people/vehicles in a short segment and compare to the detection count "
        "for that segment."
    )

    print(f"\n--- Tracking stability ---")
    print(f"Unique track_ids seen: {len(seen_track_ids)}")
    print(f"Track_ids that reached 'confirmed' ({args.min_hits}+ consecutive frames): {len(ever_confirmed_track_ids)}")
    print(f"Track_ids that NEVER confirmed (likely flicker/false tracks, now suppressed from alerts): {len(never_confirmed)}")
    if seen_track_ids:
        never_confirmed_pct = 100 * len(never_confirmed) / len(seen_track_ids)
        print(f"Never-confirmed rate: {never_confirmed_pct:.1f}% (lower is better; raise --min-hits if still high)")

    print(f"\n--- Alerts fired ---")
    if event_type_counts:
        for event_type, count in event_type_counts.most_common():
            print(f"  {event_type:16s}: {count}")
    else:
        print("  (none — pass --fence and/or --loiter-zone to exercise those rules)")

    print(f"\n--- Latency (per-frame processing: detect + track + rules), milliseconds ---")
    print(f"  mean:   {np.mean(latencies_ms):.1f} ms")
    print(f"  median: {percentile(latencies_ms, 50):.1f} ms")
    print(f"  p95:    {percentile(latencies_ms, 95):.1f} ms")
    print(f"  max:    {max(latencies_ms):.1f} ms")
    print(
        "\nCAVEAT for the PPT: the above is processing latency on THIS machine, for the "
        "detect+track+rules stage only — not the full ingest -> inference -> backend -> "
        "dashboard round trip across separate services and network hops. Quote it as the "
        "inference-stage component, or add ingest/backend/network timing separately for a "
        "true end-to-end number."
    )


if __name__ == "__main__":
    main()
