'use client';

import { useCallback, useEffect, useState } from 'react';
import { deleteFence, fetchFence, putFence } from '../lib/fenceApi';
import { API_HOST } from '../lib/backend';

/**
 * Loads a camera's saved fence and persists edits to it.
 *
 * The fence is loaded from the backend on mount rather than kept in browser
 * storage — an operator's fence has to survive a reload on someone else's
 * machine, and the rules engine reads the same record.
 */
export default function useFence(cameraId) {
  const [fence, setFence] = useState(null);
  const [state, setState] = useState('loading'); // loading | ready | saving | error
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!cameraId) return undefined;

    const controller = new AbortController();
    // 'loading' is the initial state, so there is nothing to set here — the
    // fetch below is what moves it on.
    fetchFence(cameraId, { signal: controller.signal })
      .then((loaded) => {
        setFence(loaded);
        setState('ready');
        setError(null);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        // Usually the backend simply isn't running yet, or the dashboard is
        // pointed at the wrong host — name it, so the fix is obvious without
        // opening devtools.
        setState('error');
        setError(`fence API unreachable (${API_HOST})`);
      });

    return () => controller.abort();
  }, [cameraId]);

  const save = useCallback(
    async (draft) => {
      setState('saving');
      try {
        const saved = await putFence(cameraId, draft);
        setFence(saved);
        setState('ready');
        setError(null);
        return true;
      } catch (cause) {
        setState('error');
        setError(cause.message || 'save failed');
        return false;
      }
    },
    [cameraId],
  );

  const clear = useCallback(async () => {
    setState('saving');
    try {
      await deleteFence(cameraId);
      setFence(null);
      setState('ready');
      setError(null);
      return true;
    } catch (cause) {
      setState('error');
      setError(cause.message || 'clear failed');
      return false;
    }
  }, [cameraId]);

  return { fence, state, error, save, clear };
}
