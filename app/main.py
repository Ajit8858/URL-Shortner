import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.background import run_click_flusher_forever
from app.cache import get_redis
from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.id_generator import seed_counter_floor
from app.routers import auth, urls

logging.basicConfig(level=logging.INFO)
settings = get_settings()

_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: sanity-check Redis connectivity and kick off the click
    # flusher. (Run the flusher as its own worker deployment in
    # production once you have multiple app replicas — see background.py.)
    redis = get_redis()
    try:
        await redis.ping()
    except Exception:
        logging.warning("Redis unreachable at startup — degraded mode.")

    # Reconcile the ID counter against Postgres's actual max(id) every
    # time an app instance boots. Cheap (one query, one Lua call) and it
    # turns "Redis lost the counter" from a write-outage into a no-op.
    # See id_generator.seed_counter_floor for the full rationale.
    try:
        from sqlalchemy import func, select

        from app.models import URL

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(func.max(URL.id)))
            current_max = result.scalar() or 0
        floor = await seed_counter_floor(redis, current_max)
        logging.info(
            "ID counter reconciled: db_max=%d redis_counter=%d", current_max, floor
        )
    except Exception:
        logging.exception("ID counter reconciliation failed at startup")

    task = asyncio.create_task(run_click_flusher_forever())
    _background_tasks.add(task)

    yield

    # Shutdown: clean up connections.
    for t in _background_tasks:
        t.cancel()
    await engine.dispose()
    await redis.aclose()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus /metrics endpoint — scrape this from each replica for
# request-rate / latency / error-rate dashboards and autoscaling signals.
Instrumentator().instrument(app).expose(app, include_in_schema=False)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def readiness():
    """Deep health check for k8s/ALB readiness probes — verifies the
    app can actually reach its dependencies, not just that it's up."""
    from sqlalchemy import text

    redis = get_redis()
    checks = {"redis": False, "database": False}
    try:
        await redis.ping()
        checks["redis"] = True
    except Exception:
        pass
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass

    ok = all(checks.values())
    return JSONResponse(
        status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"ready": ok, "checks": checks},
    )


app.include_router(auth.router)
# IMPORTANT: urls.router contains a catch-all GET /{short_code} redirect
# route. It must be included LAST so it never shadows a more specific
# path (/health, /metrics, /docs, /api/v1/...) registered above it —
# FastAPI matches routes in registration order.
app.include_router(urls.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error"}
    )
