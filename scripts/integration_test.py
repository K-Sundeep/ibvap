#!/usr/bin/env python3
"""
IBVAP — Day 2 integration test
Validates the full loop: ingest -> inference -> backend -> dashboard (WebSocket).

This is a cross-cutting tool (not owned by one service folder) — per the team's
role split it belongs to PM/lead: integration, demo script, metrics.

WHAT IT CHECKS
  1. Service liveness:
       - ingest      : GET /health + /streams (per-camera connected + recent frame)
       - backend     : GET /health
       - inference   : no HTTP endpoint by design (architecture doc: it's an HTTP
                        *client* to backend, not a server) -> checked indirectly via
                        (a) OS process presence and (b) backend actually receiving
                        POSTs from it (step 2).
  2. End-to-end data flow:
       - tails the backend log for incoming event POSTs matching our camera_ids
       - opens the backend WebSocket and confirms those events get broadcast out
  3. Metrics capture:
       - ingest FPS per camera (sampled from /streams frames_read over a window)
       - end-to-end latency per event = (time received on WS) - (event timestamp)
       - writes both to logs/ as CSV + a JSON summary, so numbers are ready to
         paste into the demo PPT without re-deriving them later.

CONFIG — adjust the block below to match what the backend/inference leads actually
built. Nothing here is guessed at runtime; if a route doesn't match, this script
will tell you exactly which check failed rather than hanging silently.

Usage:
    pip install requests websockets
    python scripts/integration_test.py --duration 30
"""

import argparse
import asyncio
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

try:
    import websockets
except ImportError:
    websockets = None  # handled at runtime with a clear error


# ============================================================================
# CONFIG — adjust to match your team's actual ports/routes/paths
# ============================================================================
INGEST_URL = "http://localhost:8001"
BACKEND_URL = "http://localhost:8000"
BACKEND_WS_URL = "ws://localhost:8000/ws/events"     # <-- confirm with backend lead
BACKEND_LOG_PATH = "backend/backend.log"              # <-- confirm with backend lead
INFERENCE_PROCESS_MATCH = "inference/main.py"          # substring to find via ps/pgrep

CAMERA_IDS = ["cam1", "cam2", "cam3"]                  # must match ingest config.yaml

FPS_SAMPLE_WINDOW_S = 10
WS_LISTEN_TIMEOUT_S = 15
LOG_DIR = "logs"
# ============================================================================


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log_result(results, name, ok, detail=""):
    results.append({"check": name, "ok": ok, "detail": detail, "ts": now_iso()})
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


# ---- 1. Liveness checks ----------------------------------------------------

def check_ingest(results):
    try:
        r = requests.get(f"{INGEST_URL}/health", timeout=3)
        log_result(results, "ingest /health", r.status_code == 200, r.text[:120])
    except Exception as e:
        log_result(results, "ingest /health", False, str(e))
        return {}

    try:
        r = requests.get(f"{INGEST_URL}/streams", timeout=3)
        statuses = {s["camera_id"]: s for s in r.json()}
        for cam_id in CAMERA_IDS:
            s = statuses.get(cam_id)
            if s is None:
                log_result(results, f"ingest camera {cam_id} configured", False, "not in /streams response")
                continue
            fresh = s.get("last_frame_age_s") is not None and s["last_frame_age_s"] < 3
            log_result(results, f"ingest camera {cam_id} live", s.get("connected") and fresh,
                       f"connected={s.get('connected')} last_frame_age_s={s.get('last_frame_age_s')}")
        return statuses
    except Exception as e:
        log_result(results, "ingest /streams", False, str(e))
        return {}


def check_backend(results):
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=3)
        log_result(results, "backend /health", r.status_code == 200, r.text[:120])
    except Exception as e:
        log_result(results, "backend /health", False, str(e))


def check_inference_process(results):
    try:
        out = subprocess.run(["pgrep", "-f", INFERENCE_PROCESS_MATCH],
                              capture_output=True, text=True)
        running = bool(out.stdout.strip())
        log_result(results, "inference process running", running,
                   f"pgrep match: '{INFERENCE_PROCESS_MATCH}'" + ("" if running else " — not found"))
    except FileNotFoundError:
        log_result(results, "inference process running", False,
                   "pgrep not available on this system — check manually with `ps aux | grep inference`")


# ---- 2. End-to-end data flow -----------------------------------------------

def check_backend_log_for_posts(results, since_ts):
    if not os.path.exists(BACKEND_LOG_PATH):
        log_result(results, "backend log: incoming POSTs", False,
                   f"log file not found at {BACKEND_LOG_PATH} — update BACKEND_LOG_PATH in this script")
        return
    with open(BACKEND_LOG_PATH, "r", errors="ignore") as f:
        lines = f.readlines()
    hits = {cam: 0 for cam in CAMERA_IDS}
    for line in lines[-2000:]:  # only look at recent tail, not the whole run
        if "POST" not in line and "/events" not in line:
            continue
        for cam in CAMERA_IDS:
            if cam in line:
                hits[cam] += 1
    for cam, count in hits.items():
        log_result(results, f"backend received POSTs from {cam}", count > 0, f"{count} matching log lines")


