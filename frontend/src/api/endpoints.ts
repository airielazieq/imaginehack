// Typed API functions for the full Clover backend contract (see spec 10).
//
// Each function returns the typed data model with the success envelope already
// unwrapped by the client interceptor. Endpoints not yet implemented on the
// backend are defined here so pages can be built against the full contract.

import { get, patch, post } from './client'
import type {
  Alert,
  ApprovalItem,
  ApprovalsListResponse,
  AuditLog,
  DimensionScores,
  DowntimePrediction,
  ExecutionPath,
  ExecutionStatus,
  Issue,
  IssueStatus,
  PriorityScore,
  Recommendation,
  RemediationResult,
  TelemetrySnapshot,
  VerificationResult,
  Workload,
} from '../types'

/* ------------------------------------------------------------------ *
 * Response shapes not in the shared types (dashboard / mock / misc).  *
 * ------------------------------------------------------------------ */

/**
 * Aggregate 30-day projected savings rollup (matches the backend
 * `projected_savings` block returned by /dashboard/summary and /dashboard/savings).
 */
export interface ProjectedSavings {
  cost_30d: number
  energy_30d_kwh: number
  carbon_30d_kgco2e: number
}

/**
 * Stat-card summary for the dashboard landing page.
 * Mirrors `GET /api/dashboard/summary` (backend/api/dashboard.py).
 */
export interface DashboardSummary {
  total_workloads: number
  active_issues: number
  critical_issues: number
  pending_approvals: number
  open_recommendations: number
  projected_savings: ProjectedSavings
}

/**
 * One composite-grid cell: a workload's Priority Score + full score detail.
 * Mirrors an entry in the `cells` array of `GET /api/dashboard/heatmap/composite`.
 */
export interface CompositeHeatmapCell {
  workload_id: string
  workload_name: string | null
  status: string | null
  construction_workflow?: string | null
  priority_score: number
  score_detail: PriorityScore
}

/** Envelope payload for the composite heatmap endpoint. */
interface CompositeHeatmapResponse {
  cells: CompositeHeatmapCell[]
  count: number
}

/**
 * One matrix-heatmap row: a workload plus its per-dimension scores.
 * Mirrors an entry in the `rows` array of `GET /api/dashboard/heatmap/matrix`.
 */
export interface MatrixHeatmapRow {
  workload_id: string
  workload_name: string | null
  status: string | null
  dimension_scores: DimensionScores
}

/** Envelope payload for the matrix heatmap endpoint. */
interface MatrixHeatmapResponse {
  rows: MatrixHeatmapRow[]
  count: number
}

/**
 * Projected savings rollup across open recommendations.
 * Mirrors `GET /api/dashboard/savings`.
 */
export interface SavingsSummary {
  projected_savings: ProjectedSavings
  recommendation_count: number
}

/** A recent remediation entry for the dashboard "recent actions" feed. */
export interface RecentAction {
  remediation_id: string
  workload_id: string
  issue_id: string | null
  recommendation_id: string | null
  execution_path: ExecutionPath
  execution_status: ExecutionStatus
  verification_result: VerificationResult | null
  rollback_triggered: boolean
}

