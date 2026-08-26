/** Time formatting for alert rows and the event log. */

export function formatRelative(epochSeconds, now = Date.now()) {
  const seconds = Math.max(0, Math.round(now / 1000 - epochSeconds));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function formatClock(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function formatDateTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/** Start / end of a local calendar day, as epoch seconds. */
export const startOfDay = (value) => new Date(`${value}T00:00:00`).getTime() / 1000;
export const endOfDay = (value) => new Date(`${value}T23:59:59.999`).getTime() / 1000;
