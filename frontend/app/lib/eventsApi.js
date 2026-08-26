/**
 * Event / alert API client.
 *
 * Both the live alert socket and the history endpoint carry the same record —
 * the event schema the whole platform is built around:
 *
 *   { id, camera_id, type, timestamp, track_id, confidence,
 *     snapshot_path, clip_path, metadata_json }
 *
 *   GET /api/events?camera_id=&type=&from=&to=&q=&limit=&offset=
 *     → { events: [...], total: 1234 }
 *   ws  /ws/alerts   → one event object per message, pushed as it fires
 *
 * `from` / `to` are epoch seconds, so the client owns the timezone question
 * and the backend never has to guess what "2026-08-25" means.
 */
import { API_BASE, WS_BASE } from './backend';

export const ALERT_STREAM_URL = `${WS_BASE}/ws/alerts`;

/**
 * The alert types the rules engine emits. `reason` is the fallback for the
 * explainability line — every alert has to say why it fired, not just score.
 */
export const EVENT_TYPES = {
  intrusion: {
    label: 'Intrusion',
    severity: 'critical',
    dot: 'bg-red-400',
    chip: 'bg-red-500/15 text-red-300 ring-red-500/30',
    accent: 'border-l-red-400/70',
    reason: 'track crossed the virtual fence',
  },
  watchlist_hit: {
    label: 'Watchlist hit',
    severity: 'critical',
    dot: 'bg-fuchsia-400',
    chip: 'bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-500/30',
    accent: 'border-l-fuchsia-400/70',
    tint: 'bg-fuchsia-500/[0.07]',
    reason: 'match against enrolled watchlist',
  },
  loitering: {
    label: 'Loitering',
    severity: 'warning',
    dot: 'bg-amber-400',
    chip: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
    accent: 'border-l-amber-400/70',
    reason: 'dwell time over threshold',
  },
  night_movement: {
    label: 'Night movement',
    severity: 'warning',
    dot: 'bg-sky-400',
    chip: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
    accent: 'border-l-sky-400/70',
    reason: 'motion detected during night hours',
  },
};

export const UNKNOWN_TYPE = {
  label: 'Event',
  severity: 'info',
  dot: 'bg-slate-400',
  chip: 'bg-slate-500/15 text-slate-300 ring-slate-500/30',
  accent: 'border-l-slate-500/70',
  reason: 'rule fired',
};

export const eventType = (type) => EVENT_TYPES[type] || UNKNOWN_TYPE;

/**
 * SQLite stores metadata as a JSON string, so depending on how the route
 * serializes it we may get an object or a string. Accept either.
 */
export function eventMetadata(event) {
  const raw = event?.metadata_json ?? event?.metadata;
  if (!raw) return {};
  if (typeof raw === 'object') return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

export function eventReason(event) {
  return eventMetadata(event).reason || eventType(event?.type).reason;
}

/**
 * For a watchlist hit, the thing an operator actually needs to read: which
 * plate (or which enrolled face) matched, and which list it is on. Returns
 * null for alert types where there is nothing matched.
 */
export function eventMatch(event) {
  if (event?.type !== 'watchlist_hit') return null;
  const metadata = eventMetadata(event);

  if (metadata.plate) {
    return { label: 'plate', value: metadata.plate, listType: metadata.list_type || 'blacklist' };
  }
  if (metadata.watchlist_id) {
    return {
      label: 'face',
      value: metadata.name || `entry #${metadata.watchlist_id}`,
      listType: metadata.list_type || 'blacklist',
    };
  }
  return null;
}

/**
 * The figure that makes each alert type judgeable at a glance — the same job
 * the matched plate does for a watchlist hit. Null when the rule didn't send
 * one, so the row falls back to its reason line alone.
 */
export function eventMetric(event) {
  const metadata = eventMetadata(event);

  switch (event?.type) {
    case 'loitering':
      return metadata.dwell_seconds
        ? {
          value: `${metadata.dwell_seconds}s dwell`,
          detail: metadata.threshold_seconds ? `limit ${metadata.threshold_seconds}s` : null,
        }
        : null;
    // No detail line for these two: the chip already says "night movement",
    // and the reason line already says the track crossed — repeating it beside
    // the figure is noise on every row.
    case 'night_movement':
      return metadata.lux === undefined ? null : { value: `${metadata.lux} lux`, detail: null };
    case 'intrusion':
      return metadata.direction
        ? { value: metadata.direction.toUpperCase(), detail: null }
        : null;
    default:
      return null;
  }
}

/** Resolves a stored path (`/snapshots/12.svg`) against the backend host. */
export function mediaUrl(path) {
  if (!path) return null;
  return /^https?:\/\//.test(path) ? path : `${API_BASE}${path}`;
}

export async function fetchEvents(filters = {}, { signal } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, value);
  }

  const url = `${API_BASE}/api/events?${params}`;
  const response = await fetch(url, { signal }).catch(() => {
    // A refused connection reads as a bare "Failed to fetch"; say where.
    throw new Error(`no response from ${API_BASE}`);
  });
  if (!response.ok) throw new Error(`event query failed (${response.status})`);
  return response.json();
}
