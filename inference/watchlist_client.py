"""
inference/watchlist_client.py

Polls the backend for the ANPR blacklist/whitelist on a background
thread and caches it locally, so the hot path (checking a freshly-read
plate against the list) never makes a network call mid-frame — it just
reads an in-memory dict.

ASSUMPTION: backend exposes GET /blacklist returning
  [{"plate": "KA05MN1234", "list_type": "blacklist"}, ...]
since backend/routes/blacklist.py already exists per your repo status.
Confirm the exact path/response shape against that route and adjust
get_watchlist() below if it differs — WatchlistCache and anpr_module.py
don't care how the dict was built, only that {plate: list_type} comes
back.
"""

import sys
import threading
import time
from typing import Dict

import requests


def get_watchlist(backend_url: str, timeout: float = 2.0) -> Dict[str, str]:
    url = f"{backend_url.rstrip('/')}/blacklist"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    entries = resp.json()  # expected: [{"plate": ..., "list_type": "blacklist"|"whitelist"}, ...]
    return {e["plate"].upper(): e["list_type"] for e in entries}


class WatchlistCache:
    """
    Background thread refreshes the watchlist every `refresh_interval`
    seconds. On a failed refresh, keeps serving the last good snapshot
    rather than blanking it out — a few minutes of a stale watchlist is
    far safer than silently checking every plate against an empty one.
    """

    def __init__(self, backend_url: str, refresh_interval: float = 30.0):
        self.backend_url = backend_url
        self.refresh_interval = refresh_interval
        self._lock = threading.Lock()
        self._watchlist: Dict[str, str] = {}

        # Synchronous fetch at construction so the very first plate
        # checked isn't checked against an empty cache.
        try:
            self._watchlist = get_watchlist(backend_url)
            print(f"[watchlist] loaded {len(self._watchlist)} entries at startup", file=sys.stderr)
        except Exception as e:
            print(f"[watchlist] initial load failed: {e} (starting with EMPTY watchlist)", file=sys.stderr)

        self._thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._thread.start()

    def _refresh_loop(self) -> None:
        while True:
            time.sleep(self.refresh_interval)
            try:
                fresh = get_watchlist(self.backend_url)
                with self._lock:
                    self._watchlist = fresh
                print(f"[watchlist] refreshed, {len(fresh)} entries", file=sys.stderr)
            except Exception as e:
                print(f"[watchlist] refresh failed: {e} (keeping previous snapshot)", file=sys.stderr)

    def snapshot(self) -> Dict[str, str]:
        """Current cached watchlist — cheap, just a dict copy under a lock."""
        with self._lock:
            return dict(self._watchlist)
