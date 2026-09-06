"""
GreenShift — Centralized Rate Limiter

Provides SlowAPI Limiter instance and rate limiting helpers
for protecting sensitive endpoints against brute-force and resource exhaustion.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Centralized Limiter instance
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    storage_uri="memory://",
)
