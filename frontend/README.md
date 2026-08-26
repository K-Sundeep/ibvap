# IBVAP Frontend

Operator dashboard for IBVAP (Intelligent Border Video Analytics Platform).
Next.js (App Router) + Tailwind CSS, dark theme.

## Run

```bash
npm install
cp .env.example .env.local   # points the dashboard at the mock backend
npm run mock                 # terminal 1 — tracks + fence API on :8787
npm run dev                  # terminal 2 — http://localhost:3000
```

Point `NEXT_PUBLIC_WS_BASE` / `NEXT_PUBLIC_API_BASE` at port 8000 once the
FastAPI backend is up, and drop the mock. They are `NEXT_PUBLIC_` variables,
so they are inlined at build time — restart `npm run dev` after changing
them.

Setting only one of the two is fine: FastAPI serves the REST routes and the
sockets from the same origin, so whichever you leave out is derived from the
other (`ws://` ↔ `http://`). Only set both if the two really do live on
different hosts. If they are both unset the dashboard falls back to
`localhost:8000`, and every panel that can't reach a backend names the host it
tried — `FENCE API UNREACHABLE (localhost:8000)` — so a misconfigured base
says so on the tile instead of in devtools.

## What's here

| Path | Purpose |
|---|---|
| `app/App.jsx` | Dashboard layout: header + responsive camera grid |
| `app/components/CameraTile.jsx` | One feed: `<video>`, track overlay, status + analytics readout |
| `app/components/TrackOverlay.jsx` | Canvas layer drawing bounding boxes and track ids |
| `app/components/FenceEditor.jsx` | Virtual fence drawing surface + tile-footer controls |
| `app/components/AlertsFeed.jsx` | Live alerts as they fire, newest first |
| `app/components/EventLog.jsx` | Searchable, filterable event history |
| `app/components/EventDetail.jsx` | Snapshot + clip + rule reasoning for one event |
| `app/components/PlateList.jsx` | ANPR plate enrollment for the demo zone |
| `app/components/EventIcon.jsx` | Per-type alert glyphs |
| `app/components/CameraStatusBar.jsx` | Which camera is busy — alerts per camera, last 5 min |
| `app/hooks/useTrackStream.js` | Per-camera WebSocket client (contract below) |
| `app/hooks/useFence.js` | Loads and persists a camera's fence |
| `app/hooks/useAlertStream.js` | Dashboard-wide alert socket |
| `app/hooks/useWatchlist.js` | Loads and edits the enrolled plate list |
| `app/lib/watchlistApi.js` | Watchlist contract + plate normalization |
| `app/lib/eventsApi.js` | Event/alert contract, types, history query |
| `app/lib/backend.js` | Resolves the backend HTTP + WebSocket bases |
| `app/lib/reconnectingSocket.js` | Reconnect-with-backoff shared by both sockets |
| `app/lib/rafScheduler.js` | Single shared rAF loop for all overlays |
| `app/lib/frameMapping.js` | Normalized ↔ pixel mapping shared by overlay and editor |
| `app/lib/fenceApi.js` | Fence REST client (contract below) |
| `app/data/cameras.js` | Placeholder camera roster |
| `mock/server.mjs` | Throwaway mock backend: track stream + fence API |
| `public/samples/sample-feed.mp4` | Static 12s sample clip (synthetic, ~28 KB) |

## Track stream contract

One socket per camera: `$NEXT_PUBLIC_WS_BASE/ws/tracks/<camera_id>`.

```jsonc
{
  "camera_id":  "CAM-01",
  "frame_id":   1234,
  "ts":         1756100000.123,  // capture time, epoch seconds
  "fps":        14.8,            // backend processing rate for this camera
  "latency_ms": 82,              // capture → publish, measured backend-side
  "tracks": [
    { "track_id": 7, "cls": "person", "conf": 0.91,
      "bbox": [0.42, 0.55, 0.08, 0.30] }   // x, y, w, h as 0-1 fractions
  ]
}
```

