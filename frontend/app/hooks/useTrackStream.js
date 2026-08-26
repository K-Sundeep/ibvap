'use client';

import { useEffect, useRef, useState } from 'react';
import { openReconnectingSocket } from '../lib/reconnectingSocket';
import { WS_BASE } from '../lib/backend';

/**
 * Subscribes to one camera's live track stream.
 *
 * Contract (backend → dashboard), one socket per camera:
 *
 *   ws://<host>/ws/tracks/<camera_id>
 *
 *   {
 *     "camera_id":  "CAM-01",
 *     "frame_id":   1234,
 *     "ts":         1756100000.123,   // capture time, epoch seconds
 *     "fps":        14.8,             // backend processing rate
 *     "latency_ms": 82,               // capture → publish, measured backend-side
 *     "tracks": [
 *       { "track_id": 7, "cls": "person", "conf": 0.91,
 *         "bbox": [0.42, 0.55, 0.08, 0.30] }   // x, y, w, h as 0-1 fractions
 *     ]
 *   }
 *
 * Boxes arrive normalized so the overlay never needs to know the source
 * resolution — it scales to whatever the tile is currently rendering.
 *
 * Frames land on a ref, not in state: at 15-30 fps per camera across four
 * tiles, a setState per message would re-render the tree hundreds of times a
 * second. The canvas overlay reads the ref inside the shared rAF loop, and
 * only the human-readable stats are pushed into React, twice a second.
 */
const STATS_INTERVAL_MS = 500;

export function trackStreamUrl(cameraId) {
  return `${WS_BASE}/ws/tracks/${encodeURIComponent(cameraId)}`;
}

const numberOr = (value, fallback = null) =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

export default function useTrackStream(cameraId) {
  const frameRef = useRef(null);
  const [status, setStatus] = useState('connecting');
  const [stats, setStats] = useState({ fps: null, latencyMs: null, trackCount: 0 });

  useEffect(() => {
    if (!cameraId) return undefined;

    let lastStatsAt = 0;

    return openReconnectingSocket(trackStreamUrl(cameraId), {
      onStatus: (next) => {
        setStatus(next);
        if (next !== 'open') frameRef.current = null;
      },
      onMessage: (message) => {
        if (!message || !Array.isArray(message.tracks)) return;

        const now = performance.now();
        // New object identity per frame — the overlay uses it to tell whether
        // there is anything new to draw.
        frameRef.current = { tracks: message.tracks, receivedAt: now };

        if (now - lastStatsAt >= STATS_INTERVAL_MS) {
          lastStatsAt = now;
          setStats({
            fps: numberOr(message.fps),
            latencyMs: numberOr(message.latency_ms),
            trackCount: message.tracks.length,
          });
        }
      },
    });
  }, [cameraId]);

  return { frameRef, status, stats };
}
