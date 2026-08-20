"""
GreenShift — Shared utilities.
"""

import logging
import uuid
from datetime import datetime, timezone

from app.shared.config import settings


def get_logger(name: str) -> logging.Logger:
    """Return a named logger configured with the application log level."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    return logging.getLogger(name)


def generate_job_id() -> str:
    """Generate a unique job ID."""
    return f"JOB-{uuid.uuid4().hex[:8].upper()}"


def generate_event_id() -> str:
    """Generate a unique audit event ID."""
    return f"EVT-{uuid.uuid4().hex[:8].upper()}"


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def k8s_safe_name(job_id: str) -> str:
    """Convert a job_id to a Kubernetes-safe resource name."""
    return job_id.lower().replace("_", "-").replace(".", "-")