Boxes are **normalized 0-1**, so the overlay scales to any tile size without
knowing the source resolution. `fps` and `latency_ms` drive the per-tile
readout; latency turns amber past 500 ms and red past 1500 ms, against the
platform's sub-2s alert target. Messages without a `tracks` array are ignored
rather than dropping the socket, and a tile clears its boxes after 1s of
silence instead of holding ghosts. Disconnects reconnect with jittered
exponential backoff (1s → 10s).

Class colours: `person` green, `vehicle`/`car`/`truck`/`bus`/`motorcycle`
blue, `face` violet, `plate` amber, anything else grey.

## Virtual fence editor

Each tile's footer carries the controls, so nothing covers the feed during a
demo. **Draw polygon** or **Draw tripwire** enters draw mode; click on the
video to drop points. A polygon finishes by clicking its first vertex again or
double-clicking; a tripwire finishes on its second point. **Save fence** does
the same from the toolbar. While drawing: `Backspace` undoes a point, `Esc`
cancels, `Enter` saves, and a hint bar over the tile spells all of it out.

Saved fences load from the backend on mount, so they survive a reload — the
rules engine reads the same record, which is why they are not kept in browser
storage.

### Fence API contract

One fence per camera:

```
GET    /api/fences/<camera_id>   → 200 fence, or 200 null when none is set
PUT    /api/fences/<camera_id>   → 200 saved fence    body: { type, points }
DELETE /api/fences/<camera_id>   → 204
```

A camera without a fence answers `200 null`, not `404` — it is a normal
state, and a 404 puts a red error in the operator's console on every page
load. The client still accepts a 404 if the backend prefers to answer that
way.

```jsonc
{
  "camera_id":  "CAM-01",
  "type":       "polygon",        // "polygon" (3+ points) or "tripwire" (exactly 2)
  "points":     [[0.2, 0.4], [0.7, 0.4], [0.7, 0.9]],
  "updated_at": 1756100000.123
}
```

Points are normalized 0-1 like track boxes, so a fence drawn on a 640x360
preview still means the same thing to a worker reading 1080p — and both
overlays run through the same `object-cover` transform
(`app/lib/frameMapping.js`), so a fence and a box that touch on screen really
do touch in frame coordinates. `PUT` rejects the wrong point count or
out-of-range coordinates with `400 { detail }`, which the toolbar surfaces.

## Alerts and the event log

The right rail streams alerts as the rules engine fires them; the table
underneath is the searchable history behind it. Both carry the platform's
event schema — `id, camera_id, type, timestamp, track_id, confidence,
snapshot_path, clip_path, metadata_json` — and clicking either a live alert or
a log row opens the same detail view: snapshot, clip, and the rule's own
account of why it fired.

```
ws  /ws/alerts                    one event object per message, as it fires
GET /api/events?camera_id=&type=&from=&to=&q=&limit=&offset=
                                  → { events: [...], total: 1234 }
```

`from` / `to` are epoch seconds — the client converts the operator's local
date pickers, so the backend never has to guess what "2026-08-25" means.
`metadata_json` is accepted as either an object or a JSON string, since SQLite
stores it as text and it depends on how the route serializes it.

Making a new alert impossible to miss:

- Alerts go **straight into React state and render on arrival** — no batching,
  no polling. (Track frames are the opposite case: 15/sec per camera, kept out
  of state entirely. Alerts are rare and each one matters.)
- A new row **slides in and holds a red flash** for 2.6s, so one arriving
  mid-sentence still registers. Suppressed under `prefers-reduced-motion`.
- If the operator has scrolled down, a **"N new alerts ↑"** button appears
  rather than the list silently growing above them. "New" counts from when
  they left the top, not from page load.
- Every row leads with **why it fired** — "track #43 crossed the virtual
  fence", "dwell time 105s in zone (threshold 30s)" — not a bare score.
- The log never moves under someone reading it: new alerts offer a
  **refresh button** instead of refetching the current page.

