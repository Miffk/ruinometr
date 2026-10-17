import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cleanup import cleanup
from .config import (CACHE_DIR, CACHE_MAX_AGE_DAYS, CACHE_MAX_MB, DATA_DIR, OPENDOTA_API_KEY,
                     OPENDOTA_MIN_INTERVAL)
from .opendota import OpenDota
from .service import AnalysisService, extract_match_id

STATIC_DIR = Path(__file__).resolve().parent / "static"


CLEANUP_EVERY_SECONDS = 6 * 3600


async def _cleanup_loop():
    while True:
        await asyncio.to_thread(cleanup, DATA_DIR, CACHE_MAX_AGE_DAYS, CACHE_MAX_MB)
        await asyncio.sleep(CLEANUP_EVERY_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    od = OpenDota(CACHE_DIR, OPENDOTA_API_KEY, OPENDOTA_MIN_INTERVAL)
    app.state.service = AnalysisService(od)
    cleaner = asyncio.create_task(_cleanup_loop())
    yield
    cleaner.cancel()
    await od.close()


app = FastAPI(title="Ruiner", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """Страница и скрипты меняются вместе с кодом — пусть браузер каждый раз перепроверяет их (ETag), а не берёт из кэша."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith(("/static/", "/match/")):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/analyze/{query}")
async def analyze(query: str, refresh: bool = False):
    match_id = extract_match_id(query)
    if match_id is None:
        raise HTTPException(400, "Не нашёл ID матча — нужно число вроде 9046870406 или ссылка на матч")
    job = app.state.service.get(match_id, refresh=refresh)
    body = job.view()
    if job.state == "done":
        body["result"] = job.result
    return body


@app.get("/")
@app.get("/match/{match_id}")
async def index(match_id: str | None = None):
    return FileResponse(STATIC_DIR / "index.html")
