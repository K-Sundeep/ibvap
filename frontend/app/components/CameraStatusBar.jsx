'use client';

import { useEffect, useState } from 'react';
import EventIcon from './EventIcon';
import useNow from '../hooks/useNow';
import { eventType, fetchEvents } from '../lib/eventsApi';
import { formatRelative } from '../lib/time';

/**
 * CameraStatusBar — which camera is busy right now.
 *
 * The tiles below show what each camera sees; this says where the activity
 * is — the question an operator watching four feeds actually asks.
 *
 * Counts come from the live alert stream, seeded once from history so the
 * window is honest the moment the page loads: without the seed a camera that
 * had been firing all morning would read "quiet" until the next alert landed,
 * which is exactly the wrong thing to tell someone mid-demo.
 */
const WINDOW_SECONDS = 5 * 60;

export default function CameraStatusBar({ cameras, alerts }) {
  const now = useNow();
  const [seed, setSeed] = useState([]);

  useEffect(() => {
    const controller = new AbortController();

    fetchEvents(
      { from: Math.floor(Date.now() / 1000) - WINDOW_SECONDS, limit: 200 },
      { signal: controller.signal },
    )
      .then((data) => setSeed(data.events || []))
      .catch(() => {
        // History unavailable: fall back to live alerts only rather than
        // blanking the strip.
      });

    return () => controller.abort();
  }, []);

  const since = now / 1000 - WINDOW_SECONDS;
  const seenIds = new Set(alerts.map((alert) => alert.id));
  const events = [...alerts, ...seed.filter((event) => !seenIds.has(event.id))]
    .filter((event) => event.timestamp >= since);

  return (
    <ul className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      {cameras.map((camera) => {
        const recent = events.filter((event) => event.camera_id === camera.id);
        const latest = recent.reduce(
          (newest, event) => (!newest || event.timestamp > newest.timestamp ? event : newest),
          null,
        );
        const type = latest ? eventType(latest.type) : null;

        return (
          <li
            key={camera.id}
            className={`rounded-lg border border-white/10 bg-panel px-3 py-2 ${
              latest ? `border-l-2 ${type.accent}` : ''
            }`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-xs font-medium text-slate-200">{camera.name}</span>
              <span className="shrink-0 font-mono text-[10px] text-slate-500">{camera.id}</span>
            </div>

            <div className="mt-1 flex items-center justify-between gap-2">
              <span className={`font-mono text-[11px] ${recent.length ? 'text-slate-200' : 'text-slate-600'}`}>
                {recent.length} alert{recent.length === 1 ? '' : 's'}
                <span className="text-slate-600"> / 5 min</span>
              </span>

              {latest ? (
                <span className={`flex shrink-0 items-center gap-1 font-mono text-[10px] ${type.chip.split(' ')[1]}`}>
                  <EventIcon type={latest.type} className="h-3 w-3" />
                  {formatRelative(latest.timestamp, now)}
                </span>
              ) : (
                <span className="font-mono text-[10px] text-slate-600">quiet</span>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
