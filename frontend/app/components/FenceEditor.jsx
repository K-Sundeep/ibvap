'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import useFence from '../hooks/useFence';
import Button from './ui/Button';
import { FENCE_TYPES, canAddPoint, isFenceComplete } from '../lib/fenceApi';
import { frameToPixel, getFrameTransform, pixelToFrame } from '../lib/frameMapping';

/**
 * Virtual fence editor for a camera tile.
 *
 * Split into three exports because the two halves live in different parts of
 * the tile: the drawing surface sits on top of the video, the controls sit in
 * the tile footer where they can't cover the feed. `useFenceEditor` holds the
 * state both halves share.
 *
 *   const editor = useFenceEditor(cameraId);
 *   <FenceLayer editor={editor} videoRef={videoRef} />   // inside the video box
 *   <FenceToolbar editor={editor} />                     // in the tile footer
 */

const FENCE_COLOR = '#fbbf24';
const CLOSE_HANDLE_PX = 12;
// Swallows the second click of a double-click, and stops a shaky hand from
// stacking two points on top of each other.
const DUPLICATE_EPSILON = 0.004;

export function useFenceEditor(cameraId) {
  const { fence, state, error, save, clear } = useFence(cameraId);
  const [mode, setMode] = useState(null); // null when not drawing
  const [draft, setDraft] = useState([]);

  const startDrawing = useCallback((type) => {
    setMode(type);
    setDraft([]);
  }, []);

  const cancelDrawing = useCallback(() => {
    setMode(null);
    setDraft([]);
  }, []);

  const addPoint = useCallback(
    (point) => {
      setDraft((current) => {
        if (!canAddPoint(mode, current)) return current;
        const last = current[current.length - 1];
        if (last && Math.abs(last[0] - point[0]) < DUPLICATE_EPSILON
          && Math.abs(last[1] - point[1]) < DUPLICATE_EPSILON) {
          return current;
        }
        return [...current, point];
      });
    },
    [mode],
  );

  const undoPoint = useCallback(() => setDraft((current) => current.slice(0, -1)), []);

  const saveDraft = useCallback(async () => {
    if (!isFenceComplete(mode, draft)) return;
    const saved = await save({ type: mode, points: draft });
    if (saved) {
      setMode(null);
      setDraft([]);
    }
  }, [mode, draft, save]);

  const clearFence = useCallback(async () => {
    await clear();
  }, [clear]);

  // Keyboard shortcuts, live only while drawing.
  useEffect(() => {
    if (!mode) return undefined;

    const onKeyDown = (event) => {
      if (event.key === 'Escape') cancelDrawing();
      if (event.key === 'Enter') saveDraft();
      if (event.key === 'Backspace') {
        event.preventDefault();
        undoPoint();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [mode, cancelDrawing, saveDraft, undoPoint]);

  return {
    fence,
    state,
    error,
    mode,
    draft,
    drawing: mode !== null,
    complete: isFenceComplete(mode, draft),
    startDrawing,
    cancelDrawing,
    addPoint,
    undoPoint,
    saveDraft,
    clearFence,
  };
}

/**
 * The drawing surface: renders the saved fence, the in-progress draft, and a
 * rubber-band segment following the cursor. Transparent to pointer events
 * unless draw mode is on, so it never blocks the tile.
 */
export function FenceLayer({ editor, videoRef }) {
  const { fence, mode, draft, drawing, addPoint } = editor;
  const hostRef = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [frame, setFrame] = useState({ videoWidth: 0, videoHeight: 0 });
  // Cursor lives here rather than in the shared hook: it changes on every
  // mousemove, and only this layer needs to redraw for it.
  const [cursor, setCursor] = useState(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;

    const readSize = () => setFrame({ videoWidth: video.videoWidth, videoHeight: video.videoHeight });
    readSize(); // metadata may already be in
    video.addEventListener('loadedmetadata', readSize);
    return () => video.removeEventListener('loadedmetadata', readSize);
  }, [videoRef]);

  const transform = getFrameTransform(frame, size.width, size.height);
  const toPixel = (point) => frameToPixel(point, transform);
  const eventPoint = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      pixel: [event.clientX - rect.left, event.clientY - rect.top],
      frame: pixelToFrame(event.clientX - rect.left, event.clientY - rect.top, transform),
    };
  };

  const handleClick = (event) => {
    const { pixel, frame: point } = eventPoint(event);

    // Clicking the first vertex closes the polygon — the gesture people
    // expect from every map/zone editor.
    if (mode === 'polygon' && draft.length >= 3) {
      const [firstX, firstY] = toPixel(draft[0]);
      if (Math.hypot(pixel[0] - firstX, pixel[1] - firstY) <= CLOSE_HANDLE_PX) {
        editor.saveDraft();
        return;
      }
    }
    addPoint(point);
  };

  const draftPixels = draft.map(toPixel);
  const rubberBand = drawing && cursor && draftPixels.length > 0
    && canAddPoint(mode, draft) ? [draftPixels[draftPixels.length - 1], cursor] : null;

  return (
    <div ref={hostRef} className="absolute inset-0">
      <svg
        className={`h-full w-full ${drawing ? 'cursor-crosshair' : 'pointer-events-none'}`}
        onClick={drawing ? handleClick : undefined}
        onDoubleClick={drawing ? () => editor.saveDraft() : undefined}
        onMouseMove={drawing ? (event) => setCursor(eventPoint(event).pixel) : undefined}
        onMouseLeave={drawing ? () => setCursor(null) : undefined}
      >
        {fence ? <SavedFence fence={fence} toPixel={toPixel} dimmed={drawing} /> : null}
        {drawing ? (
          <DraftFence mode={mode} points={draftPixels} rubberBand={rubberBand} />
        ) : null}
      </svg>

      {drawing ? <DrawingHint mode={mode} count={draft.length} /> : null}
    </div>
  );
}

