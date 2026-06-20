"""Simulated MCP connectors for the Guardrailed Self-Healing module.

These connectors never touch real cloud infrastructure. Each exposes a set of
tools (discoverable via ``get_available_tools``) and returns an
:class:`~backend.schemas.remediation.MCPToolExecution` for every invocation, so
runbook execution (task 5.3) and reporting (task 5.5) can compose them
uniformly.
"""

from __future__ import annotations

import logging

from backend.connectors.audit_connector import AuditConnector, build_audit_log
from backend.connectors.cloud_connector import CloudConnector
from backend.connectors.mcp_base import MCPConnector
from backend.connectors.notification_connector import NotificationConnector
from backend.connectors.ticketing_connector import TicketingConnector
from backend.schemas.remediation import MCPToolExecution

logger = logging.getLogger("clover.connectors")


def default_connectors(
    *, persist_audit: bool = False, db_path: str | None = None
) -> dict[str, MCPConnector]:
    """Return a fresh set of connectors keyed by category.

    Convenience factory for the runbook executor and report generator so they
    can resolve the right connector for a given MCP tool.
    """
    return {
        "cloud": CloudConnector(),
        "ticketing": TicketingConnector(),
        "notification": NotificationConnector(),
        "audit": AuditConnector(persist=persist_audit, db_path=db_path),
    }


class ConnectorRegistry:
    """Tool-name → connector dispatch layer for the runbook executor.

    The safety router (task 5.1) decides *whether* an action may run; this
    registry decides *which* simulated connector actually performs each MCP
    tool. The runbook executor (task 5.3) holds a single registry and calls
    :meth:`execute` for every tool in a runbook without needing to know which
    connector category owns it.

    A flat ``tool_name -> MCPConnector`` index is built from each connector's
    :meth:`~backend.connectors.mcp_base.MCPConnector.get_available_tools`. When
    two connectors expose the same tool name, the first one registered wins and
    a :class:`ValueError` is raised so collisions surface loudly rather than
    silently shadowing a tool.
    """

    def __init__(
        self,
        connectors: dict[str, MCPConnector] | None = None,
        *,
        log_invocations: bool = False,
        db_path: str | None = None,
    ) -> None:
        self._connectors: dict[str, MCPConnector] = dict(
            connectors if connectors is not None else default_connectors()
        )
        #: When True, every tool invocation is recorded to the MCP activity log
        #: (best-effort; opt-in so importing/using a registry never requires a DB).
        self.log_invocations = log_invocations
        self.db_path = db_path
        self._tool_index: dict[str, MCPConnector] = {}
        self._reindex()

    # -- Construction ---------------------------------------------------------
    def _reindex(self) -> None:
        """Rebuild the flat tool-name index from the registered connectors."""
        self._tool_index = {}
        for connector in self._connectors.values():
            for tool_name in connector.get_available_tools():
                existing = self._tool_index.get(tool_name)
                if existing is not None and existing is not connector:
                    raise ValueError(
                        f"Tool '{tool_name}' is exposed by both "
                        f"{type(existing).__name__} and "
                        f"{type(connector).__name__}; tool names must be unique "
                        "across connectors."
                    )
                self._tool_index[tool_name] = connector

    @classmethod
    def with_defaults(
        cls,
        *,
        persist_audit: bool = False,
        log_invocations: bool = False,
        db_path: str | None = None,
    ) -> "ConnectorRegistry":
        """Build a registry from the default connector set."""
        return cls(
            default_connectors(persist_audit=persist_audit, db_path=db_path),
            log_invocations=log_invocations,
            db_path=db_path,
        )

    # -- Lookup ---------------------------------------------------------------
    def connector_for(self, tool_name: str) -> MCPConnector | None:
        """Return the connector that handles ``tool_name`` (or ``None``)."""
        return self._tool_index.get(tool_name)

    def supports(self, tool_name: str) -> bool:
        """Return ``True`` if any registered connector handles ``tool_name``."""
        return tool_name in self._tool_index

    def available_tools(self) -> list[str]:
        """Return the sorted list of every tool name the registry can dispatch."""
        return sorted(self._tool_index)

    @property
    def connectors(self) -> dict[str, MCPConnector]:
        """The registered connectors keyed by category."""
        return dict(self._connectors)

    # -- Dispatch -------------------------------------------------------------
    def execute(self, tool_name: str, **params: object) -> MCPToolExecution:
        """Dispatch ``tool_name`` to its connector and return the execution.

        Unknown tools are handled gracefully: instead of raising, a ``failed``
        :class:`MCPToolExecution` is returned describing the unknown tool and
        listing every tool the registry *can* dispatch, mirroring the per-
        connector behavior so the runbook executor sees a uniform contract.
        """
        connector = self._tool_index.get(tool_name)
        if connector is None:
            execution = MCPToolExecution(
                tool=tool_name,
                category="registry",
                input=dict(params),
                output={
                    "error": "unknown_tool",
                    "message": (
                        f"No registered connector handles tool '{tool_name}'."
                    ),
                    "available_tools": self.available_tools(),
                },
                duration_ms=1,
                status="failed",
            )
        else:
            execution = connector.execute_tool(tool_name, **params)

        self._record_invocation(execution, params)
        return execution

    # -- Activity log ---------------------------------------------------------
    def _record_invocation(
        self, execution: MCPToolExecution, params: dict[str, object]
    ) -> None:
        """Record a tool invocation to the MCP activity log (best-effort).

        Centralizes logging at the single dispatch chokepoint so *every* tool
        call (cloud, ticketing, notification, audit) is captured uniformly.
        Opt-in via :attr:`log_invocations`; wrapped so a logging failure never
        propagates into tool execution. The ``workload_id`` / ``remediation_id``
        / ``policy_compliance`` are taken from the call params when available
        (``None``/default otherwise).
        """
        if not self.log_invocations:
            return
        try:
            from backend.services import mcp_log_service

            mcp_log_service.record_invocation(
                tool=execution.tool,
                category=execution.category,
                params=execution.input,
                result=execution.output,
                status=execution.status,
                workload_id=params.get("workload_id"),  # type: ignore[arg-type]
                remediation_id=params.get("remediation_id"),  # type: ignore[arg-type]
                policy_compliance=params.get("policy_compliance"),  # type: ignore[arg-type]
                db_path=self.db_path,
            )
        except Exception:  # noqa: BLE001 - logging must never break execution
            logger.debug(
                "Failed to record MCP invocation for %r", execution.tool, exc_info=True
            )


__all__ = [
    "MCPConnector",
    "CloudConnector",
    "TicketingConnector",
    "NotificationConnector",
    "AuditConnector",
    "ConnectorRegistry",
    "build_audit_log",
    "default_connectors",
]
