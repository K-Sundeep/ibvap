'use client';

import { useEffect, useRef, useState } from 'react';
import { openReconnectingSocket } from '../lib/reconnectingSocket';
import { ALERT_STREAM_URL } from '../lib/eventsApi';

/**
 * Live alert feed: one dashboard-wide socket carrying events from every
 * camera, newest first.
 *
 * Unlike track frames — which arrive 15 times a second per camera and are
 * therefore kept out of React — alerts are rare and every one must be shown,
 * so they go straight into state and render on arrival. No batching, no
 * polling interval: the delay between the rule firing and the row appearing
 * is a socket hop plus a render.
 */
const MAX_ALERTS = 50;

export default function useAlertStream() {
  const [alerts, setAlerts] = useState([]);
  const [status, setStatus] = useState('connecting');
  const [received, setReceived] = useState(0);
  const seenIds = useRef(new Set());

  useEffect(() => {
    const dispose = openReconnectingSocket(ALERT_STREAM_URL, {
      onStatus: setStatus,
      onMessage: (event) => {
        if (!event || event.id === undefined || !event.camera_id) return;
        // A reconnect can replay recent alerts; don't stack duplicates.
        if (seenIds.current.has(event.id)) return;
        seenIds.current.add(event.id);

        setReceived((count) => count + 1);
        setAlerts((current) => [{ ...event, receivedAt: Date.now() }, ...current].slice(0, MAX_ALERTS));
      },
    });

    return dispose;
  }, []);

  return { alerts, status, received };
}
