/**
 * Mock backend — stands in for FastAPI until the real services exist. Speaks
 * the contracts documented in app/hooks/useTrackStream.js and app/lib/fenceApi.js.
 *
 *   node mock/server.mjs
 *     ws   ws://localhost:8787/ws/tracks/<camera_id>    live track frames
 *     ws   ws://localhost:8787/ws/alerts                alerts as they fire
 *     http http://localhost:8787/api/fences/<camera_id> GET / PUT / DELETE
 *     http http://localhost:8787/api/events?...         event history
 *     http http://localhost:8787/api/watchlist          GET / POST / DELETE
 *     http http://localhost:8787/snapshots/<id>.svg     generated stand-in frame
 *     http http://localhost:8787/clips/<id>.mp4         the sample clip
 *
 * Fences persist to mock/fences.json so they survive a reload, the same way
 * the real backend will persist them to SQLite. Validation is duplicated here
 * rather than imported from app/ — this file is a stand-in for Python code,
 * and the checks are what the FastAPI route will need to do anyway.
 *
 * The synthetic tracks use the same speeds and box sizes as the objects in
 * public/samples/sample-feed.mp4, so the overlay looks plausible — but the
 * mock has no idea where each tile's <video> is in its loop, so the boxes are
 * not pixel-locked to the figures on screen. That alignment only arrives with
 * the real detector.
 */
import { createServer } from 'node:http';
import { createReadStream, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';

const PORT = Number(process.env.MOCK_PORT) || 8787;
const FPS = 15;
const FRAME_W = 640;
const FRAME_H = 360;
const LOOP_SECONDS = 12;

const jitter = (spread) => (Math.random() - 0.5) * spread;

// Stable per-camera phase offset so the tiles aren't identical.
function phaseFor(cameraId) {
  let hash = 0;
  for (const char of cameraId) hash = (hash * 31 + char.charCodeAt(0)) % 9973;
  // Final mix: without it, ids differing only in the last character (CAM-01,
  // CAM-02, ...) land on near-identical phases and every tile moves in step.
  return (((hash * 7919) % 9973) / 9973) * LOOP_SECONDS;
}

function tracksAt(elapsed) {
  const tracks = [];

  // Pedestrian: crosses left to right, re-entering with a fresh track id each
  // lap — the same thing ByteTrack does when a target leaves and returns.
  const walkDistance = (elapsed * 58) % 760;
  tracks.push({
    track_id: 7 + Math.floor((elapsed * 58) / 760),
    cls: 'person',
    conf: +(0.88 + jitter(0.08)).toFixed(2),
    bbox: normalize(walkDistance - 60 + jitter(1), 206 + 8 * Math.sin(elapsed * 3), 26, 62),
  });

  // Vehicle: right to left, only reported while it is actually in frame.
  const driveX = 700 - ((elapsed * 95) % 820);
  if (driveX > -54 && driveX < FRAME_W) {
    tracks.push({
      track_id: 100 + Math.floor((elapsed * 95) / 820),
      cls: 'vehicle',
      conf: +(0.82 + jitter(0.1)).toFixed(2),
      bbox: normalize(driveX + jitter(1), 238 + jitter(1), 54, 30),
    });
  }

  return tracks;
}

function normalize(x, y, w, h) {
  return [
    +(x / FRAME_W).toFixed(4),
    +(y / FRAME_H).toFixed(4),
    +(w / FRAME_W).toFixed(4),
    +(h / FRAME_H).toFixed(4),
  ];
}

// --- watchlist store -------------------------------------------------------

const WATCHLIST_FILE = join(dirname(fileURLToPath(import.meta.url)), 'watchlist.json');

function readWatchlist() {
  try {
    return JSON.parse(readFileSync(WATCHLIST_FILE, 'utf8'));
  } catch {
    return [];
  }
}

function writeWatchlist(entries) {
  writeFileSync(WATCHLIST_FILE, `${JSON.stringify(entries, null, 2)}\n`);
}

const normalizePlate = (value) => String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '');

function validateEntry(body) {
  if (body?.kind !== 'plate') return 'kind must be "plate" (faces are not enrolled yet)';
  if (!['blacklist', 'whitelist'].includes(body.list_type)) {
    return 'list_type must be "blacklist" or "whitelist"';
  }
  const plate = normalizePlate(body.value);
  if (plate.length < 4 || plate.length > 12) return 'plate must be 4-12 alphanumeric characters';
  return null;
}

