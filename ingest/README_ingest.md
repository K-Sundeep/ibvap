# Ingest service — today's quickstart

Goal: 2-4 looped sample videos served as RTSP → ingested → visible as live video, by EOD.

## 1. Install deps

```bash
pip install -r ../requirements.txt   # or the shared repo-root requirements.txt once merged
sudo apt install ffmpeg              # if not already present (also needed by loop_samples.sh)
```

## 2. Serve sample videos as fake RTSP cameras

Grab 2-4 short CCTV-style clips (any .mp4 works) and run:

```bash
cd ingest
./loop_samples.sh sample1.mp4 sample2.mp4 sample3.mp4
```

This starts one `ffmpeg` process per file, looping it forever and listening for
one RTSP client each on `rtsp://127.0.0.1:8554/cam1`, `:8555/cam2`, `:8556/cam3`
(`:8557/cam4` if you pass a 4th file). Leave this running in its own terminal.

## 3. Configure the ingest service

```bash
cp config.example.yaml config.yaml
```

The example already points `cam1`/`cam2`/`cam3` at the ports above — edit if you
used different ports/camera_ids, or add a `cam4` block for a 4th stream.

## 4. Run the ingest service

```bash
python main.py
```

You should see one "connected to rtsp://..." log line per camera. If a camera
shows "could not open" instead, double check `loop_samples.sh` is still running
and the port/camera_id in `config.yaml` matches.

## 5. Check it's alive

```bash
curl http://localhost:8001/health
curl http://localhost:8001/streams        # per-camera status: connected, frames_read, last_frame_age_s
```

## 6. View live video

- Single frame: open `http://localhost:8001/snapshot/cam1` in a browser
- Live MJPEG: open `http://localhost:8001/stream/cam1` directly in a browser
  tab, or in the dashboard with:
  ```html
  <img src="http://localhost:8001/stream/cam1" />
  ```
  Repeat for cam2/cam3/cam4. This is enough for "video visible in browser" —
  no WebRTC/HLS complexity needed for a hackathon dashboard.

## Notes for later phases

- `/snapshot/<camera_id>` returning a single JPEG is also what the inference
  service (Phase 1) will likely poll or be handed — keeps ingest decoupled
  from the detection code per the architecture.
- `target_fps` in `config.yaml` controls both capture throttling and MJPEG
  push rate — start at 10 and raise/lower depending on GPU load once
  inference is wired in.
- Real cameras later: swap `rtsp_url` in `config.yaml` to the real ONVIF/RTSP
  URL — no code changes needed, ingest doesn't care whether the source is
  ffmpeg-looped or a real BOP camera.