Filtering runs on the backend, so the table stays honest when the store holds
weeks of events rather than the fifty the feed keeps in memory.

## ANPR plate watchlist

Phase 3's wow module. Type a plate, pick blacklist or whitelist, save — the
ANPR worker matches live reads against these rows, so enrolling a plate here
is what turns the next sighting into a `watchlist_hit`.

```
GET    /api/watchlist?kind=plate  → { entries: [...] }
POST   /api/watchlist             → 201 entry   body: { kind, value, list_type, note }
DELETE /api/watchlist/<id>        → 204
```

```jsonc
{
  "id": 3,
  "kind": "plate",                // in the schema so faces can share the table later
  "value": "HR26DK8337",          // normalized: upper case, no spaces or dashes
  "list_type": "blacklist",       // or "whitelist"
  "note": "flagged by sector HQ",
  "created_at": 1756100000.123
}
```

Plates are normalized before they are stored and before they are compared,
because OCR never sees the spaces and dashes people type — the form shows what
will actually be stored. `POST` rejects a bad `list_type` or an implausible
plate length with `400 { detail }` and a duplicate with `409`, both surfaced
in the form.

Watchlist hits are then set apart everywhere they appear: their own glyph
(colour alone isn't enough on a projector), a fuchsia row tint in both the
feed and the log, the matched plate as a mono badge rather than buried in a
sentence, and a "matched plate" block at the top of the detail view.

## Visual language

Every alert type is legible three ways, so none of them depends on colour
alone (projectors and colour vision both being what they are):

| | Accent | Glyph | Headline figure |
|---|---|---|---|
| Intrusion | red | figure over a line | `INBOUND` / `OUTBOUND` |
| Watchlist hit | fuchsia (+ row tint) | plate under a magnifier | the matched plate |
| Loitering | amber | clock | `105s dwell · limit 30s` |
| Night movement | sky | moon | `3 lux` |

The accent runs down the left edge of the row in the feed and of the time
cell in the log, so a row is typed at a glance in both. The row tint is
reserved for watchlist hits — it is the only alert that names a specific
vehicle, and tinting everything would mean tinting nothing. Each type's
headline figure appears in the feed, where rows are scanned and the reason
line is clamped to two lines; the log leaves it out, because the "why it
fired" column already spells the number out in full.

Surfaces come from two tokens in `globals.css` — `--color-app` behind
everything and `--color-panel` for panels — rather than repeated hex
literals, so a theme change is one edit.

## Keeping the overlay cheap

Four simultaneous streams at 15-30 fps is enough data to bog the UI down if
handled naively, so:

- **Frames never enter React state.** They land on a ref; the canvas reads it
  in the draw loop. Only the readout re-renders, twice a second.
- **One rAF loop for the whole page**, not one per tile.
- **Draws happen on new data**, not every frame — a 15 fps stream costs 15
  repaints a second, not 60.
- **Canvas, not SVG** — no DOM churn as tracks come and go.
- Tile size comes from a `ResizeObserver`, so the loop never forces layout.

Measured in headless Chromium with four tiles at 15 fps: 4 × 15 canvas
repaints/sec, one rAF loop, no dropped frames.

## Mock server caveat

`mock/server.mjs` reuses the speeds and box sizes of the objects in the
sample clip, so the overlay looks plausible — but it has no idea where each
tile's `<video>` is in its 12s loop, so boxes are **not** pixel-locked to the
figures on screen. Real alignment arrives with the detector.

Saved fences go to `mock/fences.json` (gitignored), which is what makes
reload-persistence real today. Its validation duplicates what the FastAPI
route will need to do — it is a stand-in for Python, not shared code.

## Not built yet

No real matching happens on the frontend's side of any of this: fence
crossings and plate reads both come from the mock, not from track geometry or
OCR. The rules engine and the ANPR worker are the backend's half — the
dashboard is ready to display whatever they emit. Faces are not enrollable;
`kind` is in the watchlist schema so they can be added without a second
endpoint.
