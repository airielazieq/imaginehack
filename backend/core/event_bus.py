"""Async pub/sub event bus for in-process module decoupling.

The bus lets modules (Detection, NBA, Self-Healing, Scoring, Alerts, Audit)
react to one another without direct coupling. Handlers are registered per
:class:`EventType` and dispatched asynchronously so publishing never blocks
the caller's pipeline.

Design notes:
- Single-process MVP: a simple in-memory registry of handlers.
- ``publish`` schedules each subscriber via ``asyncio.create_task`` (fire and
  forget) so a slow/failed subscriber cannot block the publisher.
- Handler exceptions are caught and logged, never propagated to the publisher.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Awaitable, Callable

logger = logging.getLogger("clover.event_bus")


class EventType(str, Enum):
    """All internal event types emitted across the platform pipeline."""

    TELEMETRY_INGESTED = "telemetry_ingested"
    ISSUE_DETECTED = "issue_detected"
    RECOMMENDATION_GENERATED = "recommendation_generated"
    REMEDIATION_COMPLETED = "remediation_completed"
    SCORE_UPDATED = "score_updated"
    ALERT_FIRED = "alert_fired"
    PREDICTION_UPDATED = "prediction_updated"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Event:
    """An event flowing through the bus.

    Attributes:
        event_type: The category of event (see :class:`EventType`).
        payload: Arbitrary event data (e.g. workload_id, issue dict).
        timestamp: When the event was created (UTC).
        correlation_id: Trace id linking related events across the pipeline.
    """

    event_type: EventType
    payload: dict
    timestamp: datetime = field(default_factory=_utcnow)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# A handler receives an Event and may be async.
EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """In-memory asyncio pub/sub event bus.

    Subscribers register an async handler against an :class:`EventType`.
    Publishing dispatches to every registered handler concurrently.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._tasks: set[asyncio.Task] = set()

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register ``handler`` to be invoked for ``event_type`` events."""
        self._subscribers[event_type].append(handler)
        logger.debug("Subscribed handler %s to %s", getattr(handler, "__name__", handler), event_type)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a previously registered handler. No-op if not present."""
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: Event) -> None:
        """Dispatch ``event`` to all subscribers without blocking on them.

        Each handler runs in its own task. Exceptions raised by handlers are
        logged and swallowed so one bad subscriber cannot break the pipeline.
        """
        handlers = list(self._subscribers.get(event.event_type, []))
        if not handlers:
            logger.debug("No subscribers for %s", event.event_type)
            return

        for handler in handlers:
            task = asyncio.create_task(self._safe_invoke(handler, event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def publish_and_wait(self, event: Event) -> None:
        """Dispatch ``event`` and await completion of all handlers.

        Useful for tests and deterministic pipelines where the caller needs to
        observe the side effects before continuing.
        """
        handlers = list(self._subscribers.get(event.event_type, []))
        await asyncio.gather(
            *(self._safe_invoke(handler, event) for handler in handlers)
        )

    async def _safe_invoke(self, handler: EventHandler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:  # noqa: BLE001 - intentionally broad; isolate subscribers
            logger.exception(
                "Event handler %s failed for %s (correlation_id=%s)",
                getattr(handler, "__name__", handler),
                event.event_type,
                event.correlation_id,
            )

    async def aclose(self) -> None:
        """Cancel and drain any in-flight handler tasks (used on shutdown)."""
        pending = [t for t in self._tasks if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()


# Module-level singleton used across the application.
event_bus = EventBus()
