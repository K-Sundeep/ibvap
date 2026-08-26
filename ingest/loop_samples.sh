#!/usr/bin/env bash
#
# loop_samples.sh — serve local video files as looping RTSP streams for testing
# the ingest service without real cameras.
#
# Uses ffmpeg's built-in RTSP muxer in "listen" mode, so no separate RTSP
# server binary is needed. Each ffmpeg process listens on its own port and
# accepts ONE client connection (the ingest service) — that's fine for our
# use case: one CameraWorker per stream.
#
# Usage:
#   ./loop_samples.sh sample1.mp4 sample2.mp4 sample3.mp4 [sample4.mp4]
#
# Then point config.yaml at:
#   rtsp://127.0.0.1:8554/cam1
#   rtsp://127.0.0.1:8555/cam2
#   rtsp://127.0.0.1:8556/cam3
#   rtsp://127.0.0.1:8557/cam4   (if a 4th file is given)
#
# Ctrl+C stops all of them.

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 video1.mp4 [video2.mp4] [video3.mp4] [video4.mp4]"
  echo "  (2-4 files recommended to match today's 2-4 camera test target)"
  exit 1
fi

BASE_PORT=8554
PIDS=()

cleanup() {
  echo ""
  echo "Stopping all looped RTSP streams..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

i=0
for video in "$@"; do
  if [ "$i" -ge 4 ]; then
    echo "Ignoring extra file '$video' — only 4 streams supported by this script."
    break
  fi
  if [ ! -f "$video" ]; then
    echo "File not found: $video"
    exit 1
  fi

  port=$((BASE_PORT + i))
  cam_name="cam$((i + 1))"

  echo "Serving '$video' as rtsp://127.0.0.1:${port}/${cam_name}"

  # -re                 : read input at native frame rate (simulate a live feed)
  # -stream_loop -1      : loop the file forever
  # -an                  : drop audio, keep it simple
  # -c:v libx264          : re-encode to a stream-friendly codec (works for any input format)
  # -rtsp_flags listen    : ffmpeg acts as its own tiny RTSP server, no external binary
  ffmpeg -re -stream_loop -1 -i "$video" \
    -an -c:v libx264 -preset ultrafast -tune zerolatency \
    -f rtsp -rtsp_flags listen "rtsp://0.0.0.0:${port}/${cam_name}" \
    > "ffmpeg_${cam_name}.log" 2>&1 &

  PIDS+=($!)
  i=$((i + 1))
done

echo ""
echo "${#PIDS[@]} stream(s) running. Logs: ffmpeg_cam*.log. Press Ctrl+C to stop."
wait