function SavedFence({ fence, toPixel, dimmed }) {
  const points = (fence.points || []).map(toPixel);
  if (points.length < 2) return null;
  const attr = points.map(([x, y]) => `${x},${y}`).join(' ');

  return (
    <g opacity={dimmed ? 0.35 : 1}>
      {fence.type === 'tripwire' ? (
        <line
          x1={points[0][0]} y1={points[0][1]}
          x2={points[1][0]} y2={points[1][1]}
          stroke={FENCE_COLOR} strokeWidth="2"
        />
      ) : (
        <polygon points={attr} fill={FENCE_COLOR} fillOpacity="0.12" stroke={FENCE_COLOR} strokeWidth="2" />
      )}
      {points.map(([x, y], index) => (
        <circle key={index} cx={x} cy={y} r="3" fill={FENCE_COLOR} />
      ))}
    </g>
  );
}

function DraftFence({ mode, points, rubberBand }) {
  const attr = points.map(([x, y]) => `${x},${y}`).join(' ');

  return (
    <g>
      {points.length >= 2 ? (
        <polyline
          points={attr}
          fill="none"
          stroke={FENCE_COLOR}
          strokeWidth="2"
          strokeDasharray="5 4"
        />
      ) : null}

      {/* Closing edge preview, so a polygon reads as an area while drawing. */}
      {mode === 'polygon' && points.length >= 3 ? (
        <polygon points={attr} fill={FENCE_COLOR} fillOpacity="0.08" stroke="none" />
      ) : null}

      {rubberBand ? (
        <line
          x1={rubberBand[0][0]} y1={rubberBand[0][1]}
          x2={rubberBand[1][0]} y2={rubberBand[1][1]}
          stroke={FENCE_COLOR} strokeWidth="1.5" strokeDasharray="4 4" opacity="0.7"
        />
      ) : null}

      {points.map(([x, y], index) => (
        <circle
          key={index}
          cx={x} cy={y}
          r={index === 0 ? 5 : 3.5}
          fill={index === 0 ? 'transparent' : '#ffffff'}
          stroke={index === 0 ? '#ffffff' : FENCE_COLOR}
          strokeWidth="2"
        />
      ))}
    </g>
  );
}

function DrawingHint({ mode, count }) {
  const instruction = mode === 'tripwire'
    ? 'Click two points to set the tripwire'
    : 'Click to add points · click the first point or double-click to finish';

  return (
    // Anchored near the top, clear of the area being drawn on.
    <div className="pointer-events-none absolute inset-x-0 top-14 flex justify-center px-4">
      <p className="rounded bg-black/80 px-3 py-1.5 text-center text-[11px] text-slate-100 shadow-lg">
        {instruction}
        <span className="ml-2 font-mono text-slate-400">
          {count} pt{count === 1 ? '' : 's'} · Esc cancels
        </span>
      </p>
    </div>
  );
}

/**
 * Tile-footer controls. Kept out of the video box so nothing covers the feed
 * during a demo, and labelled with what each action does rather than icons.
 */
export function FenceToolbar({ editor }) {
  const { fence, state, error, mode, draft, drawing, complete } = editor;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 px-3 py-2">
      <FenceStatus fence={fence} state={state} error={error} mode={mode} count={draft.length} />

      <div className="flex items-center gap-1.5">
        {drawing ? (
          <>
            <Button onClick={editor.undoPoint} disabled={draft.length === 0}>Undo</Button>
            <Button onClick={editor.cancelDrawing}>Cancel</Button>
            <Button onClick={editor.saveDraft} disabled={!complete || state === 'saving'} primary>
              {state === 'saving' ? 'Saving…' : 'Save fence'}
            </Button>
          </>
        ) : (
          <>
            {Object.entries(FENCE_TYPES).map(([type, spec]) => (
              <Button key={type} onClick={() => editor.startDrawing(type)}>
                Draw {spec.label.toLowerCase()}
              </Button>
            ))}
            {fence ? (
              <Button onClick={editor.clearFence} disabled={state === 'saving'}>Clear</Button>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function FenceStatus({ fence, state, error, mode, count }) {
  if (state === 'loading') {
    return <span className="font-mono text-[11px] text-slate-500">FENCE · LOADING</span>;
  }
  if (mode) {
    return (
      <span className="font-mono text-[11px] text-amber-300">
        DRAWING {FENCE_TYPES[mode].label.toUpperCase()} · {count} PT{count === 1 ? '' : 'S'}
      </span>
    );
  }
  if (error) {
    return <span className="font-mono text-[11px] text-red-300">{error.toUpperCase()}</span>;
  }
  if (!fence) {
    return <span className="font-mono text-[11px] text-slate-500">NO FENCE SET</span>;
  }

  return (
    <span className="flex items-center gap-2 font-mono text-[11px] text-amber-300">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
      {FENCE_TYPES[fence.type]?.label.toUpperCase() || fence.type.toUpperCase()}
      {' · '}
      {fence.points.length} PT{fence.points.length === 1 ? '' : 'S'}
    </span>
  );
}
