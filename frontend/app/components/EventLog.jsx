'use client';

import { useEffect, useMemo, useState } from 'react';
import Button from './ui/Button';
import EventIcon from './EventIcon';
import { EVENT_TYPES, eventMatch, eventReason, eventType, fetchEvents } from '../lib/eventsApi';
import { endOfDay, formatDateTime, startOfDay } from '../lib/time';

/**
 * EventLog — the searchable history behind the live feed.
 *
 * Filtering happens on the backend (the table is one page of a SQLite query,
 * not a filtered copy of everything ever seen), so this stays honest when the
 * store holds weeks of events rather than the fifty the feed keeps in memory.
 */
const PAGE_SIZE = 25;
const SEARCH_DEBOUNCE_MS = 300;

const EMPTY_FILTERS = { camera_id: '', type: '', from: '', to: '', q: '' };

export default function EventLog({ cameras, liveCount, onSelect }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [page, setPage] = useState(0);
  const [result, setResult] = useState({ events: [], total: 0 });
  const [state, setState] = useState('loading'); // loading | ready | error
  const [error, setError] = useState(null);
  // Alerts that arrived since this page was fetched — offered as a refresh
  // rather than yanking the table out from under whoever is reading it.
  const [liveCountAtFetch, setLiveCountAtFetch] = useState(liveCount);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(filters.q), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [filters.q]);

  const query = useMemo(() => ({
    camera_id: filters.camera_id,
    type: filters.type,
    from: filters.from ? startOfDay(filters.from) : '',
    to: filters.to ? endOfDay(filters.to) : '',
    q: debouncedQuery,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  }), [filters.camera_id, filters.type, filters.from, filters.to, debouncedQuery, page]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    const run = async () => {
      setState('loading');
      try {
        const data = await fetchEvents(query, { signal: controller.signal });
        if (!active) return;
        setResult({ events: data.events || [], total: data.total || 0 });
        setState('ready');
        setError(null);
        setLiveCountAtFetch(liveCount);
      } catch (cause) {
        if (!active || controller.signal.aborted) return;
        setState('error');
        setError(cause.message || 'query failed');
      }
    };
    run();

    return () => {
      active = false;
      controller.abort();
    };
    // liveCount is deliberately not a dependency: new alerts offer a refresh,
    // they don't refetch under the operator.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, reloadToken]);

  const update = (patch) => {
    setFilters((current) => ({ ...current, ...patch }));
    setPage(0);
  };

  const pendingLive = Math.max(0, liveCount - liveCountAtFetch);
  const showing = result.events.length;
  const firstIndex = page * PAGE_SIZE;

  return (
    <section className="rounded-lg border border-white/10 bg-panel">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-3 py-2.5">
        <h2 className="text-sm font-medium text-slate-100">Event log</h2>
        <div className="flex items-center gap-2">
          {pendingLive > 0 ? (
            <Button primary onClick={() => setReloadToken((token) => token + 1)}>
              {pendingLive} new event{pendingLive === 1 ? '' : 's'} · refresh
            </Button>
          ) : null}
          <span className="font-mono text-[11px] text-slate-500">
            {state === 'error' ? 'QUERY FAILED' : `${result.total} EVENTS`}
          </span>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
        <Select
          label="Camera"
          value={filters.camera_id}
          onChange={(value) => update({ camera_id: value })}
          options={[['', 'All cameras'], ...cameras.map((camera) => [camera.id, `${camera.id} · ${camera.name}`])]}
        />
        <Select
          label="Type"
          value={filters.type}
          onChange={(value) => update({ type: value })}
          options={[['', 'All types'], ...Object.entries(EVENT_TYPES).map(([key, spec]) => [key, spec.label])]}
        />
        <DateInput label="From" value={filters.from} onChange={(value) => update({ from: value })} />
        <DateInput label="To" value={filters.to} onChange={(value) => update({ to: value })} />

        <input
          type="search"
          value={filters.q}
          onChange={(changeEvent) => update({ q: changeEvent.target.value })}
          placeholder="Search reason, camera, track…"
          className="min-w-[10rem] flex-1 rounded border border-white/10 bg-black/30 px-2 py-1 text-xs text-slate-200 placeholder:text-slate-600 focus:border-white/25 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80"
        />

        <Button onClick={() => { setFilters(EMPTY_FILTERS); setPage(0); }}>Reset</Button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[52rem] text-left text-xs">
          <thead className="font-mono text-[10px] uppercase tracking-wide text-slate-500">
            <tr className="border-b border-white/10">
              <Th>Time</Th>
              <Th>Camera</Th>
              <Th>Type</Th>
              <Th>Track</Th>
              <Th>Conf</Th>
              <Th>Why it fired</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {state === 'error' ? (
              <Message>Could not reach the event API — {error}</Message>
            ) : showing === 0 && state === 'ready' ? (
              <Message>No events match these filters.</Message>
            ) : (
              result.events.map((event) => (
                <EventRow key={event.id} event={event} cameras={cameras} onSelect={onSelect} />
              ))
            )}
          </tbody>
        </table>
      </div>

      <footer className="flex items-center justify-between gap-3 border-t border-white/10 px-3 py-2">
        <span className="font-mono text-[11px] text-slate-500">
          {showing === 0 ? '0 of 0' : `${firstIndex + 1}–${firstIndex + showing} of ${result.total}`}
          {state === 'loading' ? ' · loading…' : ''}
        </span>
        <div className="flex gap-1.5">
          <Button onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={page === 0}>
            Previous
          </Button>
          <Button
            onClick={() => setPage((current) => current + 1)}
            disabled={firstIndex + showing >= result.total}
          >
            Next
          </Button>
        </div>
      </footer>
    </section>
  );
}

