"""WebSocket real-time event streaming (task 17.1).

Exposes a single WebSocket endpoint, ``GET /ws/events``, that pushes live
platform updates to connected dashboard clients (Requirements 20.1, 20.2,
21.2). The dashboard heatmap, alert badges, self-healing status and approval
queue counts update in real time without manual refresh.

How it works
------------
1. A client connects to ``/ws/events``. The connection is registered with a
   module-level :class:`ConnectionManager` and immediately receives a
   ``hello`` envelope so the frontend can confirm liveness.
2. The broadcaster subscribes to the relevant event-bus events
   (:data:`_STREAM_TYPE_BY_EVENT`). Each internal :class:`Event` is translated
   into a frontend-facing stream message and broadcast to every connected
   client. Because the event bus dispatches handlers concurrently and never
   blocks the publisher, updates reach clients well within the 2-second budget
   (Requirement 20.1).
3. A lightweight periodic heartbeat keeps the connection warm so the frontend
   "data stale" indicator (task 17.2 / Requirement 20.3) only trips on a real
   connection loss.

Message envelope
----------------
Every message is a JSON object with a consistent shape::

    {
      "type":          "heatmap_update",   # frontend-facing stream type
      "event_type":    "score_updated",    # internal EventType value (or null)
      "data":          { ... },            # the event payload
      "timestamp":     "2024-01-01T00:00:00+00:00",
      "correlation_id":"<uuid>"            # trace id (absent on hello/heartbeat)
    }

Stream types (Requirement 20.2) and their source events:

    heatmap_update     <- SCORE_UPDATED            (priority score / cell color)
    alert_new          <- ALERT_FIRED              (new alert badge)
    healing_status     <- REMEDIATION_COMPLETED    (self-healing transition)
    approval_count     <- RECOMMENDATION_GENERATED (approval queue count change)
    prediction_update  <- PREDICTION_UPDATED       (downtime forecast refresh)

Plus two control messages with ``event_type == null``: ``hello`` (on connect)
and ``heartbeat`` (periodic liveness ping).

Robustness
----------
- Slow or broken clients are tolerated: a failed ``send`` removes only that
  client and never breaks the broadcast loop or the event bus.
- Disconnects are handled cleanly (the client is deregistered on
  ``WebSocketDisconnect``).
- :func:`register_subscriptions` is idempotent so repeated calls (lifespan,
  test setup, re-import) wire the handlers at most once.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.event_bus import Event, EventType, event_bus

logger = logging.getLogger("clover.api.websocket")

router = APIRouter(tags=["websocket"])


# Map an internal EventType to the frontend-facing stream message ``type``.
_STREAM_TYPE_BY_EVENT: dict[EventType, str] = {
    EventType.SCORE_UPDATED: "heatmap_update",
    EventType.ALERT_FIRED: "alert_new",
    EventType.REMEDIATION_COMPLETED: "healing_status",
    EventType.RECOMMENDATION_GENERATED: "approval_count",
    EventType.PREDICTION_UPDATED: "prediction_update",
}

# Seconds between liveness heartbeats sent to connected clients.
_HEARTBEAT_INTERVAL = 15.0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_message(stream_type: str, event: Event) -> dict:
    """Translate an internal :class:`Event` into a stream envelope."""
    timestamp = event.timestamp
    return {
        "type": stream_type,
        "event_type": event.event_type.value,
        "data": event.payload,
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else _utcnow_iso(),
        "correlation_id": event.correlation_id,
    }


def _control_message(message_type: str, data: dict | None = None) -> dict:
    """Build a control envelope (``hello`` / ``heartbeat``) with no event."""
    return {
        "type": message_type,
        "event_type": None,
        "data": data or {},
        "timestamp": _utcnow_iso(),
    }


class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts envelopes to them.

    All mutation of the connection set is guarded by an :class:`asyncio.Lock`
    so concurrent connect/disconnect/broadcast operations stay consistent.
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """The event loop the connections live on (captured on first connect)."""
        return self._loop

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new client connection."""
        await websocket.accept()
        self._loop = asyncio.get_running_loop()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WebSocket client connected (total=%d)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Deregister a client connection (no-op if already removed)."""
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WebSocket client disconnected (total=%d)", len(self._connections))

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        """Send a single envelope to one client."""
        await websocket.send_json(message)

    async def broadcast(self, message: dict) -> None:
        """Send ``message`` to every connected client.

        A failing client is dropped from the registry but never aborts the
        loop, so one slow/broken consumer cannot stall the others or the bus.
        """
        async with self._lock:
            targets = list(self._connections)
        if not targets:
            return

        broken: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except Exception:  # noqa: BLE001 - isolate a bad client from the broadcast
                logger.debug("Dropping unreachable WebSocket client during broadcast")
                broken.append(websocket)

        if broken:
            async with self._lock:
                for websocket in broken:
                    self._connections.discard(websocket)


# Module-level singleton shared by the endpoint and the event handlers.
manager = ConnectionManager()


# --------------------------------------------------------------------------- #
# Event bus -> WebSocket bridge
# --------------------------------------------------------------------------- #
async def _on_event(event: Event) -> None:
    """Broadcast a mapped event-bus event to all connected clients."""
    stream_type = _STREAM_TYPE_BY_EVENT.get(event.event_type)
    if stream_type is None:
        return
    await manager.broadcast(_build_message(stream_type, event))


_subscribed = False


def register_subscriptions() -> None:
    """Subscribe the broadcaster to the streamed event types (idempotent)."""
    global _subscribed
    if _subscribed:
        return
    for event_type in _STREAM_TYPE_BY_EVENT:
        event_bus.subscribe(event_type, _on_event)
    _subscribed = True
    logger.info(
        "WebSocket broadcaster subscribed to %d event types",
        len(_STREAM_TYPE_BY_EVENT),
    )


def unregister_subscriptions() -> None:
    """Remove the broadcaster's event-bus subscriptions (idempotent)."""
    global _subscribed
    if not _subscribed:
        return
    for event_type in _STREAM_TYPE_BY_EVENT:
        event_bus.unsubscribe(event_type, _on_event)
    _subscribed = False
    logger.info("WebSocket broadcaster unsubscribed")


