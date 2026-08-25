from fastapi import FastAPI

app = FastAPI(title="IBVAP Ingest")


@app.get("/health")
def health():
    return {"status": "ok", "service": "ingest"}


# TODO Phase 0/1: pull RTSP/ONVIF streams from existing IP cameras,
# decode/normalize via GStreamer/FFmpeg/OpenCV, forward frames to inference.

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
