"""Simulated cloud infrastructure connector.

Covers the cloud-side MCP tools referenced by ``rules/recommendation_rules.json``
and the runbooks in spec ``06_GUARDRAILED_SELF_HEALING_SDD``: restart, scale,
stop/start, resize, schedule shutdown, restrict public access, update storage
ACL, pull container image, enable monitoring, and reschedule batch jobs.

None of these touch real infrastructure. Each tool returns a deterministic,
JSON-serializable description of the simulated state change which the runbook
executor and report generator (tasks 5.3 / 5.5) surface to operators.
"""

from __future__ import annotations

from typing import Any

from backend.connectors.mcp_base import MCPConnector


class CloudConnector(MCPConnector):
    """Simulated infrastructure-operations connector (no real cloud calls)."""

    category = "cloud"

    # -- Lifecycle / compute --------------------------------------------------
    def _tool_restart(self, workload_id: str | None = None, **params: Any) -> dict:
        return {
            "action": "restart",
            "workload_id": workload_id,
            "previous_state": "running",
            "new_state": "running",
            "note": "Workload restarted (simulated).",
            **params,
        }

    def _tool_restart_container(
        self, workload_id: str | None = None, **params: Any
    ) -> dict:
        return {
            "action": "restart_container",
            "workload_id": workload_id,
            "previous_state": "running",
            "new_state": "running",
            "note": "Container restarted (simulated).",
            **params,
        }

    def _tool_stop(self, workload_id: str | None = None, **params: Any) -> dict:
        return {
            "action": "stop",
            "workload_id": workload_id,
            "previous_state": "running",
            "new_state": "stopped",
            "note": "Workload stopped (simulated).",
            **params,
        }

    def _tool_start(self, workload_id: str | None = None, **params: Any) -> dict:
        return {
            "action": "start",
            "workload_id": workload_id,
            "previous_state": "stopped",
            "new_state": "running",
            "note": "Workload started (simulated).",
            **params,
        }

    # -- Scaling / sizing -----------------------------------------------------
    def _tool_scale(
        self,
        workload_id: str | None = None,
        replicas: int | None = None,
        **params: Any,
    ) -> dict:
        return {
            "action": "scale",
            "workload_id": workload_id,
            "target_replicas": replicas,
            "new_state": "scaled",
            "note": "Workload scaled (simulated).",
            **params,
        }

    def _tool_resize_resource(
        self,
        workload_id: str | None = None,
        target_size: str | None = None,
        **params: Any,
    ) -> dict:
        return {
            "action": "resize_resource",
            "workload_id": workload_id,
            "previous_size": params.pop("current_size", "unknown"),
            "target_size": target_size or "smaller_tier",
            "new_state": "resized",
            "note": "Resource resized to a smaller tier (simulated).",
            **params,
        }

    # -- Scheduling -----------------------------------------------------------
    def _tool_schedule_shutdown(
        self,
        workload_id: str | None = None,
        window: str | None = None,
        **params: Any,
    ) -> dict:
        return {
            "action": "schedule_shutdown",
            "workload_id": workload_id,
            "shutdown_window": window or "idle_hours",
            "new_state": "shutdown_scheduled",
            "note": "Idle-window shutdown scheduled (simulated).",
            **params,
        }

    def _tool_reschedule_batch_job(
        self,
        workload_id: str | None = None,
        target_window: str | None = None,
        **params: Any,
    ) -> dict:
        return {
            "action": "reschedule_batch_job",
            "workload_id": workload_id,
            "target_window": target_window or "low_carbon_window",
            "new_state": "rescheduled",
            "note": "Batch job rescheduled to a low-carbon window (simulated).",
            **params,
        }

    # -- Security / access ----------------------------------------------------
    def _tool_restrict_public_access(
        self, workload_id: str | None = None, **params: Any
    ) -> dict:
        return {
            "action": "restrict_public_access",
            "workload_id": workload_id,
            "previous_exposure": "public",
            "new_exposure": "private",
            "new_state": "access_restricted",
            "note": "Public access restricted (simulated).",
            **params,
        }

    def _tool_update_storage_acl(
        self,
        workload_id: str | None = None,
        acl: str | None = None,
        **params: Any,
    ) -> dict:
        return {
            "action": "update_storage_acl",
            "workload_id": workload_id,
            "previous_acl": "public-read",
            "new_acl": acl or "private",
            "new_state": "acl_updated",
            "note": "Storage ACL tightened (simulated).",
            **params,
        }

    def _tool_pull_container_image(
        self,
        workload_id: str | None = None,
        image: str | None = None,
        **params: Any,
    ) -> dict:
        return {
            "action": "pull_container_image",
            "workload_id": workload_id,
            "image": image or "patched:latest",
            "new_state": "image_pulled",
            "note": "Patched container image pulled (simulated).",
            **params,
        }

    # -- Observability --------------------------------------------------------
    def _tool_enable_monitoring(
        self, workload_id: str | None = None, **params: Any
    ) -> dict:
        return {
            "action": "enable_monitoring",
            "workload_id": workload_id,
            "previous_state": "monitoring_disabled",
            "new_state": "monitoring_enabled",
            "note": "Baseline monitoring enabled (simulated).",
            **params,
        }
