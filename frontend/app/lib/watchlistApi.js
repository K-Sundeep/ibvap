/**
 * Watchlist API client — ANPR plate list for Phase 3.
 *
 *   GET    /api/watchlist?kind=plate  → { entries: [...] }
 *   POST   /api/watchlist             → 201 entry   body: { kind, value, list_type, note }
 *   DELETE /api/watchlist/<id>        → 204
 *
 *   {
 *     "id": 3,
 *     "kind": "plate",
 *     "value": "HR26DK8337",          // normalized: upper case, no spaces or dashes
 *     "list_type": "blacklist",       // or "whitelist"
 *     "note": "flagged by sector HQ",
 *     "created_at": 1756100000.123
 *   }
 *
 * `kind` is in the schema so the same table can hold face entries later
 * without a second endpoint — but only plates are enrolled today.
 */
import { API_BASE } from './backend';

export const LIST_TYPES = {
  blacklist: {
    label: 'Blacklist',
    chip: 'bg-red-500/15 text-red-300 ring-red-500/30',
    hint: 'Alert whenever this plate is seen',
  },
  whitelist: {
    label: 'Whitelist',
    chip: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
    hint: 'Known vehicle — logged, no alert',
  },
};

/** Plates are compared after normalizing, so "HR 26 DK 8337" matches the OCR output. */
export const normalizePlate = (value) => value.toUpperCase().replace(/[^A-Z0-9]/g, '');

export function validatePlate(value) {
  const plate = normalizePlate(value);
  if (!plate) return 'Enter a plate number';
  if (plate.length < 4) return 'Too short to be a plate';
  if (plate.length > 12) return 'Too long to be a plate';
  return null;
}

export async function fetchWatchlist({ signal } = {}) {
  const response = await fetch(`${API_BASE}/api/watchlist?kind=plate`, { signal });
  if (!response.ok) throw new Error(`load failed (${response.status})`);
  return response.json();
}

export async function addWatchlistEntry({ value, listType, note }) {
  const response = await fetch(`${API_BASE}/api/watchlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      kind: 'plate',
      value: normalizePlate(value),
      list_type: listType,
      note: note?.trim() || '',
    }),
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `save failed (${response.status})`);
  }
  return response.json();
}

export async function removeWatchlistEntry(id) {
  const response = await fetch(`${API_BASE}/api/watchlist/${id}`, { method: 'DELETE' });
  if (!response.ok && response.status !== 404) {
    throw new Error(`delete failed (${response.status})`);
  }
}
