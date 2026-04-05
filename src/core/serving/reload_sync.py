"""Cross-worker model reload synchronization via Redis Pub/Sub.

When a Gunicorn worker receives POST /model/reload, it publishes a message
to a Redis channel. All workers subscribe to this channel on startup via
a background thread and reload when they receive a message.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

RELOAD_CHANNEL = "model-reload"


class ReloadSubscriber:
    """Background thread subscribing to Redis reload notifications.

    Gracefully degrades if Redis is unavailable — the subscriber
    logs a warning and does not start, leaving single-worker reload
    as the fallback behavior.

    Args:
        redis_url: Redis connection URL (e.g. ``redis://redis:6379/0``).
        on_reload: Callback invoked with reload payload when a message is received.
    """

    def __init__(self, redis_url: str, on_reload: Callable[[dict[str, Any]], None]) -> None:
        self._redis_url = redis_url
        self._on_reload = on_reload
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._worker_id = f"pid-{os.getpid()}"
        self._client: Any = None

    def start(self) -> None:
        """Start the background subscriber thread."""
        try:
            import redis

            self._client = redis.from_url(self._redis_url)
            self._client.ping()
        except Exception:
            logger.warning(
                "Redis not available at %s — reload sync disabled. "
                "Model reloads will only affect the worker receiving the request.",
                self._redis_url,
                exc_info=True,
            )
            return

        self._thread = threading.Thread(
            target=self._listen,
            name="reload-subscriber",
            daemon=True,
        )
        self._thread.start()
        logger.info("Reload subscriber started (worker=%s, channel=%s)", self._worker_id, RELOAD_CHANNEL)

    def stop(self) -> None:
        """Stop the background subscriber thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Reload subscriber stopped (worker=%s)", self._worker_id)

    def publish_reload(self, payload: dict[str, Any]) -> bool:
        """Publish a reload message so all workers pick it up.

        Args:
            payload: Reload parameters (model_name, model_version, etc.).

        Returns:
            True if the message was published, False if Redis is unavailable.
        """
        if self._client is None:
            logger.warning("Cannot publish reload — Redis client not initialized.")
            return False
        try:
            message = json.dumps({**payload, "source_worker": self._worker_id})
            self._client.publish(RELOAD_CHANNEL, message)
            logger.info("Published reload message from worker %s", self._worker_id)
            return True
        except Exception:
            logger.warning("Failed to publish reload to Redis — other workers will not be notified.", exc_info=True)
            return False

    @property
    def is_active(self) -> bool:
        """Whether the subscriber thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def _listen(self) -> None:
        """Subscribe to the Redis channel and invoke callback on messages."""
        import redis

        try:
            pubsub = self._client.pubsub()
            pubsub.subscribe(RELOAD_CHANNEL)

            for message in pubsub.listen():
                if self._stop_event.is_set():
                    break

                if message["type"] != "message":
                    continue

                try:
                    payload = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Ignoring malformed reload message: %s", message["data"])
                    continue

                source = payload.get("source_worker", "unknown")
                if source == self._worker_id:
                    # Skip messages from self (already reloaded locally)
                    continue

                logger.info("Received reload notification from worker %s", source)
                try:
                    self._on_reload(payload)
                except Exception:
                    logger.exception("Reload callback failed for message from %s", source)

            pubsub.unsubscribe()
            pubsub.close()
        except redis.ConnectionError:
            logger.warning("Redis connection lost — reload sync disabled until restart.")
        except Exception:
            logger.exception("Unexpected error in reload subscriber")
