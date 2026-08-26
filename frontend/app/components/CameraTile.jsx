'use client';

import { useEffect, useRef, useState } from 'react';
import TrackOverlay from './TrackOverlay';
import { FenceLayer, FenceToolbar, useFenceEditor } from './FenceEditor';
import useTrackStream from '../hooks/useTrackStream';

/**
 * CameraTile — one camera feed with its live analytics overlay.
 *
 * `src` is whatever URL the backend hands us: an HLS playlist (.m3u8)
 * transcoded from the camera's RTSP stream, or a direct video file. Track
 * boxes arrive separately over the per-camera WebSocket (see useTrackStream).
 */
export default function CameraTile({ id, name, location, src, poster }) {
  const videoRef = useRef(null);
  const [status, setStatus] = useState('connecting');
  const { frameRef, status: trackStatus, stats } = useTrackStream(id);
  const fenceEditor = useFenceEditor(id);

  const isHls = typeof src === 'string' && src.includes('.m3u8');

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    // Safari/iOS plays HLS natively; other browsers will need hls.js once the
    // ingest service starts publishing real playlists.
    if (isHls && !video.canPlayType('application/vnd.apple.mpegurl')) {
      setStatus('unsupported');
      return;
    }

    // The element can already have loaded (or failed) before this effect runs,
    // and those events are gone by now — so read the current state first.
    if (video.error) {
      setStatus('offline');
    } else if (video.readyState >= 3 && !video.paused) {
      setStatus('live');
    }

    const onPlaying = () => setStatus('live');
    const onWaiting = () => setStatus('connecting');
    const onError = () => setStatus('offline');

    video.addEventListener('playing', onPlaying);
    video.addEventListener('waiting', onWaiting);
    video.addEventListener('error', onError);

    return () => {
      video.removeEventListener('playing', onPlaying);
      video.removeEventListener('waiting', onWaiting);
      video.removeEventListener('error', onError);
    };
  }, [src, isHls]);

  return (
    <figure className="group relative overflow-hidden rounded-lg border border-white/10 bg-panel">
      <div className="relative aspect-video w-full bg-black">
        {status === 'unsupported' || status === 'offline' ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 px-4 text-center">
            <p className="text-sm text-slate-300">
              {status === 'unsupported' ? 'Stream format not supported' : 'No signal'}
            </p>
            {/* The stream URL belongs in the console, not on an operator's
                wall — name the camera that dropped instead. */}
            <p className="font-mono text-xs text-slate-500">{id}</p>
          </div>
        ) : null}

        <video
          ref={videoRef}
          src={src}
          poster={poster}
          className="h-full w-full object-cover"
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
        />

        <TrackOverlay frameRef={frameRef} videoRef={videoRef} />

        {/* Top overlay: camera identity */}
        <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between bg-gradient-to-b from-black/70 to-transparent p-3">
          <figcaption>
            <span className="block text-sm font-medium text-slate-100">{name}</span>
            <span className="block text-xs text-slate-400">{location}</span>
          </figcaption>
          <span className="text-right font-mono text-xs text-slate-400">
            <span className="block">{id}</span>
            <span className="block text-[10px] text-slate-500">{isHls ? 'HLS' : 'FILE'}</span>
          </span>
        </div>

        {/* Bottom overlay: stream status + analytics readout */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-3 bg-gradient-to-t from-black/70 to-transparent p-3">
          <StatusBadge status={status} />
          <TrackReadout status={trackStatus} stats={stats} />
        </div>

        <FenceLayer editor={fenceEditor} videoRef={videoRef} />
      </div>

      <FenceToolbar editor={fenceEditor} />
    </figure>
  );
}

function StatusBadge({ status }) {
  const styles = {
    live: { dot: 'bg-emerald-400', text: 'text-emerald-300', label: 'LIVE' },
    connecting: { dot: 'bg-amber-400', text: 'text-amber-300', label: 'CONNECTING' },
    offline: { dot: 'bg-red-500', text: 'text-red-300', label: 'OFFLINE' },
    unsupported: { dot: 'bg-slate-500', text: 'text-slate-400', label: 'UNSUPPORTED' },
  }[status];

  return (
    <span className={`flex items-center gap-2 font-mono text-[11px] tracking-wide ${styles.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${styles.dot}`} />
      {styles.label}
    </span>
  );
}

/**
 * Per-tile analytics readout: how fast the backend is processing this camera
 * and how far behind real time its boxes are. Latency is colour-coded against
 * the platform's sub-2s alert target so a lagging worker is visible at a
 * glance rather than buried in a log.
 */
function TrackReadout({ status, stats }) {
  if (status !== 'open') {
    return (
      <span className="font-mono text-[11px] text-slate-500">
        {status === 'connecting' ? 'TRACKS · CONNECTING' : 'TRACKS · OFFLINE'}
      </span>
    );
  }

  const { fps, latencyMs, trackCount } = stats;
  const latencyColor =
    latencyMs === null ? 'text-slate-400'
      : latencyMs > 1500 ? 'text-red-300'
        : latencyMs > 500 ? 'text-amber-300'
          : 'text-slate-300';

  return (
    <span className="flex items-center gap-2 font-mono text-[11px] text-slate-400">
      <span>{trackCount} trk</span>
      <span aria-hidden="true">·</span>
      <span className="text-slate-300">{fps === null ? '—' : fps.toFixed(1)} fps</span>
      <span aria-hidden="true">·</span>
      <span className={latencyColor}>{latencyMs === null ? '—' : Math.round(latencyMs)} ms</span>
    </span>
  );
}
