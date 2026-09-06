"""
GreenShift — FastAPI Application Entry Point
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.shared.config import settings
from app.shared.database import init_db
from app.shared.utils import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="GreenShift API",
    description="Carbon-aware Kubernetes compute scheduling platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    logger.info("GreenShift API starting up")
    init_db()
    logger.info("Database initialised")


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "greenshift-api"}


# ─── Routers — registered by each agent ───────────────────────
# Agent 1 — INGEST
try:
    from app.api.routers import ingest as ingest_router
    app.include_router(ingest_router.router, prefix="/api/v1", tags=["Ingest"])
except ImportError:
    logger.warning("Ingest router not yet implemented")

# Agent 2 — DECIDE
try:
    from app.api.routers import schedule as schedule_router
    app.include_router(schedule_router.router, prefix="/api/v1", tags=["Schedule"])
except ImportError:
    logger.warning("Schedule router not yet implemented")

# Agent 3 — DISPATCH
try:
    from app.api.routers import dispatch as dispatch_router
    app.include_router(dispatch_router.router, prefix="/api/v1", tags=["Dispatch"])
except ImportError:
    logger.warning("Dispatch router not yet implemented")

# Agent 4 — TRUST
try:
    from app.api.routers import trust as trust_router
    app.include_router(trust_router.router, prefix="/api/v1", tags=["Trust"])
except ImportError:
    logger.warning("Trust router not yet implemented")

# Agent 5 — PRESENT
try:
    from app.api.routers import dashboard as dashboard_router
    app.include_router(dashboard_router.router, prefix="/api/v1", tags=["Dashboard"])
except ImportError:
    logger.warning("Dashboard router not yet implemented")

# Human Approval Gate
try:
    from app.api.routers import approval as approval_router
    app.include_router(approval_router.router, prefix="/api/v1", tags=["Approval"])
except ImportError:
    logger.warning("Approval router not yet implemented")

# BRSR Report + Data Sources
try:
    from app.api.routers import report as report_router
    app.include_router(report_router.router, prefix="/api/v1", tags=["Report"])
except ImportError:
    logger.warning("Report router not yet implemented")