/** Blacklisted plates the ANPR worker would be matching against right now. */
function blacklistedPlates() {
  return readWatchlist().filter((entry) => entry.kind === 'plate' && entry.list_type === 'blacklist');
}

// --- event store -----------------------------------------------------------

/**
 * Events follow the platform schema exactly — id, camera_id, type, timestamp,
 * track_id, confidence, snapshot_path, clip_path, metadata_json — because the
 * live socket, the history endpoint and (eventually) the SQLite table all
 * carry the same record.
 *
 * History is seeded in memory at startup rather than persisted: every restart
 * gives a fresh few days of events ending "now", which is what makes the date
 * filters demoable.
 */
const CAMERA_IDS = ['CAM-01', 'CAM-02', 'CAM-03', 'CAM-04'];

const EVENT_KINDS = [
  {
    type: 'intrusion',
    weight: 4,
    reason: (event) => `track #${event.track_id} crossed the virtual fence`,
    extra: () => ({ rule: 'virtual_fence', direction: pick(['inbound', 'outbound']) }),
  },
  {
    type: 'loitering',
    weight: 3,
    reason: (event, extra) => `dwell time ${extra.dwell_seconds}s in zone (threshold ${extra.threshold_seconds}s)`,
    extra: () => ({ rule: 'loitering', dwell_seconds: 32 + Math.floor(Math.random() * 90), threshold_seconds: 30 }),
  },
  {
    type: 'night_movement',
    weight: 2,
    reason: (event, extra) => `motion during night hours (${extra.lux} lux, no scheduled patrol)`,
    extra: () => ({ rule: 'night_mode', lux: 2 + Math.floor(Math.random() * 8) }),
  },
  {
    type: 'watchlist_hit',
    weight: 1,
    reason: (event, extra) => (extra.plate
      ? `plate ${extra.plate} matched blacklist`
      : `face matched watchlist entry #${extra.watchlist_id}`),
    extra: () => {
      // Prefer a plate the operator has actually enrolled: enrol a plate in
      // the dashboard and the next hit should be that plate, which is what
      // makes the ANPR demo land.
      const enrolled = blacklistedPlates();
      if (enrolled.length > 0 && Math.random() < 0.8) {
        const entry = pick(enrolled);
        return {
          rule: 'anpr',
          plate: entry.value,
          list_type: entry.list_type,
          watchlist_id: entry.id,
        };
      }
      return {
        rule: 'anpr',
        plate: `${pick(['HR', 'UP', 'WB', 'BR'])}${10 + Math.floor(Math.random() * 89)}${pick(['AK', 'DK', 'CQ'])}${1000 + Math.floor(Math.random() * 8999)}`,
        list_type: 'blacklist',
      };
    },
  },
];

const WEIGHTED_KINDS = EVENT_KINDS.flatMap((kind) => Array(kind.weight).fill(kind));

const pick = (items) => items[Math.floor(Math.random() * items.length)];

let nextEventId = 1;
const events = [];

function makeEvent(timestamp) {
  const kind = pick(WEIGHTED_KINDS);
  const extra = kind.extra();
  const id = nextEventId;
  nextEventId += 1;

  const event = {
    id,
    camera_id: pick(CAMERA_IDS),
    type: kind.type,
    timestamp,
    track_id: 1 + Math.floor(Math.random() * 200),
    confidence: +(0.72 + Math.random() * 0.27).toFixed(2),
    snapshot_path: `/snapshots/${id}.svg`,
    clip_path: `/clips/${id}.mp4`,
  };
  event.metadata_json = { reason: kind.reason(event, extra), ...extra };
  return event;
}

// Five days of history, thinning out towards the present so "today" isn't
// suspiciously busy.
function seedEvents(days = 5, perDay = 26) {
  const now = Date.now() / 1000;
  const seeded = [];
  for (let day = days; day >= 0; day -= 1) {
    const count = day === 0 ? Math.floor(perDay / 3) : perDay;
    for (let index = 0; index < count; index += 1) {
      // Day 0 spreads over the last twelve hours; earlier days fill their
      // whole 24h window. (Clamping a negative offset to zero would stack
      // every one of today's events on the same second.)
      const offset = day === 0 ? Math.random() * 43200 : (day + Math.random()) * 86400;
      seeded.push(makeEvent(Math.round(now - offset)));
    }
  }
  seeded.sort((a, b) => a.timestamp - b.timestamp);
  // Reassign ids so they run in chronological order, the way an autoincrement
  // primary key would.
  nextEventId = 1;
  for (const event of seeded) {
    event.id = nextEventId;
    event.snapshot_path = `/snapshots/${event.id}.svg`;
    event.clip_path = `/clips/${event.id}.mp4`;
    nextEventId += 1;
    events.push(event);
  }
}

