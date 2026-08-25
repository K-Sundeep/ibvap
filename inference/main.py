from fastapi import FastAPI

app = FastAPI(title="IBVAP Inference")


@app.get("/health")
def health():
    return {"status": "ok", "service": "inference"}


# TODO Phase 1: wire up detector.py (YOLOv8/v10) + tracker.py (ByteTrack/BoT-SORT),
# call backend API directly over HTTP with resulting events.

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
