#!/usr/bin/env bash
# IBVAP — starts all services as plain local processes (no Docker).
# Usage: ./run_all.sh   (Ctrl+C stops everything cleanly)
#
# Works on real Linux/WSL (uses setsid + /proc for full process-group
# cleanup and port detection) AND on Windows Git Bash, which has neither —
# on Git Bash it falls back to plain background jobs + netstat.
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

# Detect whether we have real setsid + /proc (Linux/WSL) or not (Git Bash/Windows)
HAVE_SETSID=0
if command -v setsid >/dev/null 2>&1; then
  HAVE_SETSID=1
fi
HAVE_PROC=0
if [ -d /proc/net ]; then
  HAVE_PROC=1
fi

# ---------- helpers ----------

# Start a service. Uses setsid (own process group, clean group-kill later)
# when available; otherwise just backgrounds it normally.
#
# IMPORTANT: this does NOT use command substitution ($(...)) to hand back
# the PID. A backgrounded, long-running process (uvicorn/npm) shares the
# calling subshell's stdout — command substitution's capture pipe never
# sees EOF until that process exits, so "PIDS+=($(start_service ...))"
# would hang forever on the very first service, waiting on a pipe that a
# permanently-running server will never close. Instead, this sets a global
# LAST_PID that the caller reads immediately after — no pipe involved.
start_service() {
  local dir="$1" cmd="$2"
  if [ "$HAVE_SETSID" -eq 1 ]; then
    setsid bash -c "cd '$dir' && exec $cmd" &
  else
    bash -c "cd '$dir' && exec $cmd" &
  fi
  LAST_PID=$!
}

# Resolve the PID bound to a local TCP port.
# Linux/WSL: reads /proc/net/tcp directly (fast, no external tools needed).
# Git Bash/Windows: shells out to netstat.exe (available on every Windows box).
find_pid_on_port() {
  local port="$1"
  if [ "$HAVE_PROC" -eq 1 ]; then
    local port_hex inode pidfd link
    port_hex=$(printf '%04X' "$port")
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
  else
    # netstat.exe output line looks like:
    #   TCP    127.0.0.1:8000    0.0.0.0:0    LISTENING    12345
    netstat -ano -p tcp 2>/dev/null | grep -E "LISTENING" | grep -E ":$port[[:space:]]" \
      | awk '{print $NF}' | head -1
  fi
}

# If a port from a previous run is still occupied, kill it so this run
# doesn't fail — no manual "go kill it yourself" step.
free_port_if_stale() {
  local port="$1" name="$2" pid
  if nc -z localhost "$port" 2>/dev/null; then
    pid=$(find_pid_on_port "$port" 2>/dev/null)
    if [ -n "$pid" ] && [ "$pid" != "$$" ]; then
      echo "Port $port ($name) still occupied by a previous run (pid $pid) — stopping it."
      if [ "$HAVE_PROC" -eq 1 ]; then
        kill "$pid" 2>/dev/null
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
          kill -9 "$pid" 2>/dev/null
          sleep 1
        fi
      else
        # Git Bash: kill by Windows PID via taskkill, which is more reliable
        # than bash's kill for processes not spawned in this shell.
        taskkill //F //PID "$pid" >/dev/null 2>&1
        sleep 1
      fi
    else
      echo "WARNING: port $port ($name) is occupied but its process could not be identified."
      if [ "$HAVE_PROC" -eq 1 ]; then
        echo "         Free it manually, e.g.: fuser -k $port/tcp"
      else
        echo "         Free it manually: netstat -ano | findstr :$port   then   taskkill /F /PID <pid>"
      fi
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
      if [ "$HAVE_SETSID" -eq 1 ]; then
        # Negative PID = kill the whole process group (setsid made $pid the
        # group leader), so children (e.g. next-server under npm) die too.
        kill -- "-$pid" 2>/dev/null
      fi
      kill "$pid" 2>/dev/null
    fi
  done
  # On Git Bash, npm/node children often survive a plain `kill` of the
  # bash wrapper PID since there's no real process-group kill available —
  # sweep our known dev ports as a backstop so nothing lingers.
  if [ "$HAVE_SETSID" -eq 0 ]; then
    for port in 8000 8001 8002 3000; do
      pid=$(find_pid_on_port "$port" 2>/dev/null)
      [ -n "$pid" ] && taskkill //F //PID "$pid" >/dev/null 2>&1
    done
  fi
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
start_service "$ROOT_DIR/backend" "python main.py"
PIDS+=("$LAST_PID")
wait_for_health "http://localhost:8000/health" "backend" 15

echo "Starting ingest (port 8001)..."
start_service "$ROOT_DIR/ingest" "python main.py"
PIDS+=("$LAST_PID")

echo "Starting inference (port 8002)..."
start_service "$ROOT_DIR/inference" "python main.py"
PIDS+=("$LAST_PID")

echo "Starting frontend (npm run dev)..."
start_service "$ROOT_DIR/frontend" "npm run dev"
PIDS+=("$LAST_PID")

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
