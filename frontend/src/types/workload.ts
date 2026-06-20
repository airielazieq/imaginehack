// Mirrors backend/schemas/workload.py and telemetry.py.

export type CloudServiceType =
  | 'vm'
  | 'container'
  | 'database'
  | 'storage'
  | 'serverless'
  | 'pipeline'

export type Environment = 'production' | 'staging' | 'testing' | 'development'

export type WorkflowCriticality = 'critical' | 'high' | 'medium' | 'low'

export type WorkloadStatus = 'healthy' | 'warning' | 'critical' | 'unreachable'

// One of 9 predefined construction workflows (see 03_DATA_MODEL.md).
export type ConstructionWorkflow =
  | 'field_worker_mobile_app'
  | 'project_management_dashboard'
  | 'iot_equipment_monitoring'
  | 'bim_model_data_processing'
  | 'site_safety_analytics'
  | 'reporting_worker'
  | 'customer_order_platform'
  | 'construction_document_management'
  | 'site_progress_tracking_system'

/** Canonical workload entity that drives the entire pipeline. */
export interface Workload {
  workload_id: string
  workload_name: string
  workload_type: string
  cloud_service_type: CloudServiceType
  environment: Environment
  region: string
  owner_team: string
  construction_workflow: ConstructionWorkflow
  workflow_criticality: WorkflowCriticality
  status: WorkloadStatus
}

export type VulnerabilitySeverity = 'none' | 'low' | 'medium' | 'high' | 'critical'

/** A single point-in-time telemetry reading for a workload. */
export interface TelemetrySnapshot {
  workload_id: string

  // Utilization percentages [0, 100].
  cpu_usage_percent: number
  memory_usage_percent: number

  // Resource / activity counters (>= 0).
  storage_gb: number
  runtime_hours_24h: number
  request_count_24h: number

  // Performance.
  error_rate_percent: number
  latency_ms: number

  // Security posture.
  public_exposure: boolean
  public_storage: boolean
  vulnerability_severity: VulnerabilitySeverity
  critical_vulnerability_count: number
  access_anomaly_detected: boolean
  monitoring_enabled: boolean

  // Cost [0, 999999.99].
  cost_per_hour: number
  cost_24h: number
  cost_30d_forecast: number

  // GreenOps.
  energy_kwh_24h: number
  carbon_kgco2e_24h: number
  carbon_intensity_gco2_per_kwh: number

  timestamp: string
}