seedEvents();

function queryEvents(params) {
  const cameraId = params.get('camera_id');
  const type = params.get('type');
  const from = Number(params.get('from'));
  const to = Number(params.get('to'));
  const search = (params.get('q') || '').trim().toLowerCase();
  const limit = Math.min(Number(params.get('limit')) || 25, 200);
  const offset = Math.max(Number(params.get('offset')) || 0, 0);

  const matched = events.filter((event) => {
    if (cameraId && event.camera_id !== cameraId) return false;
    if (type && event.type !== type) return false;
    if (from && event.timestamp < from) return false;
    if (to && event.timestamp > to) return false;
    if (search) {
      const haystack = [
        event.camera_id,
        event.type,
        `#${event.track_id}`,
        event.metadata_json?.reason || '',
      ].join(' ').toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    return true;
  });

  matched.sort((a, b) => b.timestamp - a.timestamp); // newest first
  return { events: matched.slice(offset, offset + limit), total: matched.length };
}

// --- snapshots and clips ---------------------------------------------------

const CLIP_FILE = process.env.MOCK_CLIP_FILE || join(
  dirname(fileURLToPath(import.meta.url)),
  '..', 'public', 'samples', 'sample-feed.mp4',
);

/**
 * A stand-in "frame grab": the real backend writes a JPEG cropped from the
 * frame that fired the rule. An SVG needs no encoder and still shows the
 * operator which camera, which box and when.
 */
function snapshotSvg(event) {
  const time = new Date(event.timestamp * 1000).toISOString().slice(11, 19);
  const boxX = 120 + ((event.id * 37) % 380);
  const boxY = 150 + ((event.id * 17) % 60);

  return `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <rect width="640" height="360" fill="#1a1f24"/>
  <rect y="268" width="640" height="2" fill="#2f3a44"/>
  <rect y="300" width="640" height="60" fill="#14181c" opacity="0.55"/>
  <polygon points="90,300 300,190 560,215 520,330" fill="#fbbf24" fill-opacity="0.12" stroke="#fbbf24" stroke-width="2"/>
  <rect x="${boxX}" y="${boxY}" width="34" height="78" fill="#f87171" fill-opacity="0.15" stroke="#f87171" stroke-width="2"/>
  <rect x="${boxX}" y="${boxY - 16}" width="74" height="15" fill="#f87171"/>
  <text x="${boxX + 4}" y="${boxY - 5}" font-family="monospace" font-size="11" fill="#0a0d10">#${event.track_id}</text>
  <text x="14" y="24" font-family="monospace" font-size="14" fill="#d4dae0">${event.camera_id} · ${event.type}</text>
  <text x="626" y="24" text-anchor="end" font-family="monospace" font-size="14" fill="#d4dae0">${time}</text>
</svg>`;
}

function sendClip(request, response) {
  let stat;
  try {
    stat = statSync(CLIP_FILE);
  } catch {
    return send(response, 404, { detail: 'sample clip missing' });
  }

  const range = /bytes=(\d*)-(\d*)/.exec(request.headers.range || '');
  const headers = {
    'Content-Type': 'video/mp4',
    'Accept-Ranges': 'bytes',
    'Access-Control-Allow-Origin': '*',
  };

  // Chrome re-requests with a Range header as soon as anyone scrubs the
  // timeline; answering 200 to that breaks seeking.
  if (range) {
    const start = range[1] ? Number(range[1]) : 0;
    const end = range[2] ? Number(range[2]) : stat.size - 1;
    if (start >= stat.size || end >= stat.size || start > end) {
      response.writeHead(416, { ...headers, 'Content-Range': `bytes */${stat.size}` });
      return response.end();
    }
    response.writeHead(206, {
      ...headers,
      'Content-Range': `bytes ${start}-${end}/${stat.size}`,
      'Content-Length': end - start + 1,
    });
    return createReadStream(CLIP_FILE, { start, end }).pipe(response);
  }

  response.writeHead(200, { ...headers, 'Content-Length': stat.size });
  return createReadStream(CLIP_FILE).pipe(response);
}

// --- alert broadcast -------------------------------------------------------

const alertSubscribers = new Set();

function emitAlert() {
  const event = makeEvent(Math.round(Date.now() / 1000));
  events.push(event);

  const payload = JSON.stringify(event);
  for (const socket of alertSubscribers) {
    if (socket.readyState === socket.OPEN) socket.send(payload);
  }
  console.log(`[mock] alert #${event.id} ${event.type} on ${event.camera_id}`);

  // Irregular spacing: a fixed metronome reads as fake in a demo.
  setTimeout(emitAlert, 4000 + Math.random() * 7000);
}

setTimeout(emitAlert, 2500);

// --- fence store -----------------------------------------------------------

const FENCE_FILE = join(dirname(fileURLToPath(import.meta.url)), 'fences.json');

function readFences() {
  try {
    return JSON.parse(readFileSync(FENCE_FILE, 'utf8'));
  } catch {
    return {}; // no file yet, or someone truncated it — start clean
  }
}

function writeFences(fences) {
  writeFileSync(FENCE_FILE, `${JSON.stringify(fences, null, 2)}\n`);
}

const FENCE_RULES = { polygon: { min: 3, max: Infinity }, tripwire: { min: 2, max: 2 } };

function validateFence(body) {
  const rules = FENCE_RULES[body?.type];
  if (!rules) return 'type must be "polygon" or "tripwire"';
  if (!Array.isArray(body.points)) return 'points must be an array';
  if (body.points.length < rules.min) return `${body.type} needs at least ${rules.min} points`;
  if (body.points.length > rules.max) return `${body.type} takes at most ${rules.max} points`;

  const malformed = body.points.some(
    (point) => !Array.isArray(point) || point.length !== 2
      || point.some((value) => typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1),
  );
  if (malformed) return 'each point must be [x, y] with both values between 0 and 1';
  return null;
}

// --- http ------------------------------------------------------------------

function send(response, status, body) {
  const payload = body === undefined ? '' : JSON.stringify(body);
  response.writeHead(status, {
    // A 204 carries no entity, and declaring a content type for one makes
    // Chrome log the request as net::ERR_ABORTED even though the fetch
    // resolved fine.
    ...(payload ? { 'Content-Type': 'application/json' } : {}),
    // The dashboard runs on :3000 and this server on :8787, so every fence
    // call is cross-origin.
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  });
  response.end(payload);
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let raw = '';
    request.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 64 * 1024) reject(new Error('body too large'));
    });
    request.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error('invalid JSON'));
      }
    });
    request.on('error', reject);
  });
}

