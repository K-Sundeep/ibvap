"""
inference/ingest_client.py

Thin HTTP client for pulling the latest frame per camera from the
ingest service (pull model — inference polls ingest, per architecture
doc: direct HTTP calls, no queue/broker).

ASSUMPTION (confirm against ingest/main.py's actual route before relying
on this): ingest exposes GET /cameras/{camera_id}/latest_frame returning
raw JPEG bytes with Content-Type: image/jpeg. If ingest actually returns
something else (base64-encoded JSON, PNG, multipart, a different path),
only _this file_ needs to change — detector.py/tracker.py/main.py don't
care how the frame arrived, only that they get a decoded BGR numpy array.
"""

import cv2
import numpy as np
import requests


class IngestClient:
    def __init__(self, base_url: str, timeout: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_latest_frame(self, camera_id: str) -> np.ndarray:
        """
        Fetch and decode the latest available frame for a camera.
        Raises requests.HTTPError / ValueError on failure — caller
        decides whether to skip this camera for one cycle or bail out.
        """
        url = f"{self.base_url}/cameras/{camera_id}/latest_frame"
        resp = requests.get(url, timeout=self.timeout)
        resp.raise_for_status()

        img_array = np.frombuffer(resp.content, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"Could not decode frame from {url} (unexpected response format)")
        return frame
