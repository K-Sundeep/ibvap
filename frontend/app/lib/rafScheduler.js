/**
 * One requestAnimationFrame loop for the whole dashboard.
 *
 * Each camera tile drawing on its own rAF would mean N independent callbacks
 * competing for the same frame budget. A single loop fanning out to
 * subscribers keeps overlay work batched into one paint, and stops entirely
 * when the last tile unsubscribes.
 */
const subscribers = new Set();
let frameId = 0;

function tick(now) {
  frameId = requestAnimationFrame(tick);
  for (const fn of subscribers) fn(now);
}

export function subscribeToFrames(fn) {
  subscribers.add(fn);
  if (subscribers.size === 1) frameId = requestAnimationFrame(tick);

  return () => {
    subscribers.delete(fn);
    if (subscribers.size === 0) cancelAnimationFrame(frameId);
  };
}
