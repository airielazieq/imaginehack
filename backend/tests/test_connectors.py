"""Tests for the simulated MCP connectors (task 5.2).

Covers Requirements 8.1 (auto-fix runbooks execute via the appropriate
MCP_Connector), 10.1 (escalation creates a ticket via the ticketing connector),
and 10.2 (escalation notifies owner/security teams via the notification
connector).

Verifies that every connector:
* advertises its tools via ``get_available_tools``,
* returns a valid ``MCPToolExecution`` (status/duration/input/output) for
  representative tools, and
* handles unknown tools gracefully (``failed`` status, no exception).
"""

from __future__ import annotations

import json

import pytest

from backend.connectors import (
    AuditConnector,
    CloudConnector,
    ConnectorRegistry,
    NotificationConnector,
    TicketingConnector,
    default_connectors,
)
from backend.core.config import load_policy
from backend.schemas.remediation import MCPToolExecution

# Cloud tools referenced by recommendation_rules.json + spec 06 runbooks.
_EXPECTED_CLOUD_TOOLS = {
    "restart",
    "stop",
    "start",
    "scale",
    "resize_resource",
    "schedule_shutdown",
    "restrict_public_access",
    "update_storage_acl",
    "pull_container_image",
    "enable_monitoring",
    "reschedule_batch_job",
}


def _assert_valid_execution(
    execution: MCPToolExecution, *, expected_tool: str, expected_category: str
) -> None:
    assert isinstance(execution, MCPToolExecution)
    assert execution.tool == expected_tool
    assert execution.category == expected_category
    assert execution.status in {"success", "failed", "skipped"}
    assert isinstance(execution.input, dict)
    assert isinstance(execution.output, dict)
    assert isinstance(execution.duration_ms, int)
    assert execution.duration_ms > 0
    # Must be JSON-serializable for persistence/reporting.
    json.dumps(execution.model_dump(mode="json"))


# --- Tool discovery ----------------------------------------------------------
def test_cloud_connector_exposes_expected_tools():
    tools = set(CloudConnector().get_available_tools())
    assert _EXPECTED_CLOUD_TOOLS.issubset(tools)


def test_ticketing_connector_exposes_create_ticket():
    assert "create_ticket" in TicketingConnector().get_available_tools()


def test_notification_connector_exposes_notify_tools():
    tools = set(NotificationConnector().get_available_tools())
    assert {"notify_owner", "notify_security_team", "notify_devops_team"}.issubset(tools)


def test_audit_connector_exposes_write_audit_log():
    assert "write_audit_log" in AuditConnector().get_available_tools()


def test_default_connectors_cover_all_categories():
    connectors = default_connectors()
    assert set(connectors) == {"cloud", "ticketing", "notification", "audit"}
    for category, connector in connectors.items():
        assert connector.category == category
        assert connector.get_available_tools()  # non-empty


# --- Cloud connector representative tools (Req 8.1) --------------------------
@pytest.mark.parametrize("tool", sorted(_EXPECTED_CLOUD_TOOLS))
def test_cloud_tools_return_successful_execution(tool):
    execution = CloudConnector().execute_tool(tool, workload_id="wl-test-001")
    _assert_valid_execution(execution, expected_tool=tool, expected_category="cloud")
    assert execution.status == "success"
    assert execution.input["workload_id"] == "wl-test-001"
    assert execution.output  # non-empty simulated state change


# --- Ticketing connector (Req 10.1) -----------------------------------------
def test_create_ticket_returns_ticket_id():
    execution = TicketingConnector().execute_tool(
        "create_ticket",
        workload_id="wl-site-db-001",
        title="Critical vuln escalation",
        priority="critical",
    )
    _assert_valid_execution(
        execution, expected_tool="create_ticket", expected_category="ticketing"
    )
    assert execution.status == "success"
    ticket_id = execution.output["ticket_id"]
    assert isinstance(ticket_id, str) and ticket_id.startswith("TICKET-")


def test_create_ticket_ids_are_unique():
    connector = TicketingConnector()
    first = connector.execute_tool("create_ticket", workload_id="wl-1")
    second = connector.execute_tool("create_ticket", workload_id="wl-2")
    assert first.output["ticket_id"] != second.output["ticket_id"]


# --- Notification connector (Req 10.2) --------------------------------------
@pytest.mark.parametrize(
    "tool,expected_recipient",
    [
        ("notify_owner", "platform-team"),
        ("notify_security_team", "security_team"),
        ("notify_devops_team", "devops_team"),
    ],
)
def test_notification_tools_return_delivery_record(tool, expected_recipient):
    kwargs = {"workload_id": "wl-test-001", "message": "please review"}
    if tool == "notify_owner":
        kwargs["owner_team"] = "platform-team"

    execution = NotificationConnector().execute_tool(tool, **kwargs)
    _assert_valid_execution(
        execution, expected_tool=tool, expected_category="notification"
    )
    assert execution.status == "success"
    assert execution.output["recipient"] == expected_recipient
    assert execution.output["delivery_status"] == "delivered"
    assert execution.output["delivery_id"].startswith("NOTIF-")