# --------------------------------------------------------------------------- #
# Heartbeat (optional liveness ping)
# --------------------------------------------------------------------------- #
_heartbeat_task: asyncio.Task | None = None


async def _heartbeat_loop() -> None:
    """Periodically broadcast a heartbeat so clients can detect liveness."""
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        if manager.connection_count:
            await manager.broadcast(_control_message("heartbeat"))


def start_heartbeat() -> None:
    """Start the background heartbeat loop (idempotent)."""
    global _heartbeat_task
    if _heartbeat_task is None or _heartbeat_task.done():
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())
        logger.info("WebSocket heartbeat started (interval=%.0fs)", _HEARTBEAT_INTERVAL)


async def stop_heartbeat() -> None:
    """Cancel and drain the background heartbeat loop (idempotent)."""
    global _heartbeat_task
    if _heartbeat_task is not None and not _heartbeat_task.done():
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass
    _heartbeat_task = None


# --------------------------------------------------------------------------- #
# WebSocket endpoint
# --------------------------------------------------------------------------- #
@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """Stream real-time platform events to a connected dashboard client."""
    await manager.connect(websocket)
    try:
        # Initial hello so the frontend can confirm the channel is live.
        await manager.send_personal(
            websocket,
            _control_message("hello", {"stream": "events", "message": "connected"}),
        )
        # We don't require inbound messages; receiving keeps the connection
        # open and surfaces a clean WebSocketDisconnect when the client leaves.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:  # noqa: BLE001 - any failure should still deregister cleanly
        logger.exception("WebSocket connection error; deregistering client")
        await manager.disconnect(websocket)