async def check_websocket_broadcast(results, metrics, timeout_s):
    if websockets is None:
        log_result(results, "backend WebSocket broadcast", False,
                   "`websockets` package not installed — pip install websockets")
        return
    seen_cams = set()
    try:
        async with websockets.connect(BACKEND_WS_URL, open_timeout=5) as ws:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline and len(seen_cams) < len(CAMERA_IDS):
                remaining = max(deadline - time.monotonic(), 0.1)
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                receive_time = time.time()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                cam_id = msg.get("camera_id")
                event_ts = msg.get("timestamp")
                if cam_id in CAMERA_IDS:
                    seen_cams.add(cam_id)
                    latency = None
                    if event_ts:
                        try:
                            event_epoch = datetime.fromisoformat(event_ts.replace("Z", "+00:00")).timestamp()
                            latency = receive_time - event_epoch
                        except Exception:
                            pass
                    metrics.append({
                        "camera_id": cam_id,
                        "track_id": msg.get("track_id"),
                        "event_type": msg.get("type"),
                        "latency_s": round(latency, 3) if latency is not None else None,
                        "received_at": now_iso(),
                    })
    except Exception as e:
        log_result(results, "backend WebSocket connect", False, str(e))
        return

    for cam in CAMERA_IDS:
        log_result(results, f"WS broadcast received for {cam}", cam in seen_cams,
                   "no message seen within timeout" if cam not in seen_cams else "")


# ---- 3. FPS metrics ---------------------------------------------------------

def measure_ingest_fps(results, window_s):
    try:
        r0 = requests.get(f"{INGEST_URL}/streams", timeout=3).json()
        t0 = time.monotonic()
    except Exception as e:
        log_result(results, "ingest FPS sample", False, str(e))
        return []

    time.sleep(window_s)

    try:
        r1 = requests.get(f"{INGEST_URL}/streams", timeout=3).json()
        t1 = time.monotonic()
    except Exception as e:
        log_result(results, "ingest FPS sample", False, str(e))
        return []

    before = {s["camera_id"]: s["frames_read"] for s in r0}
    after = {s["camera_id"]: s["frames_read"] for s in r1}
    elapsed = t1 - t0
    fps_rows = []
    for cam in CAMERA_IDS:
        delta = after.get(cam, 0) - before.get(cam, 0)
        fps = round(delta / elapsed, 2) if elapsed > 0 else 0
        fps_rows.append({"camera_id": cam, "fps": fps, "window_s": round(elapsed, 1)})
        log_result(results, f"ingest FPS {cam}", fps > 0, f"{fps} fps over {round(elapsed,1)}s")
    return fps_rows


# ---- output -----------------------------------------------------------------

def write_logs(results, fps_rows, latency_rows):
    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    checks_path = os.path.join(LOG_DIR, f"integration_run_{stamp}_checks.csv")
    with open(checks_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "check", "ok", "detail"])
        w.writeheader()
        w.writerows(results)

    metrics_path = os.path.join(LOG_DIR, f"integration_run_{stamp}_metrics.csv")
    with open(metrics_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["type", "camera_id", "value", "unit", "extra"])
        for row in fps_rows:
            w.writerow(["fps", row["camera_id"], row["fps"], "frames/s", f"window={row['window_s']}s"])
        for row in latency_rows:
            w.writerow(["latency", row["camera_id"], row["latency_s"], "s",
                       f"track_id={row.get('track_id')} type={row.get('event_type')}"])

    summary = {
        "run_ts": stamp,
        "total_checks": len(results),
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "fps": fps_rows,
        "latency_samples": latency_rows,
    }
    summary_path = os.path.join(LOG_DIR, f"integration_run_{stamp}_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nLogs written:\n  {checks_path}\n  {metrics_path}\n  {summary_path}")
    return summary


async def main_async(args):
    global CAMERA_IDS
    if args.cameras:
        CAMERA_IDS = args.cameras.split(",")

    results = []
    latency_rows = []

    print("=== 1. Liveness ===")
    check_ingest(results)
    check_backend(results)
    check_inference_process(results)

    print("\n=== 2. End-to-end data flow ===")
    since_ts = time.time()
    # give inference a moment to post at least one event before we check the log/WS
    time.sleep(2)
    check_backend_log_for_posts(results, since_ts)
    await check_websocket_broadcast(results, latency_rows, WS_LISTEN_TIMEOUT_S)

    print("\n=== 3. FPS metrics ===")
    fps_rows = measure_ingest_fps(results, args.duration)

    print("\n=== Summary ===")
    summary = write_logs(results, fps_rows, latency_rows)
    print(f"{summary['passed']}/{summary['total_checks']} checks passed.")
    if summary["failed"] > 0:
        print("See TROUBLESHOOTING.md in scripts/ for the most likely causes.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="IBVAP Day 2 integration test")
    parser.add_argument("--duration", type=int, default=FPS_SAMPLE_WINDOW_S,
                       help="seconds to sample FPS over (default: %(default)s)")
    parser.add_argument("--cameras", type=str, default=None,
                       help="comma-separated camera_ids, overrides CAMERA_IDS in script")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
