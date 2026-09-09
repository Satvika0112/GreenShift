"""
GreenShift — Centralized Rate Limiter

Provides SlowAPI Limiter instance and rate limiting helpers
for protecting sensitive endpoints against brute-force and resource exhaustion.
"""

import os
from slowapi import Limiter
from slowapi.util import get_remote_address

storage_uri = os.environ.get("REDIS_URL", "memory://")

# Centralized Limiter instance
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    storage_uri=storage_uri,
)


def reset_rate_limiter() -> None:
    """Reset all in-memory rate limiting counters (primarily used in test fixtures)."""
    try:
        limiter._limiter.storage.reset()
    except Exception:
        pass
