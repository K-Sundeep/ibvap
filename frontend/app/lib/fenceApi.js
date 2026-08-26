/**
 * Virtual fence REST client.
 *
 * Contract (one fence per camera):
 *
 *   GET    /api/fences/<camera_id>   → 200 fence, or 200 null when none is set
 *   PUT    /api/fences/<camera_id>   → 200 saved fence   body: { type, points }
 *   DELETE /api/fences/<camera_id>   → 204
 *
 *   {
 *     "camera_id":  "CAM-01",
 *     "type":       "polygon",              // or "tripwire"
 *     "points":     [[0.2, 0.4], [0.7, 0.4], [0.7, 0.9]],
 *     "updated_at": 1756100000.123
 *   }
 *
 * Points are normalized 0-1, same convention as track boxes, so a fence drawn
 * on a 640x360 preview still means the same thing to a worker reading 1080p.
 */
import { API_BASE } from './backend';

export const FENCE_TYPES = {
  polygon: { label: 'Polygon', minPoints: 3, maxPoints: Infinity },
  tripwire: { label: 'Tripwire', minPoints: 2, maxPoints: 2 },
};

export function isFenceComplete(type, points) {
  const spec = FENCE_TYPES[type];
  return Boolean(spec) && points.length >= spec.minPoints;
}

export function canAddPoint(type, points) {
  const spec = FENCE_TYPES[type];
  return Boolean(spec) && points.length < spec.maxPoints;
}

const fenceUrl = (cameraId) => `${API_BASE}/api/fences/${encodeURIComponent(cameraId)}`;

// Four decimals is ~0.2px at 1080p — plenty, and it keeps stored fences readable.
const round = (value) => Math.round(value * 10000) / 10000;

export async function fetchFence(cameraId, { signal } = {}) {
  const response = await fetch(fenceUrl(cameraId), { signal });
  // 404 is still tolerated in case the backend answers that way instead.
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`load failed (${response.status})`);
  return response.json();
}

export async function putFence(cameraId, { type, points }) {
  const response = await fetch(fenceUrl(cameraId), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, points: points.map(([x, y]) => [round(x), round(y)]) }),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(detail || `save failed (${response.status})`);
  }
  return response.json();
}

export async function deleteFence(cameraId) {
  const response = await fetch(fenceUrl(cameraId), { method: 'DELETE' });
  if (!response.ok && response.status !== 404) {
    throw new Error(`clear failed (${response.status})`);
  }
}
