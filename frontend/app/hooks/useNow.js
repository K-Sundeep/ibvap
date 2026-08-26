'use client';

import { useEffect, useState } from 'react';

/**
 * A clock that ticks, so relative timestamps ("12s ago") stay honest without
 * every row owning its own interval.
 */
export default function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);

  return now;
}