/** Envelope payload for the recent-actions endpoint. */
interface RecentActionsResponse {
  actions: RecentAction[]
  count: number
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

/**
 * A demo scenario exposed by the mock controller.
 * Mirrors an entry from `mock_data_service.list_scenarios()`
 * (backend/services/mock_data_service.py) — telemetry payload withheld.
 */
export interface MockScenario {
  scenario_id: string
  name: string | null
  description: string | null
  target_workload_id: string | null
  expected_issue_type: string | null
  expected_detection_rule: string | null
  /** Intended self-healing route (e.g. "auto_fix", "human_escalation_required"). */
  expected_execution_path: string | null
}

/** Envelope payload for `GET /api/mock/scenarios` (`{ scenarios, count }`). */
interface MockScenariosResponse {
  scenarios: MockScenario[]
  count: number
}

/**
 * Result of triggering a scenario via `POST /api/mock/trigger/{id}`.
 * Mirrors `mock_data_service.trigger_scenario`.
 */
export interface MockTriggerResult {
  scenario_id: string
  workload_id: string
  telemetry_id: number
  expected_issue_type: string | null
  expected_execution_path: string | null
}

/**
 * Result of `POST /api/mock/reset`. Mirrors `mock_data_service.reset`:
 * the number of healthy snapshots emitted plus per-table cleared counts.
 */
export interface MockResetResult {
  baseline_snapshots: number
  cleared: Record<string, number>
}

/** Result of `POST /api/mock/stream/start`. */
export interface MockStreamStartResult {
  started: boolean
  streaming: boolean
}

/** Result of `POST /api/mock/stream/stop`. */
export interface MockStreamStopResult {
  stopped: boolean
  streaming: boolean
}

/**
 * Current mock controller / stream status from `GET /api/mock/status`.
 * Mirrors `mock_data_service.status()`.
 */
export interface MockStatus {
  streaming: boolean
  triggered_scenarios: string[]
  /** [min, max] emit cadence in seconds for the continuous stream. */
  stream_interval_seconds: [number, number]
}

/** Status of a single daily uptime segment (mirrors backend api/workloads.py). */
export type UptimeStatus = 'up' | 'degraded' | 'down'

/** One daily uptime segment within the 90-day window. */
export interface UptimeSegment {
  date: string
  uptime_percent: number
  status: UptimeStatus
}

/**
 * Full 90-day uptime history payload.
 * Mirrors `GET /api/workloads/{id}/uptime` (backend/api/workloads.py), which
 * returns the segments plus an overall uptime summary — NOT a bare array.
 */
export interface WorkloadUptime {
  workload_id: string
  segments: UptimeSegment[]
  overall_uptime_percent: number
  window_days: number
  count: number
}

/**
 * Envelope payload for the workload telemetry history endpoint.
 * Mirrors `GET /api/workloads/{id}/telemetry` (backend/api/workloads.py).
 */
interface WorkloadTelemetryResponse {
  workload_id: string
  telemetry: TelemetrySnapshot[]
  count: number
}

/* ------------------------------------------------------------------ *
 * 1. Telemetry & workloads                                            *
 * ------------------------------------------------------------------ */

export const ingestTelemetry = (snapshot: TelemetrySnapshot) =>
  post<TelemetrySnapshot>('/telemetry/ingest', snapshot)

export const bulkIngestTelemetry = (snapshots: TelemetrySnapshot[]) =>
  post<TelemetrySnapshot[]>('/telemetry/bulk-ingest', snapshots)

/** Envelope payload for the workloads list endpoint (backend api/workloads.py). */
export interface WorkloadsListResponse {
  workloads: Workload[]
  count: number
}

/**
 * List all workloads. The backend wraps the list in `{ workloads, count }`;
 * we unwrap to the array so callers get `Workload[]`.
 */
export const getWorkloads = async (): Promise<Workload[]> => {
  const res = await get<WorkloadsListResponse>('/workloads')
  return res.workloads
}

export const getWorkload = (id: string) => get<Workload>(`/workloads/${id}`)

/**
 * Telemetry history for a workload, most recent first. The backend wraps the
 * list in `{ workload_id, telemetry, count }`; we unwrap to the array so
 * callers get `TelemetrySnapshot[]`.
 */
export const getWorkloadTelemetry = async (
  id: string,
  limit?: number,
): Promise<TelemetrySnapshot[]> => {
  const res = await get<WorkloadTelemetryResponse>(
    `/workloads/${id}/telemetry`,
    limit ? { limit } : undefined,
  )
  return res.telemetry
}

/**
 * 90-day uptime history for a workload. Returns the full payload (segments plus
 * `overall_uptime_percent` for the summary strip), matching the backend shape.
 */
export const getWorkloadUptime = (id: string) =>
  get<WorkloadUptime>(`/workloads/${id}/uptime`)

export const getWorkloadPrediction = (id: string) =>
  get<DowntimePrediction>(`/workloads/${id}/prediction`)

/* ------------------------------------------------------------------ *
 * 2. Detection / Issues                                               *
 * ------------------------------------------------------------------ */

export const runDetection = (workloadId?: string) =>
  post<Issue[]>(workloadId ? `/detection/run/${workloadId}` : '/detection/run')

/** Query params accepted by GET /api/issues (mirrors backend api/detection.py). */
export interface IssueFilters {
  issue_type?: string
  severity?: string
  issue_category?: string
  status?: string
  workload_id?: string
}

/** Envelope payload for the issues list endpoint. */
export interface IssuesListResponse {
  issues: Issue[]
  count: number
}

/**
 * List issues, optionally filtered. The backend wraps the list in
 * `{ issues, count }`; we unwrap to the array so callers get `Issue[]`.
 */
export const getIssues = async (filters?: IssueFilters): Promise<Issue[]> => {
  const res = await get<IssuesListResponse>(
    '/issues',
    filters as Record<string, unknown> | undefined,
  )
  return res.issues
}

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

export const getApprovals = async (
  includeResolved = false,
): Promise<ApprovalItem[]> => {
  const res = await get<ApprovalsListResponse>(
    '/approvals',
    includeResolved ? { include_resolved: true } : undefined,
  )
  return res.approvals
}

export const approveRecommendation = (id: string, selectedMcpTools?: string[]) =>
  post<ApprovalItem>(`/approvals/${id}/approve`, {
    selected_mcp_tools: selectedMcpTools ?? [],
  })

export const denyApproval = (id: string) =>
  post<ApprovalItem>(`/approvals/${id}/deny`)

export const snoozeApproval = (id: string, minutes?: number) =>
  post<ApprovalItem>(
    `/approvals/${id}/snooze`,
    minutes != null ? { minutes } : undefined,
  )

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

/** Composite heatmap: unwrap the `{ cells, count }` envelope to the cells array. */
export const getCompositeHeatmap = async (): Promise<CompositeHeatmapCell[]> => {
  const res = await get<CompositeHeatmapResponse>('/dashboard/heatmap/composite')
  return res.cells
}

/** Matrix heatmap: unwrap the `{ rows, count }` envelope to the rows array. */
export const getMatrixHeatmap = async (): Promise<MatrixHeatmapRow[]> => {
  const res = await get<MatrixHeatmapResponse>('/dashboard/heatmap/matrix')
  return res.rows
}

export const getSavingsSummary = () => get<SavingsSummary>('/dashboard/savings')

/** Recent actions: unwrap the `{ actions, count }` envelope to the actions array. */
export const getRecentActions = async (): Promise<RecentAction[]> => {
  const res = await get<RecentActionsResponse>('/dashboard/recent-actions')
  return res.actions
}

/* ------------------------------------------------------------------ *
 * 7. Mock controller                                                  *
 * ------------------------------------------------------------------ */

/** List demo scenarios: unwrap the `{ scenarios, count }` envelope to the array. */
export const getMockScenarios = async (): Promise<MockScenario[]> => {
  const res = await get<MockScenariosResponse>('/mock/scenarios')
  return res.scenarios
}

export const triggerMockScenario = (scenarioId: string) =>
  post<MockTriggerResult>(`/mock/trigger/${scenarioId}`)

export const resetMock = () => post<MockResetResult>('/mock/reset')

export const startMockStream = () =>
  post<MockStreamStartResult>('/mock/stream/start')

export const stopMockStream = () => post<MockStreamStopResult>('/mock/stream/stop')

export const getMockStatus = () => get<MockStatus>('/mock/status')

/* ------------------------------------------------------------------ *
 * Health                                                              *
 * ------------------------------------------------------------------ */

export const getHealth = () => get<{ status: string }>('/health')