# --- Audit connector ---------------------------------------------------------
def test_audit_write_without_persistence_produces_record():
    execution = AuditConnector().execute_tool(
        "write_audit_log",
        event_type="remediation_completed",
        workload_id="wl-test-001",
        actor="auto_fix",
        new_status="remediated",
    )
    _assert_valid_execution(
        execution, expected_tool="write_audit_log", expected_category="audit"
    )
    assert execution.status == "success"
    assert execution.output["persisted"] is False
    assert execution.output["audit_id"].startswith("AUDIT-")
    assert execution.output["audit_log"]["event_type"] == "remediation_completed"


def test_audit_write_with_persistence_writes_to_db(tmp_path):
    db_path = str(tmp_path / "audit_test.db")
    connector = AuditConnector(persist=True, db_path=db_path)
    execution = connector.execute_tool(
        "write_audit_log",
        event_type="auto_fix_executed",
        workload_id="wl-test-001",
    )
    assert execution.status == "success"
    assert execution.output["persisted"] is True

    # Confirm the row was actually written.
    from backend.core.database import connection

    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT event_type, workload_id FROM audit_logs WHERE audit_id = ?",
            (execution.output["audit_id"],),
        ).fetchone()
    assert row is not None
    assert row["event_type"] == "auto_fix_executed"
    assert row["workload_id"] == "wl-test-001"


# --- Unknown tool handling ---------------------------------------------------
@pytest.mark.parametrize(
    "connector",
    [
        CloudConnector(),
        TicketingConnector(),
        NotificationConnector(),
        AuditConnector(),
    ],
)
def test_unknown_tool_is_handled_gracefully(connector):
    execution = connector.execute_tool("does_not_exist", foo="bar")
    assert execution.status == "failed"
    assert execution.tool == "does_not_exist"
    assert execution.input == {"foo": "bar"}
    assert execution.output["error"] == "unknown_tool"
    assert "available_tools" in execution.output


def test_deterministic_duration_for_same_tool():
    connector = CloudConnector()
    first = connector.execute_tool("restart", workload_id="wl-1")
    second = connector.execute_tool("restart", workload_id="wl-2")
    assert first.duration_ms == second.duration_ms


# --- ConnectorRegistry dispatch (task 5.2) ----------------------------------
def _rule_mcp_tools() -> set[str]:
    """Every distinct mcp_tool referenced by recommendation_rules.json."""
    policy = load_policy("recommendation_rules")
    tools: set[str] = set()
    for rule in policy["rules"]:
        tools.update(rule.get("mcp_tools", []))
    return tools


def test_registry_dispatches_every_recommendation_rule_tool():
    """Every mcp_tool in recommendation_rules.json resolves to a connector
    and executes successfully via the registry (Req 8.1)."""
    registry = ConnectorRegistry()
    rule_tools = _rule_mcp_tools()
    assert rule_tools  # guard: rules actually declare tools

    for tool in sorted(rule_tools):
        assert registry.supports(tool), f"no connector handles '{tool}'"
        connector = registry.connector_for(tool)
        assert connector is not None
        execution = registry.execute(tool, workload_id="wl-test-001")
        assert isinstance(execution, MCPToolExecution)
        assert execution.tool == tool
        assert execution.status == "success", (
            f"tool '{tool}' dispatched to {type(connector).__name__} "
            f"returned {execution.status}"
        )
        assert execution.category == connector.category


def test_registry_index_covers_union_of_connector_tools():
    registry = ConnectorRegistry()
    expected: set[str] = set()
    for connector in default_connectors().values():
        expected.update(connector.get_available_tools())
    assert set(registry.available_tools()) == expected


def test_registry_routes_tool_to_correct_category():
    registry = ConnectorRegistry()
    assert registry.connector_for("restrict_public_access").category == "cloud"
    assert registry.connector_for("create_ticket").category == "ticketing"
    assert registry.connector_for("notify_security_team").category == "notification"
    assert registry.connector_for("write_audit_log").category == "audit"


def test_registry_unknown_tool_is_handled_gracefully():
    registry = ConnectorRegistry()
    assert registry.supports("does_not_exist") is False
    assert registry.connector_for("does_not_exist") is None

    execution = registry.execute("does_not_exist", foo="bar")
    assert isinstance(execution, MCPToolExecution)
    assert execution.status == "failed"
    assert execution.tool == "does_not_exist"
    assert execution.input == {"foo": "bar"}
    assert execution.output["error"] == "unknown_tool"
    assert "available_tools" in execution.output


def test_registry_raises_on_tool_name_collision():
    class _DupeCloud(CloudConnector):
        category = "cloud_dupe"

    with pytest.raises(ValueError, match="unique"):
        ConnectorRegistry({"cloud": CloudConnector(), "dupe": _DupeCloud()})


def test_registry_with_defaults_persists_audit(tmp_path):
    db_path = str(tmp_path / "registry_audit.db")
    registry = ConnectorRegistry.with_defaults(persist_audit=True, db_path=db_path)
    execution = registry.execute(
        "write_audit_log",
        event_type="auto_fix_executed",
        workload_id="wl-test-001",
    )
    assert execution.status == "success"
    assert execution.output["persisted"] is True
