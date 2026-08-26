import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from models import init_db
from snapshot_storage import SNAPSHOT_DIR
from routes.tracks import router as tracks_router
from routes.fences import router as fences_router
from routes.events import router as events_router
from routes.alerts import router as alerts_router
from routes.blacklist import router as blacklist_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="IBVAP Backend", lifespan=lifespan)
app.include_router(tracks_router)
app.include_router(fences_router)
app.include_router(events_router)
app.include_router(alerts_router)
app.include_router(blacklist_router)
app.mount("/snapshots", StaticFiles(directory=SNAPSHOT_DIR), name="snapshots")


@app.get("/health")
def health():
    return {"status": "ok", "service": "backend"}


# TODO Phase 2+: routes/ for cameras; alerting/ SMS + external C2 webhook out

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
