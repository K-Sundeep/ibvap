/**
 * A WebSocket that reconnects, shared by the track and alert streams.
 *
 * Returns a dispose function. Callers get parsed messages only — a frame that
 * doesn't parse is dropped rather than tearing the socket down, since one bad
 * message from a worker shouldn't cost an operator their feed.
 */
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 10000;

export function openReconnectingSocket(url, { onMessage, onStatus }) {
  let socket = null;
  let reconnectTimer = null;
  let attempt = 0;
  let disposed = false;

  const connect = () => {
    onStatus('connecting');
    socket = new WebSocket(url);

    socket.onopen = () => {
      attempt = 0;
      onStatus('open');
    };

    socket.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      onMessage(message);
    };

    socket.onclose = () => {
      if (disposed) return;
      onStatus('closed');
      const delay = Math.min(RECONNECT_MIN_MS * 2 ** attempt, RECONNECT_MAX_MS);
      attempt += 1;
      // Jitter so several sockets don't retry in lockstep against a backend
      // that is still starting up.
      reconnectTimer = setTimeout(connect, delay + Math.random() * 250);
    };
  };

  connect();

  return () => {
    disposed = true;
    clearTimeout(reconnectTimer);
    if (socket) {
      socket.onclose = null;
      socket.close();
    }
  };
}
