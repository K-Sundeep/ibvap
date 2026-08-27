"""
inference/snapshot.py

Captures a frame to disk when a crossing event fires, without blocking
the detection/tracking loop on disk I/O.

Design note: this lives here, not inside virtual_fence.py. VirtualFence
only ever receives a centroid — it has no access to frame pixels, and
keeping it that way was deliberate last sprint (pure geometry, easy to
unit-test with fabricated points, no OpenCV dependency). The service
loop already holds the raw frame when a CrossingEvent comes back from
fence.update(), so capture happens there, calling into this module.
Net effect for the pipeline is the same: a snapshot is taken at the
moment a crossing fires.

Naming convention (fixed, so backend storage never has to guess):
    {camera_id}_{epoch_millis}.jpg
e.g. cam1_1756289421123.jpg — sorts chronologically as a plain string,
one file per event, collision-proof at normal frame rates (millisecond
resolution vs. crossings that are at minimum one frame apart).
"""

import os
import queue
import sys
import threading

import cv2
import numpy as np


class SnapshotWriter:
    """
    One instance shared across the whole inference worker (not one per
    camera) — a single background thread draining a queue is enough
    for occasional event-driven snapshots; this is not a per-frame
    video writer.

    capture() is the only method the main loop calls. It:
      1. Builds the deterministic output path immediately.
      2. Copies the frame (cheap relative to a disk write) and hands it
         to a background thread.
      3. Returns the path right away — the event payload can include it
         immediately, even though the actual JPEG write finishes a few
         milliseconds later on the background thread.
    """

    def __init__(self, output_dir: str, jpeg_quality: int = 85, queue_maxsize: int = 200):
        os.makedirs(output_dir, exist_ok=True)
        self.output_dir = output_dir
        self.jpeg_quality = jpeg_quality
        self._queue: "queue.Queue[tuple[np.ndarray, str]]" = queue.Queue(maxsize=queue_maxsize)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def capture(self, frame: np.ndarray, camera_id: str, timestamp: float) -> str:
        """
        Non-blocking. Returns the snapshot's file path immediately for
        use in the event payload; the write itself happens async.
        """
        filename = f"{camera_id}_{int(timestamp * 1000)}.jpg"
        path = os.path.join(self.output_dir, filename)

        try:
            # frame.copy() so the background thread has its own buffer —
            # the main loop's `frame` variable gets overwritten next
            # iteration and we don't want a race on the same array.
            self._queue.put_nowait((frame.copy(), path))
        except queue.Full:
            # Under sustained overload, drop the snapshot rather than
            # block the pipeline — a missing snapshot on an event is far
            # better than added latency on every frame. Event data
            # (track_id, bbox, confidence) still reaches the backend
            # either way; only the image is lost.
            print(f"[snapshot] queue full, dropped snapshot for {path}", file=sys.stderr)

        return path

    def _worker(self) -> None:
        while True:
            frame, path = self._queue.get()
            try:
                cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
            except Exception as e:
                print(f"[snapshot] failed to write {path}: {e}", file=sys.stderr)
            finally:
                self._queue.task_done()
