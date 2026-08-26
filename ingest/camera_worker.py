"""
camera_worker.py — IBVAP ingest layer

One CameraWorker per configured camera. Each worker runs in its own thread:
  - opens the RTSP stream via OpenCV (FFMPEG backend)
  - normalizes resolution + FPS
  - keeps the latest JPEG-encoded frame in a thread-safe holder
  - auto-reconnects with backoff if the stream drops

This module has no knowledge of HTTP — main.py wires workers to the Flask app.
"""

import cv2
import time
import threading
import logging

logger = logging.getLogger("ibvap.ingest.worker")


class CameraWorker:
    def __init__(self, camera_id: str, rtsp_url: str,
                 target_fps: int = 10, target_width: int = 960, target_height: int = 540,
                 jpeg_quality: int = 80, reconnect_backoff_s: float = 2.0,
                 max_backoff_s: float = 15.0):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.target_fps = target_fps
        self.target_width = target_width
        self.target_height = target_height
        self.jpeg_quality = jpeg_quality
        self.reconnect_backoff_s = reconnect_backoff_s
        self.max_backoff_s = max_backoff_s

        self._min_frame_interval = 1.0 / max(target_fps, 1)
        self._lock = threading.Lock()
        self._latest_jpeg = None          # bytes, MJPEG-ready
        self._latest_frame_ts = 0.0
        self._connected = False
        self._stop_event = threading.Event()
        self._thread = None

        # simple runtime stats, useful for a /streams status endpoint
        self.frames_read = 0
        self.reconnects = 0
        self.last_error = None

    # ---- public API ----------------------------------------------------

    def start(self):
        self._thread = threading.Thread(target=self._run, name=f"cam-{self.camera_id}", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def get_latest_jpeg(self):
        with self._lock:
            return self._latest_jpeg

    def status(self):
        with self._lock:
            age = time.time() - self._latest_frame_ts if self._latest_frame_ts else None
        return {
            "camera_id": self.camera_id,
            "connected": self._connected,
            "frames_read": self.frames_read,
            "reconnects": self.reconnects,
            "last_frame_age_s": round(age, 2) if age is not None else None,
            "last_error": self.last_error,
        }

    # ---- internals -------------------------------------------------------

    def _open_capture(self):
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        # keep the OS/ffmpeg buffer small so we display near-live frames, not a backlog
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def _run(self):
        backoff = self.reconnect_backoff_s
        while not self._stop_event.is_set():
            cap = self._open_capture()
            if not cap.isOpened():
                self._connected = False
                self.last_error = "failed to open stream"
                logger.warning("[%s] could not open %s, retrying in %.1fs",
                                self.camera_id, self.rtsp_url, backoff)
                cap.release()
                if self._stop_event.wait(backoff):
                    break
                backoff = min(backoff * 1.5, self.max_backoff_s)
                continue

            logger.info("[%s] connected to %s", self.camera_id, self.rtsp_url)
            self._connected = True
            self.reconnects += 1 if self.frames_read > 0 else 0
            backoff = self.reconnect_backoff_s  # reset on successful connect
            last_emit = 0.0

            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    self.last_error = "read failed / stream ended"
                    logger.warning("[%s] frame read failed, reconnecting", self.camera_id)
                    break

                self.frames_read += 1

                # throttle to target_fps — drop frames rather than queueing them,
                # so the dashboard always sees the freshest frame, not a backlog
                now = time.time()
                if now - last_emit < self._min_frame_interval:
                    continue
                last_emit = now

                frame = cv2.resize(frame, (self.target_width, self.target_height),
                                    interpolation=cv2.INTER_AREA)

                ok, buf = cv2.imencode(".jpg", frame,
                                        [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
                if not ok:
                    continue

                with self._lock:
                    self._latest_jpeg = buf.tobytes()
                    self._latest_frame_ts = now

            cap.release()
            self._connected = False
            if self._stop_event.is_set():
                break
            if self._stop_event.wait(backoff):
                break
            backoff = min(backoff * 1.5, self.max_backoff_s)

        logger.info("[%s] worker stopped", self.camera_id)