function EventRow({ event, cameras, onSelect }) {
  const type = eventType(event.type);
  const camera = cameras.find((entry) => entry.id === event.camera_id);
  const match = eventMatch(event);

  return (
    <tr
      role="button"
      tabIndex={0}
      onClick={() => onSelect(event)}
      onKeyDown={(keyEvent) => {
        if (keyEvent.key === 'Enter' || keyEvent.key === ' ') {
          keyEvent.preventDefault();
          onSelect(event);
        }
      }}
      className={`cursor-pointer transition-colors hover:bg-white/5 focus:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80 ${
        type.tint || ''
      }`}
    >
      {/* The accent runs down the time cell so every row is typed at the
          left edge, the same cue the live feed uses. */}
      <Td className={`whitespace-nowrap border-l-2 font-mono text-slate-400 ${type.accent}`}>
        {formatDateTime(event.timestamp)}
      </Td>
      <Td className="whitespace-nowrap text-slate-200">
        {camera?.name || event.camera_id}
        <span className="ml-1.5 font-mono text-[10px] text-slate-500">{event.camera_id}</span>
      </Td>
      <Td>
        <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${type.chip}`}>
          <EventIcon type={event.type} className="h-3 w-3" />
          {type.label}
        </span>
      </Td>
      <Td className="font-mono text-slate-400">
        {event.track_id === null || event.track_id === undefined ? '—' : `#${event.track_id}`}
      </Td>
      <Td className="font-mono text-slate-400">
        {typeof event.confidence === 'number' ? event.confidence.toFixed(2) : '—'}
      </Td>
      <Td className="text-slate-300">
        {match ? (
          <span className="mr-2 rounded bg-black/40 px-1.5 py-0.5 font-mono text-xs tracking-wider text-fuchsia-200 ring-1 ring-fuchsia-500/40">
            {match.value}
          </span>
        ) : null}
        {eventReason(event)}
      </Td>
    </tr>
  );
}

const Th = ({ children }) => <th className="px-3 py-2 font-normal">{children}</th>;
const Td = ({ children, className = '' }) => <td className={`px-3 py-2 ${className}`}>{children}</td>;
const Message = ({ children }) => (
  <tr>
    <td colSpan={6} className="px-3 py-8 text-center text-slate-500">{children}</td>
  </tr>
);

function Select({ label, value, onChange, options }) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] uppercase tracking-wide text-slate-500">{label}</span>
      <select
        value={value}
        onChange={(changeEvent) => onChange(changeEvent.target.value)}
        className="rounded border border-white/10 bg-black/30 px-2 py-1 text-xs text-slate-200 focus:border-white/25 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80"
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue} className="bg-panel">
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

function DateInput({ label, value, onChange }) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] uppercase tracking-wide text-slate-500">{label}</span>
      <input
        type="date"
        value={value}
        onChange={(changeEvent) => onChange(changeEvent.target.value)}
        className="rounded border border-white/10 bg-black/30 px-2 py-1 text-xs text-slate-200 focus:border-white/25 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80"
      />
    </label>
  );
}