async function handleRequest(request, response) {
  if (request.method === 'OPTIONS') return send(response, 204);

  const [path, search] = (request.url || '').split('?');

  if (path === '/api/events' && request.method === 'GET') {
    return send(response, 200, queryEvents(new URLSearchParams(search || '')));
  }

  if (path === '/api/watchlist') {
    const entries = readWatchlist();

    if (request.method === 'GET') {
      const kind = new URLSearchParams(search || '').get('kind');
      const filtered = kind ? entries.filter((entry) => entry.kind === kind) : entries;
      return send(response, 200, {
        entries: [...filtered].sort((a, b) => b.created_at - a.created_at),
      });
    }

    if (request.method === 'POST') {
      let body;
      try {
        body = await readBody(request);
      } catch (cause) {
        return send(response, 400, { detail: cause.message });
      }

      const problem = validateEntry(body);
      if (problem) return send(response, 400, { detail: problem });

      const value = normalizePlate(body.value);
      if (entries.some((entry) => entry.kind === body.kind && entry.value === value)) {
        return send(response, 409, { detail: `${value} is already enrolled` });
      }

      const entry = {
        id: entries.reduce((max, current) => Math.max(max, current.id), 0) + 1,
        kind: body.kind,
        value,
        list_type: body.list_type,
        note: String(body.note || '').slice(0, 200),
        created_at: Date.now() / 1000,
      };
      entries.push(entry);
      writeWatchlist(entries);
      console.log(`[mock] enrolled ${entry.value} (${entry.list_type})`);
      return send(response, 201, entry);
    }

    return send(response, 405, { detail: 'method not allowed' });
  }

  const watchlistEntry = /^\/api\/watchlist\/(\d+)$/.exec(path);
  if (watchlistEntry && request.method === 'DELETE') {
    const entries = readWatchlist();
    const remaining = entries.filter((entry) => entry.id !== Number(watchlistEntry[1]));
    if (remaining.length !== entries.length) {
      writeWatchlist(remaining);
      console.log(`[mock] removed watchlist entry ${watchlistEntry[1]}`);
    }
    return send(response, 204);
  }

  const snapshot = /^\/snapshots\/(\d+)\.svg$/.exec(path);
  if (snapshot) {
    const event = events.find((entry) => entry.id === Number(snapshot[1]));
    if (!event) return send(response, 404, { detail: 'no such event' });
    response.writeHead(200, {
      'Content-Type': 'image/svg+xml',
      'Cache-Control': 'public, max-age=3600',
      'Access-Control-Allow-Origin': '*',
    });
    return response.end(snapshotSvg(event));
  }

  if (/^\/clips\/\d+\.mp4$/.test(path)) return sendClip(request, response);

  const match = /^\/api\/fences\/(.+)$/.exec(path);
  if (!match) return send(response, 404, { detail: 'not found' });

  const cameraId = decodeURIComponent(match[1]);
  const fences = readFences();

  if (request.method === 'GET') {
    // 200 with a null body rather than 404: a camera without a fence is a
    // normal state, and answering 404 logs a red error in the operator's
    // console on every page load.
    return send(response, 200, fences[cameraId] ?? null);
  }

  if (request.method === 'PUT') {
    let body;
    try {
      body = await readBody(request);
    } catch (cause) {
      return send(response, 400, { detail: cause.message });
    }

    const problem = validateFence(body);
    if (problem) return send(response, 400, { detail: problem });

    const fence = {
      camera_id: cameraId,
      type: body.type,
      points: body.points,
      updated_at: Date.now() / 1000,
    };
    fences[cameraId] = fence;
    writeFences(fences);
    console.log(`[mock] ${cameraId} fence saved (${body.type}, ${body.points.length} pts)`);
    return send(response, 200, fence);
  }

  if (request.method === 'DELETE') {
    if (fences[cameraId]) {
      delete fences[cameraId];
      writeFences(fences);
      console.log(`[mock] ${cameraId} fence cleared`);
    }
    return send(response, 204);
  }

  return send(response, 405, { detail: 'method not allowed' });
}

