'use client';

import { useCallback, useEffect, useState } from 'react';
import { addWatchlistEntry, fetchWatchlist, removeWatchlistEntry } from '../lib/watchlistApi';
import { API_HOST } from '../lib/backend';

/**
 * The enrolled plate list. Lives on the backend, not in browser storage — the
 * ANPR worker matches against the same rows, so a plate enrolled on one
 * operator's screen has to be live for everyone.
 */
export default function useWatchlist() {
  const [entries, setEntries] = useState([]);
  const [state, setState] = useState('loading'); // loading | ready | saving | error
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    fetchWatchlist({ signal: controller.signal })
      .then((data) => {
        setEntries(data.entries || []);
        setState('ready');
        setError(null);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setState('error');
        setError(`watchlist API unreachable (${API_HOST})`);
      });

    return () => controller.abort();
  }, []);

  const add = useCallback(async (draft) => {
    setState('saving');
    try {
      const entry = await addWatchlistEntry(draft);
      setEntries((current) => [entry, ...current]);
      setState('ready');
      setError(null);
      return true;
    } catch (cause) {
      setState('error');
      setError(cause.message || 'save failed');
      return false;
    }
  }, []);

  const remove = useCallback(async (id) => {
    setState('saving');
    try {
      await removeWatchlistEntry(id);
      setEntries((current) => current.filter((entry) => entry.id !== id));
      setState('ready');
      setError(null);
    } catch (cause) {
      setState('error');
      setError(cause.message || 'delete failed');
    }
  }, []);

  return { entries, state, error, add, remove };
}
