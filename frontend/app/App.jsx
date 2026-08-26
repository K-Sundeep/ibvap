'use client';

import { useState } from 'react';
import AlertsFeed from './components/AlertsFeed';
import CameraStatusBar from './components/CameraStatusBar';
import CameraTile from './components/CameraTile';
import EventDetail from './components/EventDetail';
import EventLog from './components/EventLog';
import PlateList from './components/PlateList';
import useAlertStream from './hooks/useAlertStream';
import { cameras } from './data/cameras';

/**
 * App — the operator dashboard: camera wall, live alerts alongside it, and
 * the searchable event log underneath. The alert stream lives here so the
 * feed and the log can both react to it — the feed shows alerts as they
 * arrive, the log offers a refresh rather than moving under the operator.
 */
export default function App() {
  const { alerts, status, received } = useAlertStream();
  const [selectedEvent, setSelectedEvent] = useState(null);

  return (
    <div className="min-h-screen bg-app text-slate-100">
      <header className="border-b border-white/10 px-6 py-4">
        <div className="mx-auto flex max-w-[100rem] items-center justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">IBVAP</h1>
            <p className="text-xs text-slate-400">
              Intelligent Border Video Analytics Platform
            </p>
          </div>
          <p className="font-mono text-xs text-slate-400">
            {cameras.length} cameras · sample feed
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-[100rem] space-y-4 px-6 py-6">
        {/* min-w-0 on the wide column: a grid item defaults to min-width:auto,
            so the event log's table was widening the whole page below xl
            instead of scrolling inside its own container. */}
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-4">
            <CameraStatusBar cameras={cameras} alerts={alerts} />

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {cameras.map((camera) => (
                <CameraTile key={camera.id} {...camera} />
              ))}
            </div>
          </div>

          <AlertsFeed
            alerts={alerts}
            status={status}
            received={received}
            cameras={cameras}
            onSelect={setSelectedEvent}
          />
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0">
            <EventLog cameras={cameras} liveCount={received} onSelect={setSelectedEvent} />
          </div>
          <PlateList />
        </div>
      </main>

      <EventDetail
        event={selectedEvent}
        cameras={cameras}
        onClose={() => setSelectedEvent(null)}
      />
    </div>
  );
}
