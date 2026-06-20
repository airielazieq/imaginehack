"""Base interface for simulated MCP (Model Context Protocol) connectors.

Module 3 (Guardrailed Self-Healing) never touches real cloud infrastructure.
Instead, every remediation action is routed through a *simulated* MCP connector
that:

* updates an in-memory view of system state,
* produces a structured, auditable record of what "happened", and
* returns it as an :class:`~backend.schemas.remediation.MCPToolExecution`.

This module defines :class:`MCPConnector`, the common base class. Concrete
connectors (cloud, ticketing, notification, audit) declare their tools by
implementing methods named ``_tool_<tool_name>`` that accept keyword params and
return an ``output`` ``dict``. The base class handles:

* tool discovery (:meth:`get_available_tools`),
* dispatch + error handling (:meth:`execute_tool`),
* deterministic simulated durations (no real sleeps, so tests stay fast),
* graceful handling of unknown tools (a ``failed`` execution record).

The simulation is intentionally deterministic: a given tool name always yields
the same simulated ``duration_ms`` so reports and tests are reproducible.
"""

from __future__ import annotations

import inspect
from abc import ABC
from typing import Any, Callable

from backend.schemas.remediation import MCPToolExecution

# Methods that implement a tool are named with this prefix, e.g. ``_tool_stop``.
_TOOL_PREFIX = "_tool_"


class MCPConnector(ABC):
    """Abstract base for all simulated MCP connectors.

    Subclasses set :attr:`category` and define one method per tool using the
    ``_tool_<name>`` naming convention. Each tool method receives the call
    params as keyword arguments and returns a JSON-serializable ``dict`` that
    becomes the execution ``output``.

    A tool may signal a simulated failure by returning a dict whose ``status``
    key equals ``"failed"`` (the marker is reflected in the resulting
    :class:`MCPToolExecution.status`).
    """

    #: Logical category recorded on every :class:`MCPToolExecution`.
    category: str = "generic"

    # Bounds for the deterministic simulated execution time (milliseconds).
    _MIN_DURATION_MS: int = 20
    _MAX_DURATION_MS: int = 400

    # -- Tool discovery -------------------------------------------------------
    def get_available_tools(self) -> list[str]:
        """Return the sorted list of tool names this connector exposes."""
        tools: list[str] = []
        for name, member in inspect.getmembers(self, predicate=callable):
            if name.startswith(_TOOL_PREFIX) and len(name) > len(_TOOL_PREFIX):
                tools.append(name[len(_TOOL_PREFIX):])
        return sorted(tools)

    def supports(self, tool_name: str) -> bool:
        """Return ``True`` if ``tool_name`` is implemented by this connector."""
        handler = getattr(self, f"{_TOOL_PREFIX}{tool_name}", None)
        return callable(handler)

    # -- Simulation helpers ---------------------------------------------------
    def _simulated_duration_ms(self, tool_name: str) -> int:
        """Deterministically derive a small simulated duration for a tool.

        The value is stable for a given tool name (so reports/tests are
        reproducible) and always lies within
        ``[_MIN_DURATION_MS, _MAX_DURATION_MS]``.
        """
        span = self._MAX_DURATION_MS - self._MIN_DURATION_MS
        seed = sum(ord(ch) for ch in tool_name) if tool_name else 0
        return self._MIN_DURATION_MS + (seed % (span + 1))

    # -- Dispatch -------------------------------------------------------------
    def execute_tool(self, tool_name: str, **params: Any) -> MCPToolExecution:
        """Execute a simulated tool and return a structured execution record.

        Unknown tools and tools that raise are handled gracefully: the returned
        :class:`MCPToolExecution` carries ``status="failed"`` and an explanatory
        ``output`` payload rather than propagating an exception.
        """
        duration = self._simulated_duration_ms(tool_name)
        handler: Callable[..., dict] | None = getattr(
            self, f"{_TOOL_PREFIX}{tool_name}", None
        )

        if not callable(handler):
            return MCPToolExecution(
                tool=tool_name,
                category=self.category,
                input=dict(params),
                output={
                    "error": "unknown_tool",
                    "message": (
                        f"Tool '{tool_name}' is not supported by "
                        f"{type(self).__name__}."
                    ),
                    "available_tools": self.get_available_tools(),
                },
                duration_ms=duration,
                status="failed",
            )

        try:
            output = handler(**params)
        except TypeError as exc:
            # Most commonly a bad/missing parameter for the tool.
            return MCPToolExecution(
                tool=tool_name,
                category=self.category,
                input=dict(params),
                output={"error": "invalid_parameters", "message": str(exc)},
                duration_ms=duration,
                status="failed",
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            return MCPToolExecution(
                tool=tool_name,
                category=self.category,
                input=dict(params),
                output={"error": "execution_error", "message": str(exc)},
                duration_ms=duration,
                status="failed",
            )

        if not isinstance(output, dict):
            output = {"result": output}

        status = "failed" if output.get("status") == "failed" else "success"
        return MCPToolExecution(
            tool=tool_name,
            category=self.category,
            input=dict(params),
            output=output,
            duration_ms=duration,
            status=status,
        )
