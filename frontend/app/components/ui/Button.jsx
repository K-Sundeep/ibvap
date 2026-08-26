'use client';

/** Shared button styling for the dashboard's small inline controls. */
export default function Button({ onClick, disabled, primary, type = 'button', children }) {
  const tone = primary
    ? 'bg-amber-400 text-slate-900 hover:bg-amber-300'
    : 'bg-white/5 text-slate-200 hover:bg-white/10';

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded px-2.5 py-1 text-[11px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-400/80 ${tone}`}
    >
      {children}
    </button>
  );
}
