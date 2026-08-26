'use client';

import { useState } from 'react';
import Button from './ui/Button';
import useWatchlist from '../hooks/useWatchlist';
import { LIST_TYPES, normalizePlate, validatePlate } from '../lib/watchlistApi';
import { formatDateTime } from '../lib/time';

/**
 * PlateList — ANPR enrollment for the demo zone.
 *
 * Deliberately small: type a plate, pick blacklist or whitelist, save. The
 * ANPR worker matches live reads against these rows, so enrolling a plate
 * here is what turns the next sighting into a watchlist_hit alert.
 */
export default function PlateList() {
  const { entries, state, error, add, remove } = useWatchlist();
  const [value, setValue] = useState('');
  const [listType, setListType] = useState('blacklist');
  const [note, setNote] = useState('');
  const [formError, setFormError] = useState(null);

  const normalized = normalizePlate(value);

  const submit = async (submitEvent) => {
    submitEvent.preventDefault();

    const problem = validatePlate(value);
    if (problem) {
      setFormError(problem);
      return;
    }
    setFormError(null);

    if (await add({ value, listType, note })) {
      setValue('');
      setNote('');
    }
  };

  return (
    // self-start so the panel sits at its natural height instead of stretching
    // to match the event log beside it.
    <section className="flex flex-col self-start overflow-hidden rounded-lg border border-white/10 bg-panel">
      <header className="flex items-center justify-between gap-3 border-b border-white/10 px-3 py-2.5">
        <h2 className="text-sm font-medium text-slate-100">Plate watchlist</h2>
        <span className="font-mono text-[11px] text-slate-500">
          {state === 'loading' ? 'LOADING' : `${entries.length} ENROLLED`}
        </span>
      </header>

      <form onSubmit={submit} className="space-y-2 border-b border-white/10 px-3 py-3">
        <label className="block">
          <span className="font-mono text-[10px] uppercase tracking-wide text-slate-500">Plate number</span>
          <input
            value={value}
            onChange={(changeEvent) => { setValue(changeEvent.target.value); setFormError(null); }}
            placeholder="HR26DK8337"
            autoComplete="off"
            spellCheck={false}
            className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-sm uppercase tracking-wider text-slate-100 placeholder:text-slate-600 focus:border-white/25 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80"
          />
        </label>

        {/* Show what will actually be stored — OCR never sees the spaces and
            dashes people type, so neither does the stored value. */}
        {normalized && normalized !== value.trim() ? (
          <p className="font-mono text-[10px] text-slate-500">stored as {normalized}</p>
        ) : null}

        <div className="flex gap-1.5">
          {Object.entries(LIST_TYPES).map(([key, spec]) => (
            <button
              key={key}
              type="button"
              onClick={() => setListType(key)}
              title={spec.hint}
              className={`flex-1 rounded px-2 py-1 text-[11px] font-medium ring-1 transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80 ${
                listType === key ? spec.chip : 'bg-white/5 text-slate-400 ring-transparent hover:bg-white/10'
              }`}
            >
              {spec.label}
            </button>
          ))}
        </div>

        <input
          value={note}
          onChange={(changeEvent) => setNote(changeEvent.target.value)}
          placeholder="Note (optional) — e.g. flagged by sector HQ"
          className="w-full rounded border border-white/10 bg-black/30 px-2 py-1 text-xs text-slate-200 placeholder:text-slate-600 focus:border-white/25 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80"
        />

        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] text-slate-500">{LIST_TYPES[listType].hint}</p>
          <Button type="submit" primary disabled={state === 'saving'}>
            {state === 'saving' ? 'Saving…' : 'Add plate'}
          </Button>
        </div>

        {formError || error ? (
          <p className="text-[11px] text-red-300">{formError || error}</p>
        ) : null}
      </form>

      <ul className="max-h-72 divide-y divide-white/5 overflow-y-auto">
        {entries.length === 0 ? (
          <li className="px-3 py-6 text-center text-xs text-slate-500">
            {state === 'loading' ? 'Loading…' : 'No plates enrolled yet'}
          </li>
        ) : (
          entries.map((entry) => (
            <li key={entry.id} className="flex items-start gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm tracking-wider text-slate-100">{entry.value}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ring-1 ${
                    LIST_TYPES[entry.list_type]?.chip || LIST_TYPES.blacklist.chip
                  }`}>
                    {LIST_TYPES[entry.list_type]?.label || entry.list_type}
                  </span>
                </div>
                {entry.note ? <p className="truncate text-[11px] text-slate-400">{entry.note}</p> : null}
                <p className="font-mono text-[10px] text-slate-600">{formatDateTime(entry.created_at)}</p>
              </div>

              <Button onClick={() => remove(entry.id)} disabled={state === 'saving'}>Remove</Button>
            </li>
          ))
        )}
      </ul>
    </section>
  );
}
