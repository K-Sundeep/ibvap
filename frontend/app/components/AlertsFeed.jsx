'use client';

import { useRef, useState } from 'react';
import EventIcon from './EventIcon';
import useNow from '../hooks/useNow';
import { eventMatch, eventMetric, eventReason, eventType, mediaUrl } from '../lib/eventsApi';
import { LIST_TYPES } from '../lib/watchlistApi';
import { formatClock, formatRelative } from '../lib/time';

/**
 * AlertsFeed — live alerts as they fire, newest first.
 *
 * The whole point is that an alert is impossible to miss: rows animate in and
 * flash for a couple of seconds, the newest is always at the top, and if the
 * operator has scrolled down a "new alerts" button brings them back rather
 * than the list silently growing above them.
 */
const FLASH_WINDOW_MS = 3000;

export default function AlertsFeed({ alerts, status, received, cameras, onSelect }) {
  const listRef = useRef(null);
  const now = useNow();
  const [atTop, setAtTop] = useState(true);
  const [lastSeenAt, setLastSeenAt] = useState(() => Date.now());

  const cameraName = (id) => cameras.find((camera) => camera.id === id)?.name || id;
  const unseen = atTop ? 0 : alerts.filter((alert) => alert.receivedAt > lastSeenAt).length;

  const handleScroll = (event) => {
    const isTop = event.currentTarget.scrollTop <= 8;
    if (isTop === atTop) return;
    setAtTop(isTop);
    // The baseline moves whenever they arrive at or leave the top, so "new"
    // means arrived since they last had eyes on the newest row — not since
    // the page loaded.
    setLastSeenAt(Date.now());
  };

  const jumpToTop = () => {
    listRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
    setLastSeenAt(Date.now());
    setAtTop(true);
  };

  return (
    <section className="flex min-h-[18rem] max-h-[calc(100vh-8rem)] flex-col overflow-hidden rounded-lg border border-white/10 bg-panel">
      <header className="flex items-center justify-between gap-3 border-b border-white/10 px-3 py-2.5">
        <h2 className="text-sm font-medium text-slate-100">Live alerts</h2>
        <StreamBadge status={status} received={received} />
      </header>

      <div className="relative min-h-0 flex-1">
        {unseen > 0 ? (
          <button
            type="button"
            onClick={jumpToTop}
            className="absolute inset-x-0 top-2 z-10 mx-auto w-fit rounded-full bg-red-500 px-3 py-1 text-[11px] font-medium text-white shadow-lg transition-colors hover:bg-red-400 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80"
          >
            {unseen} new alert{unseen === 1 ? '' : 's'} ↑
          </button>
        ) : null}

        <ul ref={listRef} onScroll={handleScroll} className="h-full divide-y divide-white/5 overflow-y-auto">
          {alerts.length === 0 ? (
            <li className="px-3 py-8 text-center text-xs text-slate-500">
              {status === 'open'
                ? 'Connected — waiting for the first alert'
                : 'Alert stream offline'}
            </li>
          ) : (
            alerts.map((alert) => (
              <AlertRow
                key={alert.id}
                alert={alert}
                cameraName={cameraName(alert.camera_id)}
                now={now}
                onSelect={onSelect}
              />
            ))
          )}
        </ul>
      </div>
    </section>
  );
}

function AlertRow({ alert, cameraName, now, onSelect }) {
  const type = eventType(alert.type);
  const fresh = now - alert.receivedAt < FLASH_WINDOW_MS;
  const snapshot = mediaUrl(alert.snapshot_path);
  // Every type carries its own accent and its own headline figure: the
  // matched plate for a watchlist hit, dwell time for loitering, lux for
  // night movement. A watchlist hit additionally tints the row — it is the
  // only alert that names a specific vehicle or person.
  const match = eventMatch(alert);
  const metric = eventMetric(alert);

  return (
    <li className={`border-l-2 ${type.accent} ${type.tint || ''} ${fresh ? 'alert-enter' : ''}`}>
      <button
        type="button"
        onClick={() => onSelect(alert)}
        className="flex w-full gap-3 px-3 py-2.5 text-left transition-colors hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80"
      >
        {snapshot ? (
          // eslint-disable-next-line @next/next/no-img-element -- backend-served snapshot, not a bundled asset: next/image would need the backend host allow-listed for no benefit
          <img
            src={snapshot}
            alt=""
            width={72}
            height={41}
            loading="lazy"
            className="h-[41px] w-[72px] shrink-0 rounded border border-white/10 object-cover"
          />
        ) : null}

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className={`flex shrink-0 items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${type.chip}`}>
              <EventIcon type={alert.type} className="h-3 w-3" />
              {type.label}
            </span>
            <span className="shrink-0 font-mono text-[10px] text-slate-500" title={formatClock(alert.timestamp)}>
              {formatRelative(alert.timestamp, now)}
            </span>
          </div>

          <p className="mt-1 truncate text-xs text-slate-200">
            {cameraName} <span className="font-mono text-slate-500">{alert.camera_id}</span>
          </p>
          {match ? <MatchBadge match={match} /> : null}
          {metric ? <MetricBadge metric={metric} type={type} /> : null}

          {/* Every alert says why it fired — the platform's explainability
              promise, not a bare confidence score. */}
          <p className="line-clamp-2 text-[11px] text-slate-400">{eventReason(alert)}</p>
        </div>
      </button>
    </li>
  );
}

/** The matched plate (or face), sized to be read from across a demo room. */
export function MatchBadge({ match, size = 'sm' }) {
  const listSpec = LIST_TYPES[match.listType] || LIST_TYPES.blacklist;

  return (
    <span className="my-1 flex flex-wrap items-center gap-1.5">
      <span className={`rounded bg-black/40 px-1.5 py-0.5 font-mono tracking-wider text-fuchsia-200 ring-1 ring-fuchsia-500/40 ${
        size === 'lg' ? 'text-base' : 'text-xs'
      }`}>
        {match.value}
      </span>
      <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${listSpec.chip}`}>
        {listSpec.label}
      </span>
    </span>
  );
}

/** The headline figure for the non-identity alert types. */
function MetricBadge({ metric, type }) {
  return (
    <span className="my-1 flex flex-wrap items-baseline gap-1.5">
      <span className={`rounded bg-black/40 px-1.5 py-0.5 font-mono text-xs tracking-wide ring-1 ${type.chip}`}>
        {metric.value}
      </span>
      {metric.detail ? (
        <span className="font-mono text-[10px] text-slate-500">{metric.detail}</span>
      ) : null}
    </span>
  );
}

function StreamBadge({ status, received }) {
  const styles = {
    open: { dot: 'bg-emerald-400', text: 'text-emerald-300', label: 'LIVE' },
    connecting: { dot: 'bg-amber-400', text: 'text-amber-300', label: 'CONNECTING' },
    closed: { dot: 'bg-red-500', text: 'text-red-300', label: 'OFFLINE' },
  }[status] || { dot: 'bg-slate-500', text: 'text-slate-400', label: 'UNKNOWN' };

  return (
    <span className={`flex items-center gap-2 font-mono text-[11px] ${styles.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${styles.dot}`} />
      <span>{styles.label}</span>
      <span className="text-slate-500">· {received}</span>
    </span>
  );
}
