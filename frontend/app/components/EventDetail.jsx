'use client';

import { useEffect, useRef } from 'react';
import { MatchBadge } from './AlertsFeed';
import EventIcon from './EventIcon';
import { eventMatch, eventMetadata, eventReason, eventType, mediaUrl } from '../lib/eventsApi';
import { formatDateTime } from '../lib/time';

/**
 * EventDetail — the evidence behind one alert: snapshot, clip, and the
 * rule's own account of why it fired. Opened from both the live feed and the
 * event log, so the operator's path from "something happened" to "here is
 * what happened" is one click either way.
 */
export default function EventDetail({ event, cameras, onClose }) {
  const panelRef = useRef(null);

  useEffect(() => {
    if (!event) return undefined;

    const previouslyFocused = document.activeElement;
    panelRef.current?.focus();

    const onKeyDown = (keyEvent) => {
      if (keyEvent.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);

    return () => {
      window.removeEventListener('keydown', onKeyDown);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [event, onClose]);

  if (!event) return null;

  const type = eventType(event.type);
  const metadata = eventMetadata(event);
  const snapshot = mediaUrl(event.snapshot_path);
  const clip = mediaUrl(event.clip_path);
  const camera = cameras.find((entry) => entry.id === event.camera_id);
  const match = eventMatch(event);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4"
      onClick={(clickEvent) => {
        if (clickEvent.target === clickEvent.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={`${type.label} on ${event.camera_id}`}
        className="max-h-full w-full max-w-4xl overflow-y-auto rounded-lg border border-white/10 bg-panel shadow-2xl outline-none"
      >
        <header className="flex items-start justify-between gap-3 border-b border-white/10 px-4 py-3">
          <div>
            <div className="flex items-center gap-2">
              <span className={`flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${type.chip}`}>
                <EventIcon type={event.type} />
                {type.label}
              </span>
              <span className="font-mono text-xs text-slate-400">event #{event.id}</span>
            </div>
            <h2 className="mt-1 text-sm font-medium text-slate-100">
              {camera?.name || event.camera_id}
              <span className="ml-2 font-mono text-xs text-slate-500">{event.camera_id}</span>
            </h2>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="rounded bg-white/5 px-2 py-1 text-xs text-slate-300 transition-colors hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80"
          >
            Close
          </button>
        </header>

        <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="space-y-3">
            {snapshot ? (
              // eslint-disable-next-line @next/next/no-img-element -- backend-served snapshot, not a bundled asset: next/image would need the backend host allow-listed for no benefit
              <img src={snapshot} alt="Alert snapshot" className="w-full rounded border border-white/10" />
            ) : null}

            {clip ? (
              // The snapshot doubles as the poster, so the clip shows the moment
              // that fired instead of a black rectangle.
              <video
                src={clip}
                poster={snapshot || undefined}
                controls
                playsInline
                preload="metadata"
                className="w-full rounded border border-white/10"
              />
            ) : null}
          </div>

          <div>
            {match ? (
              <div className="mb-2 rounded border border-fuchsia-500/30 bg-fuchsia-500/[0.07] px-3 py-2">
                <p className="font-mono text-[10px] uppercase tracking-wide text-fuchsia-300/70">
                  matched {match.label}
                </p>
                <MatchBadge match={match} size="lg" />
              </div>
            ) : null}

            <p className="rounded border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-200">
              {eventReason(event)}
            </p>

            <dl className="mt-3 space-y-2 text-xs">
              <Row label="Time">{formatDateTime(event.timestamp)}</Row>
              <Row label="Track">{event.track_id === null || event.track_id === undefined ? '—' : `#${event.track_id}`}</Row>
              <Row label="Confidence">
                {typeof event.confidence === 'number' ? event.confidence.toFixed(2) : '—'}
              </Row>
              <Row label="Severity">{type.severity}</Row>
            </dl>

            {Object.keys(metadata).length > 0 ? (
              <>
                <h3 className="mt-4 font-mono text-[10px] uppercase tracking-wide text-slate-500">
                  metadata_json
                </h3>
                <pre className="mt-1 whitespace-pre-wrap break-words rounded border border-white/10 bg-black/40 p-2 font-mono text-[10px] text-slate-300">
                  {JSON.stringify(metadata, null, 2)}
                </pre>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ label, children }) {
  return (
    <div className="flex justify-between gap-3 border-b border-white/5 pb-1.5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-mono text-slate-200">{children}</dd>
    </div>
  );
}
