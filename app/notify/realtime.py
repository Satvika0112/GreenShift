"""
GreenShift — Real-Time Notification Delivery (Server-Sent Events).

Pushes newly created notifications to the recipient's open browser tab(s)
the moment app.notify.service.create_notification() commits them, so the
bell/unread-count/toast update without the client polling.

Transport: Redis Pub/Sub (the project already depends on Redis — see
app.shared.carbon_cache.get_redis_client, reused here rather than adding a
second connection/circuit-breaker implementation) fanned out over one
Server-Sent Events stream per connected user. This works whether the API,
ingest, scheduler, dispatcher and trust workers run as one process (local
dev) or as separate containers (docker-compose/K8s) — a notification
created by any of them reaches any API process holding that user's SSE
connection.

Contract:
  - Best-effort, additive: publish_notification_event() never raises and
    never blocks the caller's business transaction. If Redis is
    unavailable, notifications are still created and still visible via the
    existing polling endpoints (GET /notifications, /unread-count) — this
    module only ever adds a faster delivery path, never a dependency.
  - Per-user channel: a subscriber only ever receives events published to
    *their own* user id's channel — there is no broadcast/shared channel,
    so there is no cross-user or cross-tenant leak at the transport layer.
  - No notification content is invented here: the published payload is the
    same NotificationResponse-shaped JSON the REST endpoints already return.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict

from app.shared.carbon_cache import get_redis_client

logger = logging.getLogger("greenshift.notify.realtime")

_CHANNEL_PREFIX = "greenshift:notify:user:"
_HEARTBEAT_SECONDS = 15.0
_POLL_TIMEOUT_SECONDS = 5.0


def _channel_name(user_id: int) -> str:
    return f"{_CHANNEL_PREFIX}{user_id}"


def publish_notification_event(user_id: int, payload: Dict[str, Any]) -> None:
    """
    Best-effort real-time push of one notification to `user_id`'s live
    connection(s). Must never raise — a slow/unavailable Redis must never
    affect notification creation or the business transaction that
    triggered it (the same "fail open" contract as the audit ledger).
    """
    try:
        client = get_redis_client()
        if client is None:
            return
        client.publish(_channel_name(user_id), json.dumps(payload, default=str))
    except Exception:
        logger.debug("Realtime publish failed for user %s", user_id, exc_info=True)


async def notification_event_stream(user_id: int) -> AsyncGenerator[str, None]:
    """
    Authenticated, per-user SSE frame generator. The caller (the router)
    is responsible for establishing that `user_id` is the authenticated
    caller's own id — this function trusts its argument, it does not
    re-derive identity.

    Degrades gracefully: if Redis is unavailable, still yields a
    "connected" frame (with realtime:false) plus periodic heartbeats, so
    the frontend's connection-state UI is accurate and the existing
    polling fallback remains the source of truth.
    """
    client = get_redis_client()
    if client is None:
        yield 'event: connected\ndata: {"realtime": false}\n\n'
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_SECONDS)
                yield ": keepalive\n\n"
        except asyncio.CancelledError:
            return

    pubsub = client.pubsub()
    channel = _channel_name(user_id)
    try:
        pubsub.subscribe(channel)
    except Exception:
        logger.debug("Realtime subscribe failed for user %s", user_id, exc_info=True)
        yield 'event: connected\ndata: {"realtime": false}\n\n'
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_SECONDS)
                yield ": keepalive\n\n"
        except asyncio.CancelledError:
            return

    try:
        yield 'event: connected\ndata: {"realtime": true}\n\n'
        loop = asyncio.get_event_loop()
        last_heartbeat = loop.time()
        while True:
            try:
                message = await asyncio.to_thread(
                    pubsub.get_message, timeout=_POLL_TIMEOUT_SECONDS, ignore_subscribe_messages=True
                )
            except Exception:
                # Redis connection dropped mid-stream — end the generator so
                # the router closes the response; the frontend reconnects.
                logger.debug("Realtime poll failed for user %s, ending stream", user_id, exc_info=True)
                return
            if message and message.get("type") == "message":
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                yield f"event: notification\ndata: {data}\n\n"
                last_heartbeat = loop.time()
                continue
            now = loop.time()
            if now - last_heartbeat >= _HEARTBEAT_SECONDS:
                yield ": keepalive\n\n"
                last_heartbeat = now
    except asyncio.CancelledError:
        raise
    finally:
        try:
            pubsub.unsubscribe(channel)
            pubsub.close()
        except Exception:
            pass
