'use client';

/**
 * One glyph per alert type, so an operator can tell a watchlist hit from a
 * fence crossing at a glance without reading the label — colour alone isn't
 * enough on a projector, or for anyone who reads colour differently.
 */
const PATHS = {
  // Figure stepping over a line.
  intrusion: 'M3 13h18M8 3v6M8 6l4-2M8 9l3 2M15 5l2 4',
  // Magnifier over a plate.
  watchlist_hit: 'M3 6h14v8H3zM6 9h8M21 20l-3.5-3.5M15 15.5a2.5 2.5 0 105 0 2.5 2.5 0 00-5 0',
  // Clock.
  loitering: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2',
  // Moon with motion arcs.
  night_movement: 'M17 14A8 8 0 016.5 4.5a7.5 7.5 0 1010.5 9.5zM19 6h3M19 9h2',
};

export default function EventIcon({ type, className = 'h-3.5 w-3.5' }) {
  const path = PATHS[type];
  if (!path) return null;

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}
