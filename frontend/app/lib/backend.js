/**
 * Where the backend lives.
 *
 * FastAPI serves the REST routes and the WebSocket endpoints from the same
 * origin, so setting only one of these is almost always a stale config rather
 * than a deliberate split — derive the other instead of silently falling back
 * to the default host and firing half the dashboard's requests at a port with
 * nothing on it.
 */
const rawApi = process.env.NEXT_PUBLIC_API_BASE;
const rawWs = process.env.NEXT_PUBLIC_WS_BASE;

// ws:// → http://, wss:// → https://, and back.
export const API_BASE = rawApi || (rawWs ? rawWs.replace(/^ws/, 'http') : 'http://localhost:8000');
export const WS_BASE = rawWs || (rawApi ? rawApi.replace(/^http/, 'ws') : 'ws://localhost:8000');

/** Host and port only — for telling an operator which backend just refused. */
export const API_HOST = (() => {
  try {
    return new URL(API_BASE).host;
  } catch {
    return API_BASE;
  }
})();
