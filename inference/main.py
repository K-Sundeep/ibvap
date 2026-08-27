"""
inference/main.py

Independent, stateless inference worker.

Loop, per camera:
  1. Poll ingest's HTTP endpoint for the latest frame.
  2. Run detector.detect() (human + vehicle classes only).
  3. Run that camera's ObjectTracker.update() (stable track_ids).
  4. Run every virtual fence assigned to that camera against each
     tracked object's centroid; collect any CrossingEvents.
  5. Emit one JSON object per frame to stdout:
       {
         "camera_id": ...,
         "timestamp": ...,
         "objects": [{track_id, class, bbox, confidence}, ...],
         "events": [
             {"type": "intrusion", track_id, fence_id, direction, class, confidence, timestamp, point, snapshot_path},
             {"type": "loitering", track_id, zone_id, class, dwell_seconds, timestamp, point},
             {"type": "night_movement", track_id, class, confidence, timestamp, point},
             ...
         ],
         "plate_events": [{track_id, zone_id, plate_text, confidence,
                             list_match, timestamp, snapshot_path}, ...]
       }
  All three rule types (intrusion, loitering, night_movement) share the
  same "events" list and the same {type, track_id, timestamp, ...}
  shape, per the project's event schema — no separate plumbing added
  for loitering/night_mode beyond what fences already used. plate_events
  stays a separate list (added last sprint, deliberately scoped to one
  camera) rather than unifying it in here too, since that wasn't asked
  for this round and plate_events already has its own consumer shape.
  Snapshot capture (new this sprint): when a fence crossing fires, the
  current frame is copied and handed to a background thread (snapshot.py)
  which writes it to --snapshot-dir as "{camera_id}_{epoch_millis}.jpg"
  and the deterministic path is attached to the event immediately —
  the loop never waits on the actual disk write.

No DB writes, no backend calls here for the actual event/track data —
this worker's job ends at emitting JSON. The one exception is reading
fence polygons FROM the backend at startup (see ASSUMPTION below),
since the fence editor UI writes polygons there, not here.

FPS / per-frame latency are logged to STDERR, not stdout, so stdout
stays pure JSONL — see the note left in the previous version of this
file if you'd rather have everything interleaved on stdout instead.

ASSUMPTION — fence config source: this expects a function
`get_fences(backend_url, camera_id)` importable from `backend_client`
(the file your status notes say already exists in inference/), returning
a list of {"fence_id": str, "polygon": [[x, y], ...]} per camera. Your
backend_client.py almost certainly already has its own request-making
conventions (base URL handling, auth, retries) — rather than duplicating
that here, add the snippet shown in the accompanying note to your real
backend_client.py and this import will just work. If backend_client.py's
existing shape is different, only the two lines marked ADAPT below need
to change.
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from typing import Dict, List

from ibvap.inference.detector import load_model, detect
from ibvap.inference.tracker import ObjectTracker
from ibvap.inference.ingest_client import IngestClient
from ibvap.inference.rules.virtual_fence import VirtualFence
from ibvap.inference.rules.loitering import LoiteringZone
from ibvap.inference.rules.night_mode import NightModeProcessor
from ibvap.inference.snapshot import SnapshotWriter
from ibvap.inference.anpr_module import ANPRZone, process_vehicle_for_anpr
from ibvap.inference.watchlist_client import WatchlistCache

# ADAPT: swap these imports for however your real backend_client.py
# exposes fence/ANPR-zone/loitering-zone lookup, if shapes differ from
# the snippets provided.
from ibvap.inference.backend_client import get_fences, get_anpr_zone, get_loitering_zones


def build_fences_for_camera(backend_url: str, camera_id: str) -> List[VirtualFence]:
    """
    ADAPT: this assumes get_fences() returns
    [{"fence_id": ..., "polygon": [[x, y], ...]}, ...] for one camera.
    """
    fence_configs = get_fences(backend_url, camera_id)
    fences = []
    for cfg in fence_configs:
        polygon = [(float(x), float(y)) for x, y in cfg["polygon"]]
        fences.append(VirtualFence(polygon=polygon, camera_id=camera_id, fence_id=cfg["fence_id"]))
    return fences


def build_loitering_zones_for_camera(backend_url: str, camera_id: str) -> List[LoiteringZone]:
    zone_configs = get_loitering_zones(backend_url, camera_id)
    zones = []
    for cfg in zone_configs:
        polygon = [(float(x), float(y)) for x, y in cfg["polygon"]]
        zones.append(
            LoiteringZone(
                polygon=polygon,
                camera_id=camera_id,
                zone_id=cfg["zone_id"],
                threshold_seconds=float(cfg.get("threshold_seconds", 30.0)),
            )
        )
    return zones


def run(cameras, ingest_base_url, backend_url, model_path, poll_interval, conf, device, snapshot_dir, anpr_camera, min_hits):
    model = load_model(model_path, device=device)
    ingest = IngestClient(ingest_base_url)
    trackers = {cam_id: ObjectTracker(min_hits=min_hits) for cam_id in cameras}
    night_processors = {cam_id: NightModeProcessor(base_conf=conf) for cam_id in cameras}
    snapshot_writer = SnapshotWriter(output_dir=snapshot_dir)

    loitering_zones_by_camera: Dict[str, List[LoiteringZone]] = {}
    for cam_id in cameras:
        try:
            loitering_zones_by_camera[cam_id] = build_loitering_zones_for_camera(backend_url, cam_id)
            print(f"[inference] camera={cam_id} loaded {len(loitering_zones_by_camera[cam_id])} loitering zone(s)", file=sys.stderr)
        except Exception as e:
            print(f"[inference] camera={cam_id} failed to load loitering zones: {e} (no loitering checks)", file=sys.stderr)
            loitering_zones_by_camera[cam_id] = []

    # ANPR is intentionally scoped to ONE camera only — OCR is
    # comparatively expensive and this is a controlled-zone demo
    # capability, not something that should run on every stream.
    anpr_zone = None
    watchlist_cache = None
    if anpr_camera is not None:
        if anpr_camera not in cameras:
            print(f"[inference] --anpr-camera {anpr_camera} is not in --cameras; ANPR disabled", file=sys.stderr)
        else:
            try:
                zone_cfg = get_anpr_zone(backend_url, anpr_camera)
                if zone_cfg is None:
                    print(f"[inference] no ANPR zone configured for camera={anpr_camera}; ANPR disabled", file=sys.stderr)
                else:
                    polygon = [(float(x), float(y)) for x, y in zone_cfg["polygon"]]
                    anpr_zone = ANPRZone(polygon=polygon, camera_id=anpr_camera, zone_id=zone_cfg["zone_id"])
                    watchlist_cache = WatchlistCache(backend_url)
                    print(f"[inference] ANPR enabled on camera={anpr_camera} zone={zone_cfg['zone_id']}", file=sys.stderr)
            except Exception as e:
                print(f"[inference] failed to load ANPR zone for camera={anpr_camera}: {e} (ANPR disabled)", file=sys.stderr)

    fences_by_camera: Dict[str, List[VirtualFence]] = {}
    for cam_id in cameras:
        try:
            fences_by_camera[cam_id] = build_fences_for_camera(backend_url, cam_id)
            print(f"[inference] camera={cam_id} loaded {len(fences_by_camera[cam_id])} fence(s)", file=sys.stderr)
        except Exception as e:
            print(f"[inference] camera={cam_id} failed to load fences: {e} (running with NO fence checks)", file=sys.stderr)
            fences_by_camera[cam_id] = []

    frame_counts = defaultdict(int)
    fps_window_start = {cam_id: time.time() for cam_id in cameras}

    print(
        f"[inference] worker started | cameras={cameras} | model={model_path} | ingest={ingest_base_url}",
        file=sys.stderr,
    )

    while True:
        loop_start = time.time()

        for cam_id in cameras:
            frame_start = time.time()
            try:
                frame = ingest.get_latest_frame(cam_id)
            except Exception as e:
                print(f"[inference] camera={cam_id} frame fetch failed: {e}", file=sys.stderr)
                continue

            timestamp = time.time()
            detections, is_night = night_processors[cam_id].process(frame, model, detect)
            tracked = trackers[cam_id].update(detections)

            objects_json = []
            events_json = []
            plate_events_json = []

            for obj in tracked:
                objects_json.append(
                    {
                        "track_id": obj.track_id,
                        "class": obj.class_name,
                        "bbox": [round(v, 1) for v in obj.bbox],
                        "confidence": round(obj.confidence, 4),
                        "confirmed": obj.confirmed,
                    }
                )

                # Reliability gate (this sprint): every alert-producing
                # check below only runs for CONFIRMED tracks — a track
                # seen for fewer than min_hits consecutive frames could
                # be a single-frame flicker/false detection, not a real
                # object, and would otherwise be just as able to fire a
                # fence/loitering/night/plate alert as a stable track.
                # objects_json above still lists every track (confirmed
                # or not) so the dashboard can show raw detections if it
                # wants to.
                if not obj.confirmed:
                    continue

                # ANPR check — only runs at all if this is the configured
                # ANPR camera, and only fires the (comparatively expensive)
                # OCR pipeline on the single frame a vehicle enters the zone.
                if anpr_zone is not None and cam_id == anpr_camera:
                    entered = anpr_zone.check_entry(
                        track_id=obj.track_id,
                        centroid=obj.centroid,
                        category=obj.category,
                        timestamp=timestamp,
                    )
                    if entered:
                        plate_event = process_vehicle_for_anpr(
                            frame=frame,
                            track_id=obj.track_id,
                            vehicle_bbox=obj.bbox,
                            camera_id=cam_id,
                            zone_id=anpr_zone.zone_id,
                            timestamp=timestamp,
                            watchlist=watchlist_cache.snapshot(),
                        )
                        if plate_event:
                            plate_event.snapshot_path = snapshot_writer.capture(
                                frame=frame, camera_id=cam_id, timestamp=plate_event.timestamp
                            )
                            plate_events_json.append(
                                {
                                    "track_id": plate_event.track_id,
                                    "zone_id": plate_event.zone_id,
                                    "plate_text": plate_event.plate_text,
                                    "confidence": round(plate_event.ocr_confidence, 4),
                                    "list_match": plate_event.list_match,
                                    "timestamp": plate_event.timestamp,
                                    "snapshot_path": plate_event.snapshot_path,
                                }
                            )
                            print(
                                f"[inference] camera={cam_id} PLATE_READ track_id={obj.track_id} "
                                f"plate={plate_event.plate_text} list_match={plate_event.list_match}",
                                file=sys.stderr,
                            )

                # Night-time movement alert (capability #7) — fires once
                # per track for the duration of a continuous night
                # sighting, not every frame, via should_alert()'s
                # already-alerted bookkeeping.
                if is_night and night_processors[cam_id].should_alert(obj.track_id):
                    events_json.append(
                        {
                            "type": "night_movement",
                            "track_id": obj.track_id,
                            "class": obj.class_name,
                            "confidence": round(obj.confidence, 4),
                            "timestamp": timestamp,
                            "point": [round(v, 1) for v in obj.centroid],
                        }
                    )

                for zone in loitering_zones_by_camera.get(cam_id, []):
                    loiter_event = zone.update(
                        track_id=obj.track_id,
                        centroid=obj.centroid,
                        timestamp=timestamp,
                        class_name=obj.class_name,
                    )
                    if loiter_event:
                        events_json.append(
                            {
                                "type": "loitering",
                                "track_id": loiter_event.track_id,
                                "zone_id": loiter_event.zone_id,
                                "class": loiter_event.class_name,
                                "dwell_seconds": round(loiter_event.dwell_seconds, 1),
                                "timestamp": loiter_event.timestamp,
                                "point": [round(v, 1) for v in loiter_event.point] if loiter_event.point else None,
                            }
                        )
                        print(
                            f"[inference] camera={cam_id} LOITERING track_id={loiter_event.track_id} "
                            f"zone={loiter_event.zone_id} dwell={loiter_event.dwell_seconds:.1f}s",
                            file=sys.stderr,
                        )

                for fence in fences_by_camera.get(cam_id, []):
                    event = fence.update(
                        track_id=obj.track_id,
                        centroid=obj.centroid,
                        timestamp=timestamp,
                        class_name=obj.class_name,
                        confidence=obj.confidence,
                    )
                    if event:
                        # Snapshot capture: non-blocking (see snapshot.py) —
                        # the write happens on a background thread, so this
                        # call just copies the current frame and returns a
                        # deterministic path immediately. No re-detection,
                        # no re-processing, no wait on disk I/O here.
                        event.snapshot_path = snapshot_writer.capture(
                            frame=frame, camera_id=cam_id, timestamp=event.timestamp
                        )

                        events_json.append(
                            {
                                "type": "intrusion",
                                "track_id": event.track_id,
                                "fence_id": event.fence_id,
                                "direction": event.direction,
                                "class": event.class_name,
                                "confidence": round(event.confidence, 4) if event.confidence is not None else None,
                                "timestamp": event.timestamp,
                                "point": [round(v, 1) for v in event.point] if event.point else None,
                                "snapshot_path": event.snapshot_path,
                            }
                        )
                        print(
                            f"[inference] camera={cam_id} INTRUSION track_id={event.track_id} "
                            f"fence={event.fence_id} direction={event.direction} "
                            f"snapshot={event.snapshot_path}",
                            file=sys.stderr,
                        )

            latency_ms = (time.time() - frame_start) * 1000

            frame_payload = {
                "camera_id": cam_id,
                "timestamp": timestamp,
                "objects": objects_json,
                "events": events_json,
                "plate_events": plate_events_json,
            }

            # The JSON the backend consumes — one object per line (JSONL).
            print(json.dumps(frame_payload))
            sys.stdout.flush()

            frame_counts[cam_id] += 1
            if frame_counts[cam_id] % 30 == 0:
                elapsed = time.time() - fps_window_start[cam_id]
                fps = 30 / elapsed if elapsed > 0 else 0.0
                print(
                    f"[inference] camera={cam_id} fps={fps:.1f} last_latency_ms={latency_ms:.1f}",
                    file=sys.stderr,
                )
                fps_window_start[cam_id] = time.time()

        elapsed_loop = time.time() - loop_start
        sleep_time = max(0.0, poll_interval - elapsed_loop)
        time.sleep(sleep_time)


def main():
    parser = argparse.ArgumentParser(description="IBVAP inference worker: ingest -> detector -> tracker -> fence -> JSON")
    parser.add_argument("--ingest-url", required=True, help="Base URL of the ingest service, e.g. http://localhost:8001")
    parser.add_argument("--backend-url", required=True, help="Base URL of the backend service, e.g. http://localhost:8000")
    parser.add_argument("--cameras", required=True, help="Comma-separated camera IDs, e.g. cam1,cam2")
    parser.add_argument("--model", default="yolov8n.pt", help="yolov8n.pt / yolov8s.pt / yolov10n.pt / yolov10s.pt")
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--poll-interval", type=float, default=0.04, help="Seconds between polls per camera (~25 FPS target)")
    parser.add_argument("--device", default=None, help="0 for first GPU, cpu for CPU; default lets ultralytics auto-pick")
    parser.add_argument(
        "--snapshot-dir",
        default="../data/snapshots",
        help="Shared/mounted path snapshots are written to — must be readable by whatever "
             "serves snapshot_path to the dashboard (e.g. backend's static file mount).",
    )
    parser.add_argument(
        "--anpr-camera",
        default=None,
        help="Camera ID to run ANPR on (must be one of --cameras). Omit to disable ANPR entirely "
             "for this worker — it never runs on every stream, only this one if set.",
    )
    parser.add_argument(
        "--min-hits",
        type=int,
        default=3,
        help="Consecutive frames a track must persist before it's 'confirmed' and eligible to "
             "trigger any alert (intrusion/loitering/night_movement/ANPR). Reliability tuning: "
             "raises this to suppress flicker-track false alarms; lower if real short-lived "
             "objects (e.g. fast-crossing vehicles) are being missed because they never confirm.",
    )
    args = parser.parse_args()

    cameras = [c.strip() for c in args.cameras.split(",") if c.strip()]
    if not cameras:
        raise SystemExit("--cameras must list at least one camera ID")

    run(
        cameras, args.ingest_url, args.backend_url, args.model, args.poll_interval,
        args.conf, args.device, args.snapshot_dir, args.anpr_camera, args.min_hits,
    )


if __name__ == "__main__":
    main()
