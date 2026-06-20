"""Tests for the MCP activity log (task 18.2).

Covers the two remaining sub-bullets of task 18.2:
- every connector invocation is logged centrally at the ConnectorRegistry
  dispatch chokepoint (``mcp_log_service.record_invocation``),
- the list/filter query (``list_mcp_log``) returns entries most-recent-first
  and filters by ``workload_id``,
- ``GET /api/mcp/log`` returns the entries as a **bare list** in ``data``, with
  and without the ``workload_id`` query filter.

A temporary SQLite database is configured via ``CLOVER_DB_PATH`` before the app
is imported so tests never touch the real ``clover.db``.
"""

from __future__ import annotations

import os
import tempfile

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="clover_mcplog_test_"), "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.connectors import ConnectorRegistry  # noqa: E402
from backend.core.database import init_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services import mcp_log_service  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    """Ensure the schema (incl. the mcp_log table) exists in the temp DB."""
    init_db()


# --------------------------------------------------------------------------- #
# 1. A connector invocation is logged at the registry chokepoint
# --------------------------------------------------------------------------- #
def test_registry_execute_logs_connector_invocation():
    registry = ConnectorRegistry(log_invocations=True)
    execution = registry.execute(
        "schedule_shutdown",
        workload_id="wl-log-001",
        remediation_id="REM-LOG-1",
    )
    assert execution.status == "success"

    entries = mcp_log_service.list_mcp_log("wl-log-001")
    assert len(entries) == 1
    entry = entries[0]
    # Matches the frontend MCPLogEntry contract.
    assert entry["tool"] == "schedule_shutdown"
    assert entry["category"] == "cloud"
    assert entry["workload_id"] == "wl-log-001"
    assert entry["remediation_id"] == "REM-LOG-1"
    assert entry["policy_compliance"] == "compliant"
    assert isinstance(entry["params"], dict)
    assert isinstance(entry["result"], dict)
    assert entry["params"].get("workload_id") == "wl-log-001"
    assert "timestamp" in entry


def test_registry_without_logging_does_not_record():
    """Logging is opt-in: a default registry must not write to the log."""
    registry = ConnectorRegistry()  # log_invocations defaults to False
    registry.execute("schedule_shutdown", workload_id="wl-nolog-001")
    assert mcp_log_service.list_mcp_log("wl-nolog-001") == []


# --------------------------------------------------------------------------- #
# 2. list/filter query works and is most-recent-first
# --------------------------------------------------------------------------- #
def test_list_mcp_log_filters_by_workload_and_orders_recent_first():
    registry = ConnectorRegistry(log_invocations=True)
    # Two invocations for the same workload (different categories/tools).
    registry.execute("resize_resource", workload_id="wl-filter-A")
    registry.execute("create_ticket", workload_id="wl-filter-A")
    # One invocation for a different workload.
    registry.execute("notify_owner", workload_id="wl-filter-B")

    a_entries = mcp_log_service.list_mcp_log("wl-filter-A")
    assert {e["tool"] for e in a_entries} == {"resize_resource", "create_ticket"}
    # Most-recent-first: create_ticket was logged after resize_resource.
    assert a_entries[0]["tool"] == "create_ticket"

    b_entries = mcp_log_service.list_mcp_log("wl-filter-B")
    assert [e["tool"] for e in b_entries] == ["notify_owner"]

    # Unfiltered list includes entries from both workloads.
    all_tools = {e["tool"] for e in mcp_log_service.list_mcp_log()}
    assert {"resize_resource", "create_ticket", "notify_owner"} <= all_tools


# --------------------------------------------------------------------------- #
# 3. GET /api/mcp/log returns a bare list, with and without the filter
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active (creates schema in the temp DB)."""
    with TestClient(app) as c:
        yield c


def test_get_mcp_log_endpoint_returns_bare_list(client):
    registry = ConnectorRegistry(log_invocations=True)
    registry.execute("schedule_shutdown", workload_id="wl-api-001")
    registry.execute("create_ticket", workload_id="wl-api-002")

    resp = client.get("/api/mcp/log")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    # data is a BARE LIST (not wrapped in {entries, count}).
    assert isinstance(body["data"], list)
    tools = {e["tool"] for e in body["data"]}
    assert {"schedule_shutdown", "create_ticket"} <= tools
    # Each entry matches the MCPLogEntry shape.
    sample = body["data"][0]
    assert set(sample.keys()) >= {
        "timestamp",
        "workload_id",
        "category",
        "tool",
        "params",
        "result",
        "policy_compliance",
        "remediation_id",
    }


def test_get_mcp_log_endpoint_filters_by_workload(client):
    registry = ConnectorRegistry(log_invocations=True)
    registry.execute("enable_monitoring", workload_id="wl-api-filter")

    resp = client.get("/api/mcp/log", params={"workload_id": "wl-api-filter"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)
    assert len(data) >= 1
    assert all(e["workload_id"] == "wl-api-filter" for e in data)
    assert any(e["tool"] == "enable_monitoring" for e in data)
