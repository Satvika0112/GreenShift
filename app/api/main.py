import re
import uuid
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.shared.config import settings, validate_security_config
from app.shared.database import init_db
from app.shared.rate_limiter import limiter
from app.shared.utils import get_logger

logger = get_logger(__name__)

# Request ID regex validation pattern (alphanumeric, hyphens, underscores, dots, 1-128 chars)
REQUEST_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")

# Content Security Policy tailored for API & interactive documentation (Swagger UI / ReDoc)
API_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net data:; "
    "frame-ancestors 'none'; "
    "object-src 'none';"
)

app = FastAPI(
    title="GreenShift API",
    description="Carbon-aware Kubernetes compute scheduling platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Rate Limiter Configuration
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Secure CORS Configuration: Explicit origins loaded from settings, no wildcard with credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_and_request_tracing_middleware(request: Request, call_next):
    """
    Middleware providing Request ID generation & propagation, logging integration,
    and enterprise security response headers.
    """
    # 1. Request ID Handling
    incoming_id = request.headers.get("x-request-id") or request.headers.get("X-Request-ID")
    if incoming_id and REQUEST_ID_REGEX.match(incoming_id.strip()):
        request_id = incoming_id.strip()
    else:
        request_id = str(uuid.uuid4())

    request.state.request_id = request_id

    # 2. Process Request
    response: Response = await call_next(request)

    # 3. Echo Request ID in Response
    response.headers["X-Request-ID"] = request_id

    # 4. Security Headers (No obsolete X-XSS-Protection)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"

    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = API_CSP_POLICY

    # Cache-Control: prevent caching of sensitive API data
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/auth"):
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

    # Strict-Transport-Security (HSTS)
    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
    )
    if is_https or settings.environment == "production" or getattr(settings, "enable_hsts", False):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


@app.on_event("startup")
async def startup_event():
    logger.info("GreenShift API starting up")
    # Fail fast if security configuration is invalid (e.g. missing production secrets)
    validate_security_config(settings)
    init_db()
    try:
        from app.shared.database import SessionLocal
        from app.shared.auth import seed_default_users
        db = SessionLocal()
        seed_default_users(db)
        db.close()
    except Exception as exc:
        logger.warning(f"Default user seeding skipped: {exc}")
    logger.info("Database initialised")


# ─── Routers — registered by each agent ───────────────────────
# Health Checks, Liveness, and Readiness
try:
    from app.api.routers import health as health_router
    app.include_router(health_router.router, prefix="/api/v1", tags=["Health"])
    app.include_router(health_router.router, prefix="", tags=["Health"])
except ImportError:
    logger.warning("Health router not yet implemented")
# Agent 1 — INGEST
try:
    from app.api.routers import ingest as ingest_router
    app.include_router(ingest_router.router, prefix="/api/v1", tags=["Ingest"])
    app.include_router(ingest_router.router, prefix="", tags=["Ingest"])
except ImportError:
    logger.warning("Ingest router not yet implemented")

# Agent 2 — DECIDE
try:
    from app.api.routers import schedule as schedule_router
    app.include_router(schedule_router.router, prefix="/api/v1", tags=["Schedule"])
    app.include_router(schedule_router.router, prefix="", tags=["Schedule"])
except ImportError:
    logger.warning("Schedule router not yet implemented")

# Agent 3 — DISPATCH
try:
    from app.api.routers import dispatch as dispatch_router
    app.include_router(dispatch_router.router, prefix="/api/v1", tags=["Dispatch"])
    app.include_router(dispatch_router.router, prefix="", tags=["Dispatch"])
except ImportError:
    logger.warning("Dispatch router not yet implemented")

# Agent 4 — TRUST
try:
    from app.api.routers import trust as trust_router
    app.include_router(trust_router.router, prefix="/api/v1", tags=["Trust"])
    app.include_router(trust_router.router, prefix="", tags=["Trust"])
except ImportError:
    logger.warning("Trust router not yet implemented")

# Agent 5 — PRESENT
try:
    from app.api.routers import dashboard as dashboard_router
    app.include_router(dashboard_router.router, prefix="/api/v1", tags=["Dashboard"])
    app.include_router(dashboard_router.router, prefix="", tags=["Dashboard"])
except ImportError:
    logger.warning("Dashboard router not yet implemented")

# Human Approval Gate
try:
    from app.api.routers import approval as approval_router
    app.include_router(approval_router.router, prefix="/api/v1", tags=["Approval"])
    app.include_router(approval_router.router, prefix="", tags=["Approval"])
except ImportError:
    logger.warning("Approval router not yet implemented")

# BRSR Report + Data Sources
try:
    from app.api.routers import report as report_router
    app.include_router(report_router.router, prefix="/api/v1", tags=["Report"])
    app.include_router(report_router.router, prefix="", tags=["Report"])
except ImportError:
    logger.warning("Report router not yet implemented")

# Authentication & RBAC
try:
    from app.api.routers import auth as auth_router
    app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["Authentication"])
    app.include_router(auth_router.router, prefix="/auth", tags=["Authentication"])
except ImportError:
    logger.warning("Auth router not yet implemented")

# Operational Metrics & Monitoring
try:
    from app.api.routers import metrics as metrics_router
    app.include_router(metrics_router.router, prefix="", tags=["Metrics"])
except ImportError:
    logger.warning("Metrics router not yet implemented")



