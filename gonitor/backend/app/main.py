import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings, STATIC_DIR
from app.database import engine, Base
from app.services.scheduler import scheduler, load_and_schedule_all, set_monitoring_enabled
from app.services.ws_manager import ws_manager, broadcast_app_event
from app.routers import auth, dashboard, hosts, host_services, schedule, users, settings_router, events, logs
from app.routers.ai_router import router as ai_router
from app.routers.api import router as api_router
from app.routers.public import router as public_router
from app.dependencies import RedirectException

# Import all models so SQLAlchemy metadata is populated before create_all
import app.models  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)





@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup → create tables, start scheduler. Shutdown → stop cleanly."""
    logger.info("Starting Gonitor...")

    # Create tables (idempotent — only adds missing tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB tables ensured.")


    # Start scheduler
    scheduler.start()
    logger.info("APScheduler started.")

    # Load monitoring state from DB settings
    try:
        from app.database import AsyncSessionFactory
        from sqlalchemy import select
        from app.models.app_settings import AppSettings
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(AppSettings).where(AppSettings.id == 1))
            app_settings = result.scalar_one_or_none()
            if app_settings and not app_settings.monitoring_enabled:
                set_monitoring_enabled(False)
    except Exception as exc:
        logger.warning("Could not load monitoring state: %s", exc)

    # Schedule all active services
    await load_and_schedule_all()

    broadcast_app_event("app-starting")
    yield

    # Shutdown
    logger.info("Shutting down Gonitor...")
    broadcast_app_event("app-stopping")
    scheduler.shutdown(wait=False)
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Gonitor",
    description="Production-quality uptime monitoring service",
    version="2.0.0",
    lifespan=lifespan,
)


# ── Exception Handlers ────────────────────────────────────────────────────
@app.exception_handler(RedirectException)
async def redirect_exception_handler(request: Request, exc: RedirectException):
    return RedirectResponse(url=exc.url, status_code=302)


# ── Static Files ──────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── WebSocket endpoint ────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; we only push, not pull
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        await ws_manager.disconnect(websocket)


# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(dashboard.router)
app.include_router(auth.router)
app.include_router(hosts.router)
app.include_router(host_services.router)
app.include_router(schedule.router)
app.include_router(users.router)
app.include_router(settings_router.router)
app.include_router(events.router)
app.include_router(logs.router)
app.include_router(ai_router)
app.include_router(api_router)
app.include_router(public_router)


# ── API: monitoring status ────────────────────────────────────────────────
@app.get("/api/monitoring/status")
async def monitoring_status():
    from app.services.scheduler import is_monitoring_enabled
    return JSONResponse({"monitoring_enabled": is_monitoring_enabled()})
