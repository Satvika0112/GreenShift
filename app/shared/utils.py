"""
GreenShift — Shared utilities.
"""

import json
import logging
import sys
import uuid
from datetime import datetime, timezone

from app.shared.config import settings


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger configured with environment-aware formatting."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if getattr(settings, "environment", "") == "production":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
            ))
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    return logger


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
