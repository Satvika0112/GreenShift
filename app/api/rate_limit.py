"""
GreenShift API — In-memory sliding-window rate limiter.

NOTE: This rate limiter is designed for single-instance deployment.
In a multi-replica deployment behind a load balancer, a client could
bypass limits by hitting different instances. A distributed deployment
should migrate limiter state to Redis or another shared store.

Usage:
    from app.api.rate_limit import rate_limit_expensive

    @router.post("/some-endpoint")
    def my_endpoint(_rate: None = Depends(rate_limit_expensive)):
        ...
"""

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request


class RateLimiter:
    """
    Thread-safe in-memory sliding-window rate limiter.

    NOTE: Single-instance only. See module docstring for multi-replica guidance.
    """

    def __init__(self, max_requests: int = 30, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, client_key: str) -> None:
        """
        Enforce the rate limit for the given client key (typically IP address).
        Raises HTTP 429 if the limit is exceeded.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            window = self._windows[client_key]
            # Evict timestamps outside the sliding window
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= self.max_requests:
                retry_after = int(self.window_seconds - (now - window[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded: {self.max_requests} requests "
                        f"per {self.window_seconds}s window. "
                        f"Retry after {retry_after}s."
                    ),
                    headers={"Retry-After": str(retry_after)},
                )

            window.append(now)

    def reset(self, client_key: Optional[str] = None) -> None:  # type: ignore[name-defined]
        """Reset rate limit counters (for testing)."""
        with self._lock:
            if client_key:
                self._windows.pop(client_key, None)
            else:
                self._windows.clear()


# Shared instance — 30 write requests per 60 seconds per IP
_expensive_limiter = RateLimiter(max_requests=30, window_seconds=60)

# Login limiter — stricter: 10 attempts per 60 seconds per IP
_login_limiter = RateLimiter(max_requests=10, window_seconds=60)


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For in proxied setups."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit_expensive(request: Request) -> None:
    """
    FastAPI dependency: enforce rate limit on expensive write endpoints.
    30 requests per 60 seconds per IP address.
    """
    _expensive_limiter.check(_get_client_ip(request))


def rate_limit_login(request: Request) -> None:
    """
    FastAPI dependency: enforce stricter rate limit on login endpoint.
    10 requests per 60 seconds per IP address.
    """
    _login_limiter.check(_get_client_ip(request))


def reset_rate_limiters() -> None:
    """Reset all rate limiter state (for use in tests)."""
    _expensive_limiter.reset()
    _login_limiter.reset()
