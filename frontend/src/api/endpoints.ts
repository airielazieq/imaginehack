// Typed API functions for the full Clover backend contract (see spec 10).
//
// Each function returns the typed data model with the success envelope already
// unwrapped by the client interceptor. Endpoints not yet implemented on the
// backend are defined here so pages can be built against the full contract.

import { get, patch, post } from './client'
import type {
  Alert,
  AuditLog,
  DimensionScores,
  DowntimePrediction,
  ForecastComponent,
  Issue,
  IssueStatus,
  PriorityScore,
  Recommendation,
  RemediationResult,
  TelemetrySnapshot,
  Workload,
} from '../types'

/* ------------------------------------------------------------------ *
 * Response shapes not in the shared types (dashboard / mock / misc).  *
 * ------------------------------------------------------------------ */

/** Stat-card summary for the dashboard landing page. */
export interface DashboardSummary {
  total_workloads: number
  active_issues: number
  critical_issues: number
  pending_approvals: number
  self_healing_actions: number
  critical_workloads: number
  avg_security_score: number
  avg_energy_score: number
  monthly_cost: number
  projected_monthly_savings: number
  projected_carbon_reduction: number
}

/** One composite-grid cell: a workload's Priority Score + quick context. */
export interface CompositeHeatmapCell {
  workload_id: string
  workload_name: string
  score: number
  status: string
  top_alert: string | null
  downtime_risk: number | null
}

/** Projected savings summary across cost / energy / carbon. */
export interface SavingsSummary {
  forecast_without_action: ForecastComponent
  forecast_after_action: ForecastComponent
  projected_savings: ForecastComponent
}

/** A recent remediation entry for the dashboard "recent actions" feed. */
export interface RecentAction {
  remediation_id: string
  workload_id: string
  workload_name: string
  action_taken: string
  execution_path: string
  execution_status: string
  timestamp: string
}

/** A single MCP tool invocation log entry. */
export interface MCPLogEntry {
  timestamp: string
  workload_id: string
  category: string
  tool: string
  params: Record<string, unknown>
  result: Record<string, unknown>
  policy_compliance: string
  remediation_id: string | null
}

/** A demo scenario exposed by the mock controller. */
export interface MockScenario {
  scenario_id: string
  name: string
  description: string
  target_workloads: string[]
  expected_path: string
}

/** Current state of the mock telemetry stream. */
export interface MockStatus {
  streaming: boolean
  interval_seconds: number | null
  last_emitted_at: string | null
}

/** One 90-day uptime segment for a workload. */
export interface UptimeSegment {
  date: string
  uptime_percent: number
  status: string
}

/* ------------------------------------------------------------------ *
 * 1. Telemetry & workloads                                            *
 * ------------------------------------------------------------------ */

export const ingestTelemetry = (snapshot: TelemetrySnapshot) =>
  post<TelemetrySnapshot>('/telemetry/ingest', snapshot)

export const bulkIngestTelemetry = (snapshots: TelemetrySnapshot[]) =>
  post<TelemetrySnapshot[]>('/telemetry/bulk-ingest', snapshots)

export const getWorkloads = () => get<Workload[]>('/workloads')

export const getWorkload = (id: string) => get<Workload>(`/workloads/${id}`)

export const getWorkloadTelemetry = (id: string, limit?: number) =>
  get<TelemetrySnapshot[]>(`/workloads/${id}/telemetry`, limit ? { limit } : undefined)

export const getWorkloadUptime = (id: string) =>
  get<UptimeSegment[]>(`/workloads/${id}/uptime`)

export const getWorkloadPrediction = (id: string) =>
  get<DowntimePrediction>(`/workloads/${id}/prediction`)

/* ------------------------------------------------------------------ *
 * 2. Detection / Issues                                               *
 * ------------------------------------------------------------------ */

export const runDetection = (workloadId?: string) =>
  post<Issue[]>(workloadId ? `/detection/run/${workloadId}` : '/detection/run')

export interface IssueFilters {
  severity?: string
  category?: string
  environment?: string
  status?: string
  owner_team?: string
}

export const getIssues = (filters?: IssueFilters) =>
  get<Issue[]>('/issues', filters as Record<string, unknown> | undefined)

