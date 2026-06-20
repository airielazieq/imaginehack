"""Tests for the WebSocket real-time event stream (task 17.1).

Covers Requirements 20.1, 20.2, 21.2:

- A client can connect to ``/ws/events`` and immediately receives a ``hello``
  control envelope (initial liveness).
- When a mapped event is published on the event bus, every connected client
  receives a correctly-shaped stream envelope (``type`` / ``event_type`` /
  ``data`` / ``timestamp``) with the frontend-facing stream type.
- A disconnect deregisters the client from the connection manager.
- A broken client is dropped without aborting the broadcast for healthy ones.

The full application pipeline is active during these tests (scoring recomputes
on remediation/recommendation events and cascades into SCORE_UPDATED, etc.), so
the helpers below filter the stream by the expected message type rather than
assuming exactly one message per publish.

An isolated temp SQLite DB is configured via CLOVER_DB_PATH before the app is
imported so tests never touch the real clover.db.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_ws_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import websocket as websocket_api  # noqa: E402
from backend.api.websocket import ConnectionManager, _build_message  # noqa: E402
from backend.core.event_bus import Event, EventType, event_bus  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """Start the app once for the whole module (lifespan wires the broadcaster)."""
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _publish_on_app_loop(event: Event) -> None:
    """Publish ``event`` on the running app event loop and wait for handlers.

    The WebSocket connections live on the loop the ASGI app runs on, so the
    publish must happen on that loop for the broadcaster's ``send_json`` to
    reach the queue the TestClient session reads from.
    """
    loop = websocket_api.manager.loop
    assert loop is not None, "expected the app loop to be captured on connect"
    future = asyncio.run_coroutine_threadsafe(event_bus.publish_and_wait(event), loop)
    future.result(timeout=5)


def _receive_until(ws, expected_type: str, *, workload_id: str | None = None, max_msgs: int = 25):
    """Read messages until one matches ``expected_type`` (and workload_id)."""
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg["type"] != expected_type:
            continue
        if workload_id is not None and msg.get("data", {}).get("workload_id") != workload_id:
            continue
        return msg
    raise AssertionError(f"did not receive a {expected_type!r} message within {max_msgs} messages")


def _wait_for_connection_count(expected: int, *, timeout: float = 3.0) -> None:
    """Poll the manager until it reports ``expected`` connections.

    Disconnect handling runs asynchronously on the app loop after the client
    closes, so the count converges shortly after the ``with`` block exits.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if websocket_api.manager.connection_count == expected:
            return
        time.sleep(0.02)
    assert websocket_api.manager.connection_count == expected


# --------------------------------------------------------------------------- #
# End-to-end via TestClient WebSocket support
# --------------------------------------------------------------------------- #
def test_connect_receives_hello_and_registers_client(client):
    """A connecting client gets a hello envelope and is tracked by the manager."""
    with client.websocket_connect("/ws/events") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["event_type"] is None
        assert hello["data"]["stream"] == "events"
        assert "timestamp" in hello
        assert websocket_api.manager.connection_count == 1
    # After the context closes, the client is deregistered (Req 20.3 cleanup).
    _wait_for_connection_count(0)


def test_score_updated_broadcasts_heatmap_update_envelope(client):
    """Publishing SCORE_UPDATED pushes a heatmap_update envelope to the client."""
    with client.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "hello"

        event = Event(
            event_type=EventType.SCORE_UPDATED,
            payload={"workload_id": "wl-ws-1", "score": 42.5},
        )
        _publish_on_app_loop(event)

        msg = _receive_until(ws, "heatmap_update", workload_id="wl-ws-1")
        # Frontend-facing stream type + internal event type are both present.
        assert msg["type"] == "heatmap_update"
        assert msg["event_type"] == EventType.SCORE_UPDATED.value
        assert msg["data"] == {"workload_id": "wl-ws-1", "score": 42.5}
        assert msg["timestamp"]
        assert msg["correlation_id"] == event.correlation_id
    _wait_for_connection_count(0)


def test_mapped_event_types_produce_expected_stream_types(client):
    """Each mapped event type broadcasts its frontend-facing stream type."""
    cases = [
        (EventType.ALERT_FIRED, "alert_new", "wl-ws-alert"),
        (EventType.REMEDIATION_COMPLETED, "healing_status", "wl-ws-heal"),
        (EventType.RECOMMENDATION_GENERATED, "approval_count", "wl-ws-rec"),
        (EventType.PREDICTION_UPDATED, "prediction_update", "wl-ws-pred"),
    ]
    with client.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "hello"

        for event_type, stream_type, workload_id in cases:
            _publish_on_app_loop(
                Event(event_type=event_type, payload={"workload_id": workload_id})
            )
            msg = _receive_until(ws, stream_type, workload_id=workload_id)
            assert msg["type"] == stream_type
            assert msg["event_type"] == event_type.value
            assert msg["data"]["workload_id"] == workload_id
    _wait_for_connection_count(0)


def test_disconnect_deregisters_client(client):
    """Leaving the WebSocket context removes the client from the manager."""
    with client.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "hello"
        assert websocket_api.manager.connection_count == 1
    _wait_for_connection_count(0)


# --------------------------------------------------------------------------- #
# Pure-function / manager unit tests (deterministic, no app startup needed)
# --------------------------------------------------------------------------- #
def test_stream_type_mapping_covers_required_events():
    """All five required stream types map from a distinct internal event."""
    mapping = websocket_api._STREAM_TYPE_BY_EVENT
    assert set(mapping.values()) == {
        "heatmap_update",
        "alert_new",
        "healing_status",
        "approval_count",
        "prediction_update",
    }
    assert len(mapping) == len(set(mapping.values()))  # one-to-one


def test_build_message_envelope_shape():
    """The envelope carries type, internal event_type, data and timestamp."""
    event = Event(event_type=EventType.ALERT_FIRED, payload={"alert_id": "a-1"})
    msg = _build_message("alert_new", event)
    assert msg["type"] == "alert_new"
    assert msg["event_type"] == "alert_fired"
    assert msg["data"] == {"alert_id": "a-1"}
    assert msg["timestamp"] == event.timestamp.isoformat()
    assert msg["correlation_id"] == event.correlation_id


class _FakeWebSocket:
    """Minimal stand-in for a Starlette WebSocket used in manager unit tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self.accepted = False
        self.sent: list[dict] = []
        self._fail = fail

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        if self._fail:
            raise RuntimeError("client is broken")
        self.sent.append(message)


def test_broadcast_drops_broken_client_without_breaking_others():
    """A failing client is removed; healthy clients still receive the message."""

    async def _run():
        mgr = ConnectionManager()
        good = _FakeWebSocket()
        bad = _FakeWebSocket(fail=True)
        await mgr.connect(good)
        await mgr.connect(bad)
        assert mgr.connection_count == 2

        payload = {"type": "heartbeat", "event_type": None, "data": {}}
        await mgr.broadcast(payload)

        # The healthy client received the message; the broken one was dropped.
        assert good.sent == [payload]
        assert mgr.connection_count == 1

    asyncio.run(_run())
