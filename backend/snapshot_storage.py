"""
Local-disk snapshot storage (prototype-grade — swap for object storage later
if this needs to survive beyond a single BOP server).

Inference sends the snapshot as base64 image data on event creation;
this decodes it, writes it under storage/snapshots/<camera_id>/, and
returns a URL path that the backend serves directly via StaticFiles
(mounted in main.py) — that URL path is what gets stored in
events.snapshot_path.
"""

import base64
import os
import uuid

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "storage", "snapshots")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def save_snapshot(camera_id: str, image_base64: str) -> str:
    camera_dir = os.path.join(SNAPSHOT_DIR, camera_id)
    os.makedirs(camera_dir, exist_ok=True)

    # Strip a data URL prefix if present, e.g. "data:image/jpeg;base64,...."
    if image_base64.strip().startswith("data:") and "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    filename = f"{uuid.uuid4().hex}.jpg"
    filepath = os.path.join(camera_dir, filename)
    with open(filepath, "wb") as f:
        f.write(base64.b64decode(image_base64))

    return f"/snapshots/{camera_id}/{filename}"