export const getIssue = (id: string) => get<Issue>(`/issues/${id}`)

export const updateIssueStatus = (id: string, status: IssueStatus) =>
  patch<Issue>(`/issues/${id}/status`, { status })

/* ------------------------------------------------------------------ *
 * 3. Recommendations / Forecast                                       *
 * ------------------------------------------------------------------ */

export const generateRecommendation = (issueId: string) =>
  post<Recommendation>(`/recommendations/generate/${issueId}`)

export const getRecommendation = (id: string) =>
  get<Recommendation>(`/recommendations/${id}`)

export const runForecast = (workloadId: string) =>
  post<Recommendation['forecast_model_result']>(`/forecast/${workloadId}`)

/* ------------------------------------------------------------------ *
 * 4. Remediation / Approvals                                          *
 * ------------------------------------------------------------------ */

export const evaluateRemediation = (recommendationId: string) =>
  post<RemediationResult>(`/remediation/evaluate/${recommendationId}`)

export const executeRemediation = (recommendationId: string) =>
  post<RemediationResult>(`/remediation/execute/${recommendationId}`)

export const getRemediationReport = (id: string) =>
  get<RemediationResult>(`/remediation/${id}/report`)

export const getApprovals = () => get<Recommendation[]>('/approvals')

export const approveRecommendation = (id: string, selectedTools?: string[]) =>
  post<RemediationResult>(`/approvals/${id}/approve`, { selected_tools: selectedTools ?? [] })

export const denyApproval = (id: string, reason?: string) =>
  post<Recommendation>(`/approvals/${id}/deny`, { reason })

export const snoozeApproval = (id: string, minutes?: number) =>
  post<Recommendation>(`/approvals/${id}/snooze`, { minutes })

/* ------------------------------------------------------------------ *
 * 5. Scoring / Alerts / MCP log / Audit                               *
 * ------------------------------------------------------------------ */

export const getScoringIssues = () => get<PriorityScore[]>('/scoring/issues')

export const getAlerts = (workloadId?: string) =>
  get<Alert[]>('/alerts', workloadId ? { workload_id: workloadId } : undefined)

export const getMCPLog = (workloadId?: string) =>
  get<MCPLogEntry[]>('/mcp/log', workloadId ? { workload_id: workloadId } : undefined)

export interface AuditLogFilters {
  workload_id?: string
  event_type?: string
  start_date?: string
  end_date?: string
}

export const getAuditLogs = (filters?: AuditLogFilters) =>
  get<AuditLog[]>('/audit-logs', filters as Record<string, unknown> | undefined)

export const getAuditLog = (id: string) => get<AuditLog>(`/audit-logs/${id}`)

export const getIssueAuditLogs = (issueId: string) =>
  get<AuditLog[]>(`/issues/${issueId}/audit-logs`)

/* ------------------------------------------------------------------ *
 * 6. Dashboard                                                        *
 * ------------------------------------------------------------------ */

export const getDashboardSummary = () => get<DashboardSummary>('/dashboard/summary')

export const getCompositeHeatmap = () =>
  get<CompositeHeatmapCell[]>('/dashboard/heatmap/composite')

export const getMatrixHeatmap = () =>
  get<DimensionScores[]>('/dashboard/heatmap/matrix')

export const getSavingsSummary = () => get<SavingsSummary>('/dashboard/savings')

export const getRecentActions = () => get<RecentAction[]>('/dashboard/recent-actions')

/* ------------------------------------------------------------------ *
 * 7. Mock controller                                                  *
 * ------------------------------------------------------------------ */

export const getMockScenarios = () => get<MockScenario[]>('/mock/scenarios')

export const triggerMockScenario = (scenarioId: string) =>
  post<{ scenario_id: string; triggered: boolean }>(`/mock/trigger/${scenarioId}`)

export const resetMock = () => post<{ reset: boolean }>('/mock/reset')

export const startMockStream = () =>
  post<MockStatus>('/mock/stream/start')

export const stopMockStream = () => post<MockStatus>('/mock/stream/stop')

export const getMockStatus = () => get<MockStatus>('/mock/status')

/* ------------------------------------------------------------------ *
 * Health                                                              *
 * ------------------------------------------------------------------ */

export const getHealth = () => get<{ status: string }>('/health')