// --- server ----------------------------------------------------------------

const httpServer = createServer((request, response) => {
  handleRequest(request, response).catch((cause) => {
    console.error('[mock]', cause);
    send(response, 500, { detail: 'mock server error' });
  });
});

const server = new WebSocketServer({ server: httpServer });

server.on('connection', (socket, request) => {
  const path = (request.url || '').split('?')[0];

  if (path.startsWith('/ws/alerts')) {
    alertSubscribers.add(socket);
    console.log('[mock] alert subscriber connected');
    socket.on('close', () => {
      alertSubscribers.delete(socket);
      console.log('[mock] alert subscriber disconnected');
    });
    return;
  }

  const cameraId = decodeURIComponent(path.split('/').filter(Boolean).pop() || 'UNKNOWN');
  const phase = phaseFor(cameraId);
  const startedAt = Date.now();
  let frameId = 0;

  console.log(`[mock] ${cameraId} connected`);

  const timer = setInterval(() => {
    if (socket.readyState !== socket.OPEN) return;

    const elapsed = phase + (Date.now() - startedAt) / 1000;
    frameId += 1;

    socket.send(
      JSON.stringify({
        camera_id: cameraId,
        frame_id: frameId,
        ts: Date.now() / 1000,
        fps: +(FPS + jitter(1.4)).toFixed(1),
        // Mostly comfortable, with an occasional spike so the readout's
        // warning colours are actually exercised.
        latency_ms: Math.round(Math.random() < 0.02 ? 900 + jitter(400) : 85 + jitter(50)),
        tracks: tracksAt(elapsed),
      }),
    );
  }, 1000 / FPS);

  socket.on('close', () => {
    clearInterval(timer);
    console.log(`[mock] ${cameraId} disconnected`);
  });
});

httpServer.listen(PORT, () => {
  console.log(`[mock] track stream  ws://localhost:${PORT}/ws/tracks/<camera_id>`);
  console.log(`[mock] fence api     http://localhost:${PORT}/api/fences/<camera_id>`);
  console.log(`[mock] alert stream  ws://localhost:${PORT}/ws/alerts`);
  console.log(`[mock] event log     http://localhost:${PORT}/api/events`);
  console.log(`[mock] watchlist     http://localhost:${PORT}/api/watchlist`);
  console.log(`[mock] seeded ${events.length} historical events`);
});
