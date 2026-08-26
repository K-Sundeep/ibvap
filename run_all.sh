#!/usr/bin/env bash
# IBVAP — starts all services as plain local processes (no Docker).
# Usage: ./run_all.sh   (Ctrl+C stops everything cleanly)
#
# Demo-day stability additions:
#   - clears any stale process left on our ports from a previous run,
#     so a fresh run never fails with "address already in use"
#   - starts backend first and waits for it to be healthy before
#     starting the others, since they read from it
#   - prints one clear ALL SERVICES READY / NOT READY line at the end —
#     that's the only thing you should need to check before recording

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDS=()

# ---------- helpers ----------

# Resolve the PID bound to a local TCP port without relying on lsof/fuser
# (neither is guaranteed to be installed on every dev machine/BOP server).
find_pid_on_port() {
  local port_hex inode pidfd link
  port_hex=$(printf '%04X' "$1")
  inode=$(awk -v p=":${port_hex}" '$2 ~ p && $4 == "0A" {print $10}' /proc/net/tcp 2>/dev/null | head -1)
  [ -z "$inode" ] && return 1
  for pidfd in /proc/[0-9]*/fd/*; do
    link=$(readlink "$pidfd" 2>/dev/null) || continue
    if [ "$link" = "socket:[$inode]" ]; then
      basename "$(dirname "$(dirname "$pidfd")")"
      return 0
    fi
  done
  return 1
}

# If a port from a previous run is still occupied, kill its whole process
# group so this run doesn't fail — no manual "go kill it yourself" step.
free_port_if_stale() {
  local port="$1" name="$2" pid
  if nc -z localhost "$port" 2>/dev/null; then
    pid=$(find_pid_on_port "$port" 2>/dev/null)
    if [ -n "$pid" ] && [ "$pid" != "$$" ]; then
      echo "Port $port ($name) still occupied by a previous run (pid $pid) — stopping it."
      # Kill only this specific PID, not its process group — we didn't
      # launch it, so we can't assume it's safely isolated in its own
      # group (it could even coincide with our own, if launched from the
      # same shell as this run).
      kill "$pid" 2>/dev/null
      sleep 1
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null
        sleep 1
      fi
    else
      echo "WARNING: port $port ($name) is occupied but its process could not be identified."
      echo "         Free it manually, e.g.: fuser -k $port/tcp"
    fi
  fi
}

# Poll a health endpoint until it responds or the timeout elapses.
wait_for_health() {
  local url="$1" name="$2" timeout="${3:-15}" waited=0
  until curl -sf "$url" >/dev/null 2>&1; do
    waited=$((waited + 1))
    if [ "$waited" -ge "$timeout" ]; then
      echo "WARNING: $name did not become healthy within ${timeout}s ($url)"
      return 1
    fi
    sleep 1
  done
  echo "$name is up ($url)"
  return 0
}

cleanup() {
  echo ""
  echo "Stopping all IBVAP services..."
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      # Negative PID = kill the whole process group (setsid made $pid the
      # group leader), so children (e.g. next-server under npm) die too.
      kill -- "-$pid" 2>/dev/null
      kill "$pid" 2>/dev/null
    fi
  done
  wait 2>/dev/null
  echo "All services stopped."
  exit 0
}
trap cleanup SIGINT SIGTERM

# ---------- pre-flight: clear stale ports from a previous run ----------
echo "Checking for leftover processes from a previous run..."
free_port_if_stale 8001 ingest
free_port_if_stale 8002 inference
free_port_if_stale 8000 backend
free_port_if_stale 3000 frontend
echo ""

# ---------- start backend first, wait for it — others read from it ----------
echo "Starting backend (port 8000)..."
setsid bash -c "cd '$ROOT_DIR/backend' && exec python main.py" &
PIDS+=($!)
wait_for_health "http://localhost:8000/health" "backend" 15

echo "Starting ingest (port 8001)..."
setsid bash -c "cd '$ROOT_DIR/ingest' && exec python main.py" &
PIDS+=($!)

echo "Starting inference (port 8002)..."
setsid bash -c "cd '$ROOT_DIR/inference' && exec python main.py" &
PIDS+=($!)

echo "Starting frontend (npm run dev)..."
setsid bash -c "cd '$ROOT_DIR/frontend' && exec npm run dev" &
PIDS+=($!)

echo ""
echo "All services launching. PIDs: ${PIDS[*]}"
echo ""
echo "Waiting for all services to report healthy..."
sleep 2
ALL_OK=1
wait_for_health "http://localhost:8001/health" "ingest"    10 || ALL_OK=0
wait_for_health "http://localhost:8002/health" "inference" 10 || ALL_OK=0
wait_for_health "http://localhost:8000/health" "backend"   5  || ALL_OK=0
wait_for_health "http://localhost:3000/"       "frontend"  20 || ALL_OK=0

echo ""
if [ "$ALL_OK" -eq 1 ]; then
  echo "=================================================="
  echo " ALL SERVICES READY — safe to start the demo."
  echo " Dashboard: http://localhost:3000"
  echo "=================================================="
else
  echo "=================================================="
  echo " NOT ALL SERVICES CAME UP CLEAN — check the log"
  echo " above before recording. Do not start the demo yet."
  echo "=================================================="
fi
echo ""
echo "Press Ctrl+C to stop everything."
echo "(Running this script itself in the background? Use 'kill -TERM <pid>' to"
echo " stop it — a backgrounded shell can't trap Ctrl+C's SIGINT, but SIGTERM"
echo " still triggers this same clean shutdown.)"

wait
