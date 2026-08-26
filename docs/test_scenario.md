# IBVAP — Phase 2 floor test scenario

Purpose: one fixed, repeatable scenario to re-run every time a piece gets merged
today, so "did I just break something" has a fast, consistent answer instead of
re-inventing a test each time. Keep the fence and clip **unchanged** all day —
only re-run the same scenario, don't vary it, or you lose the ability to compare
runs.

---

## Fixed test setup (don't change this mid-day)

- **Camera:** `cam1` (the first `loop_samples.sh` stream, `rtsp://127.0.0.1:8554/cam1`)
- **Clip:** one clip where a single person enters from one side and walks fully
  across frame over roughly 5-8 seconds, at a normal walking pace — not
  sprinting. A few seconds of the person being visible *before* they reach the
  line matters: it gives the tracker time to stabilize an ID before the
  crossing, so you're testing "did the fence rule fire," not "did tracking
  even lock on in time."
  - Avoid clips with multiple people, heavy occlusion, or fast motion for this
    baseline test — those are good stress tests for Phase 4, not for today's
    floor check.
- **Fence:** a single straight vertical tripwire at the horizontal midpoint of
  the frame (~x=480 of 960px width), spanning the full frame height. Simple
  orientation on purpose — reduces geometry ambiguity while you're still
  confirming the coordinate system between frontend and inference is even
  correct (see known gap in TROUBLESHOOTING.md).
  - Draw this once, save it, and don't touch it again today unless you're
    specifically testing the fence editor itself.

---

## Expected sequence, in order, with rough timing

Run this after every merge. If any step doesn't happen, or happens in the
wrong order, that tells you where the break is — don't skip ahead to check
later steps "just in case."

1. **(t+0s)** Start/confirm all services (`scripts/integration_test.py` or
   manual health checks).
2. **(t+~5-10s)** cam1's live feed appears in the dashboard's CameraTile —
   confirms ingest → frontend end of the pipe, independent of AI entirely.
3. **(immediate, one-time)** Fence overlay is visible on the cam1 tile —
   confirms frontend → backend fence save/fetch round-trip. You should only
   need to see this once per day unless you touch the fence editor again.
4. **(as clip plays)** A tracking box + ID appears on the person as they walk
   — confirms detection + tracking are wired into what the dashboard renders,
   independent of the fence rule.
5. **(the moment the person crosses x≈480)** Intrusion alert fires. Target:
   under 1-2s from crossing to alert appearing (per the architecture doc's
   latency target) — note the actual delay you observe each run, it's useful
   demo-readiness data.
6. **(same moment, +0-1s)** AlertsFeed on the dashboard shows a new entry:
   camera_id=cam1, a snapshot thumbnail, and a human-readable reason (e.g.
   "track crossed virtual line") — not just a raw score.
7. **(same moment)** EventLog table gets a new row matching the same event.
8. **(anytime after)** `python scripts/query_events.py --camera_id cam1
   --type intrusion` shows the row, with `snapshot_exists: True`.

## Repeat testing note

Since the clip loops (`-stream_loop -1`), the crossing will recur every loop
cycle automatically — you don't need to manually restart anything to get a
second test run. **One event per loop is correct.** If you see two-plus
events for a single crossing (duplicate/flood) or zero events across several
loop cycles, that's the signal something regressed — not the looping itself
misbehaving.

Use `--since_minutes` on `query_events.py` to scope each check to just the
latest run instead of the whole day's accumulated test events.
