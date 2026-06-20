"""Pydantic schemas for the canonical Workload entity."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CloudServiceType = Literal[
    "vm", "container", "database", "storage", "serverless", "pipeline"
]
Environment = Literal["production", "staging", "testing", "development"]
WorkflowCriticality = Literal["critical", "high", "medium", "low"]
WorkloadStatus = Literal["healthy", "warning", "critical", "unreachable"]

# One of 9 predefined construction workflows (see 03_DATA_MODEL.md).
ConstructionWorkflow = Literal[
    "field_worker_mobile_app",
    "project_management_dashboard",
    "iot_equipment_monitoring",
    "bim_model_data_processing",
    "site_safety_analytics",
    "reporting_worker",
    "customer_order_platform",
    "construction_document_management",
    "site_progress_tracking_system",
]


class Workload(BaseModel):
    """Canonical workload entity that drives the entire pipeline."""

    workload_id: str = Field(..., description="e.g. 'wl-bim-processor-001'")
    workload_name: str
    workload_type: str = Field(..., description="Business type")
    cloud_service_type: CloudServiceType
    environment: Environment
    region: str
    owner_team: str
    construction_workflow: ConstructionWorkflow
    workflow_criticality: WorkflowCriticality
    status: WorkloadStatus
