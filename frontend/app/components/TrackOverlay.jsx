'use client';

import { useEffect, useRef } from 'react';
import { subscribeToFrames } from '../lib/rafScheduler';
import { getFrameTransform } from '../lib/frameMapping';

/**
 * TrackOverlay — canvas layer drawing bounding boxes over a camera tile.
 *
 * Canvas rather than SVG: at 15-30 fps with a shifting set of tracks, SVG
 * would mean creating and destroying DOM nodes every frame across four tiles.
 * One canvas per tile repaints in a single operation and touches no DOM.
 *
 * The loop is deliberately lazy — it only repaints when a new frame has
 * arrived or the tile was resized, so a 15 fps stream costs 15 paints a
 * second, not 60.
 */
const STALE_AFTER_MS = 1000;
const LABEL_HEIGHT = 15;

const CLASS_COLORS = {
  person: '#34d399',
  vehicle: '#38bdf8',
  car: '#38bdf8',
  truck: '#38bdf8',
  bus: '#38bdf8',
  motorcycle: '#38bdf8',
  face: '#c084fc',
  plate: '#fbbf24',
};
const DEFAULT_COLOR = '#94a3b8';

export default function TrackOverlay({ frameRef, videoRef }) {
  const canvasRef = useRef(null);
  const sizeRef = useRef({ width: 0, height: 0, dpr: 1 });
  const drawnRef = useRef({ frame: null, width: 0, height: 0, cleared: true });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const ctx = canvas.getContext('2d');

    // Size is tracked by observer rather than read per frame — reading
    // clientWidth inside the rAF loop would force a layout on every tile.
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (!width || !height) return;

      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      sizeRef.current = { width, height, dpr };
      drawnRef.current.frame = null; // backing store was reset — repaint
    });
    observer.observe(canvas);

    const unsubscribe = subscribeToFrames((now) => {
      const { width, height, dpr } = sizeRef.current;
      if (!width || !height) return;

      const frame = frameRef.current;
      const drawn = drawnRef.current;
      const stale = !frame || now - frame.receivedAt > STALE_AFTER_MS;

      // Nothing arriving: clear once and stop, rather than holding ghost
      // boxes over a feed whose analytics worker has gone away.
      if (stale) {
        if (!drawn.cleared) {
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, width, height);
          drawnRef.current = { frame: null, width, height, cleared: true };
        }
        return;
      }

      if (frame === drawn.frame && width === drawn.width && height === drawn.height) return;

      drawTracks(ctx, frame.tracks, videoRef.current, { width, height, dpr });
      drawnRef.current = { frame, width, height, cleared: false };
    });

    return () => {
      observer.disconnect();
      unsubscribe();
    };
  }, [frameRef, videoRef]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 h-full w-full"
      aria-hidden="true"
    />
  );
}

function drawTracks(ctx, tracks, video, { width, height, dpr }) {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  // Shared with the fence editor so boxes and fences land in the same place.
  const { frameWidth, frameHeight, scale, offsetX, offsetY } =
    getFrameTransform(video, width, height);

  ctx.lineWidth = 1.5;
  ctx.font = '600 11px ui-monospace, SFMono-Regular, Menlo, monospace';
  ctx.textBaseline = 'middle';

  for (const track of tracks) {
    const bbox = track?.bbox;
    if (!Array.isArray(bbox) || bbox.length < 4) continue;

    const x = offsetX + bbox[0] * frameWidth * scale;
    const y = offsetY + bbox[1] * frameHeight * scale;
    const w = bbox[2] * frameWidth * scale;
    const h = bbox[3] * frameHeight * scale;

    // Cropped out of view by object-cover.
    if (x + w < 0 || y + h < 0 || x > width || y > height) continue;

    const color = CLASS_COLORS[track.cls] || DEFAULT_COLOR;
    ctx.strokeStyle = color;
    ctx.strokeRect(x, y, w, h);

    const label = track.cls ? `#${track.track_id} ${track.cls}` : `#${track.track_id}`;
    const labelWidth = ctx.measureText(label).width + 8;
    const labelY = y - LABEL_HEIGHT >= 0 ? y - LABEL_HEIGHT : y;
    // Keep the label inside the tile — a track at the frame edge would
    // otherwise have its id clipped, which is the one part that must stay
    // readable.
    const labelX = Math.min(Math.max(x, 0), Math.max(width - labelWidth, 0));

    ctx.fillStyle = color;
    ctx.fillRect(labelX, labelY, labelWidth, LABEL_HEIGHT);
    ctx.fillStyle = '#0a0d10';
    ctx.fillText(label, labelX + 4, labelY + LABEL_HEIGHT / 2);
  }
}
