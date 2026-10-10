"""
S.T.R.A.N.D — FastAPI Application Entry Point

Sets up the API server with middleware (CORS, auth, rate limiting, security headers),
mounts all route groups, and initializes the database on startup.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from strand import __version__
from strand.config import get_settings
from strand.db.connection import check_db_health, close_db
from strand.db.migrations import run_migrations
from strand.models import ErrorDetail, ErrorResponse, HealthResponse

logger = logging.getLogger(__name__)


# ─── Application Lifecycle ───────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # Startup
    settings = get_settings()
    settings.ensure_directories()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("S.T.R.A.N.D v%s starting up...", __version__)

    # Run database migrations
    try:
        run_migrations()
        logger.info("Database ready")
    except Exception as e:
        logger.error("Database migration failed: %s", e)
        raise

    yield

    # Shutdown
    close_db()
    logger.info("S.T.R.A.N.D shut down")


# ─── FastAPI App ─────────────────────────────────────────────

app = FastAPI(
    title="S.T.R.A.N.D API",
    description=(
        "Satellite Terrain Response & Network Damage — "
        "Autonomous flood damage mapping and isolation analysis system. "
        "Multimodal AI Hackathon 2026 — Track B."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ─── Middleware ──────────────────────────────────────────────

# Routers
from strand.api.routes.auth import router as auth_router
from strand.api.routes.analysis import router as analysis_router
from strand.api.routes.layers import router as layers_router
from strand.api.routes.copilot import router as copilot_router
from strand.api.routes.exports import router as exports_router

app.include_router(auth_router)
app.include_router(analysis_router)
app.include_router(layers_router)
app.include_router(copilot_router)
app.include_router(exports_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Alternative
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type", "Authorization"],
    allow_credentials=False,
    max_age=3600,
)


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Attribution"] = (
        "Contains modified Copernicus Sentinel data 2026. "
        "(c) OpenStreetMap contributors."
    )
    return response


# Request timing middleware
@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    """Add response timing header for performance monitoring."""
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
    return response


# ─── Health Endpoint ─────────────────────────────────────────

@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="System health check",
)
async def health_check() -> HealthResponse:
    """
    Check system health including database connectivity,
    Redis availability, and GPU status.
    """
    import shutil

    # Database health
    db_status = check_db_health()

    # Redis health
    redis_status = "unknown"
    try:
        import redis as redis_lib

        settings = get_settings()
        r = redis_lib.from_url(settings.redis_url, socket_timeout=2)
        r.ping()
        redis_status = "connected"
    except Exception:
        redis_status = "disconnected"

    # GPU check
    gpu_available = False
    gpu_memory_mb = None
    try:
        import torch

        gpu_available = torch.cuda.is_available()
        if gpu_available:
            gpu_memory_mb = int(
                torch.cuda.get_device_properties(0).total_mem / 1e6
            )
    except ImportError:
        pass

    # Disk space
    disk_free_gb = None
    try:
        settings = get_settings()
        usage = shutil.disk_usage(settings.data_dir)
        disk_free_gb = round(usage.free / 1e9, 1)
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        version=__version__,
        database=db_status,
        redis=redis_status,
        gpu_available=gpu_available,
        gpu_memory_mb=gpu_memory_mb,
        disk_free_gb=disk_free_gb,
        uptime_seconds=0,  # TODO: Track actual uptime
    )


# ─── WebSocket Progress Channel ──────────────────────────────

@app.websocket("/ws/analysis/{analysis_id}")
async def websocket_analysis_progress(websocket: WebSocket, analysis_id: str):
    """
    Real-time WebSocket progress channel for pipeline execution updates.
    Streams phase, status, and completion progress to the dashboard.
    """
    import asyncio
    from strand.db.spatial_queries import get_analysis_summary

    await websocket.accept()
    logger.info("WebSocket connected for analysis %s", analysis_id)

    try:
        while True:
            summary = get_analysis_summary(analysis_id)
            if summary:
                current_phase = summary.get("current_phase", "queued")
                status = summary.get("status", "queued")
                progress_pct = float(summary.get("progress_pct") or 0.0)

                await websocket.send_json({
                    "type": "progress",
                    "analysis_id": analysis_id,
                    "phase": current_phase,
                    "status": status,
                    "progress_pct": progress_pct,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                if status in ("complete", "failed"):
                    if status == "complete":
                        await websocket.send_json({
                            "type": "complete",
                            "analysis_id": analysis_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    break
            else:
                await websocket.send_json({
                    "type": "error",
                    "analysis_id": analysis_id,
                    "message": "Analysis not found",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                break

            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected for analysis %s", analysis_id)
    except Exception as e:
        logger.error("WebSocket exception for analysis %s: %s", analysis_id, e)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ─── Root Redirect ──────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to API docs."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")


# ─── Entry Point ─────────────────────────────────────────────

def run() -> None:
    """Run the API server via uvicorn."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "strand.api.main:app",
        host=settings.strand_host,
        port=settings.strand_port,
        reload=True,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
