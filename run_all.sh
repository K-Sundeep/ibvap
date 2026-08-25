#!/usr/bin/env bash
# IBVAP — starts all services as plain local processes (no Docker).
# Usage: ./run_all.sh   (Ctrl+C stops everything cleanly)

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDS=()

cleanup() {
  echo ""
  echo "Stopping all IBVAP services..."
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null
  echo "All services stopped."
  exit 0
}
trap cleanup SIGINT SIGTERM

echo "Starting ingest (port 8001)..."
(cd "$ROOT_DIR/ingest" && python main.py) &
PIDS+=($!)

echo "Starting inference (port 8002)..."
(cd "$ROOT_DIR/inference" && python main.py) &
PIDS+=($!)

echo "Starting backend (port 8000)..."
(cd "$ROOT_DIR/backend" && python main.py) &
PIDS+=($!)

echo "Starting frontend (npm run dev)..."
(cd "$ROOT_DIR/frontend" && npm run dev) &
PIDS+=($!)

echo ""
echo "All services launching. PIDs: ${PIDS[*]}"
echo "Press Ctrl+C to stop everything."

wait
