# IBVAP — Day 2 integration troubleshooting

Quick-reference for the most likely failure points when wiring ingest -> inference
-> backend -> dashboard together for the first time. Check these in order —
they're roughly in the order data flows through the pipeline.

---

## 1. RTSP stream timing out / ingest can't connect

**Symptom:** `/streams` shows `connected: false`, or `last_error: "failed to open
stream"` / `"read failed / stream ended"` repeating in ingest logs.

**Likely causes & checks:**
- `loop_samples.sh` (or real camera) isn't actually running — check for the
  ffmpeg process: `ps aux | grep ffmpeg`
- ffmpeg's `-rtsp_flags listen` mode only accepts **one client**. If you
  restarted the ingest service without killing the old connection, or opened
  the stream in VLC to sanity-check it, ingest's reconnect will now fail
  because the slot is taken. Kill any other RTSP clients before restarting ingest.
- Port mismatch between `loop_samples.sh` output and `config.yaml` — confirm
  with `cat ingest/ffmpeg_cam*.log` (should show "Stream mapping" once a
  client connects) and re-check the ports in `config.yaml`.
- Firewall/localhost binding — `loop_samples.sh` binds `0.0.0.0`, but if
  you're testing across a VM/container boundary, `127.0.0.1` in `config.yaml`
  may not resolve to the right host. Try the actual IP.

**Quick test in isolation:** `ffplay rtsp://127.0.0.1:8554/cam1` — if this
doesn't show video, the problem is upstream of ingest entirely (the fake
camera itself), so don't waste time debugging ingest code yet.

---

## 2. Backend not up yet when inference/ingest start (startup race)

**Symptom:** inference process is running (`pgrep` shows it) but backend log
shows zero incoming POSTs, and inference's own log shows connection-refused
errors early on.

**Likely causes & checks:**
- Plain-process startup (no Docker, no orchestrator) means there's no
  built-in "wait for dependency" behavior — if `run_all.sh` starts services
  in parallel, inference can easily beat backend to first request.
- Check inference's log for `ConnectionRefusedError` / `httpx.ConnectError`
  in the first few seconds after startup.
- Fix for today: either (a) add a short retry-with-backoff around inference's
  POST calls to backend (a few lines, worth adding permanently — real
  deployments restart independently too), or (b) just start backend first
  and give it ~2s before starting inference/ingest in `run_all.sh`.
- Confirm backend is actually listening: `curl http://localhost:8000/health`
  before assuming inference is at fault.

---

## 3. WebSocket not reconnecting / dashboard shows stale data

**Symptom:** Backend log shows events being received and processed fine, but
the dashboard (or `integration_test.py`'s WS check) stops getting messages
after a while, or never connects at all.

**Likely causes & checks:**
- Confirm the WS route matches what `integration_test.py` / the frontend
  expects — `ws://localhost:8000/ws/events` is a placeholder; check
  `backend/routes/` for the actual path and update the script's
  `BACKEND_WS_URL` if it differs.
- If the WS connects once but silently stops delivering: check whether the
  backend is broadcasting to a **specific client list** that isn't being
  cleaned up on disconnect (a common bug — a dead connection object still in
  the broadcast loop can silently swallow `send()` exceptions). Check backend
  logs for exceptions during broadcast, not just on connect.
- If the frontend doesn't auto-reconnect on drop: for today's integration
  test that's fine to skip, but note it in `docs/` as a Day 4/5 hardening
  item — brief network hiccups are realistic for remote BOP sites and will
  matter for the demo narrative either way.
- Quick isolation test: `wscat -c ws://localhost:8000/ws/events` (or the
  `websockets` python client directly) — if a raw WS client also gets
  nothing, it's a backend broadcast bug, not a frontend bug.

---

## 4. Backend receives POSTs but never broadcasts (silent drop)

**Symptom:** log shows `POST /events 200 OK` but nothing comes out on the WS.

**Likely causes & checks:**
- Event fails validation against the schema in `backend/models.py` after the
  200 is returned to inference but before it's written to SQLite / broadcast
  — check for a swallowed exception between "request accepted" and "insert +
  broadcast." Add a log line at the point of broadcast if there isn't one;
  today's integration test is exactly when you want that visibility.
- `camera_id` mismatch between what inference sends and what the frontend/WS
  filter expects (e.g. `"cam1"` vs `"Cam1"` vs `"camera_1"`) — case/format
  drift between services is easy to introduce when each teammate owns a
  different folder. Confirm the literal string against `ingest/config.yaml`.

---

## 5. Numbers look wrong in the FPS/latency log

**Symptom:** `integration_test.py` reports 0 fps, or negative/huge latency.

**Likely causes & checks:**
- 0 FPS: sampling window too short, or ingest just restarted (frames_read
  reset) — rerun with `--duration 15` or wait a few seconds after startup.
- Negative or absurd latency: clock skew between machines (e.g. inference
  running on a rented GPU box, backend running locally) — NTP-sync both, or
  for the demo, just report ingest FPS and drop cross-machine latency numbers
  rather than presenting skewed data.
- Latency includes ingest capture-to-display delay, not just
  inference-to-backend — if you need the narrower number for the PPT,
  timestamp the event at the moment inference produces the track, not at
  frame capture.

---

## When something breaks and you're short on time

Run `python scripts/integration_test.py` first — it tells you *which* layer
failed (ingest / inference-process / backend / WS) instead of guessing. Fix
top-down: ingest connectivity first, then backend liveness, then WS — a
failure lower in the list is often just a symptom of one higher up (e.g. "no
WS messages" is expected and correct if ingest was never connected).
