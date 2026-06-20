// Mirrors backend/schemas/remediation.py.

export type ExecutionPath = 'auto_fix' | 'user_approved' | 'human_escalation'

export type ExecutionStatus =
  | 'not_started'
  | 'pending_approval'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'escalated'
  | 'rejected'

export type MCPToolStatus = 'success' | 'failed' | 'skipped'

export type ApprovalType = 'auto' | 'user_approved' | 'escalated'

export type PolicyCompliance = 'compliant' | 'violation_overridden' | 'exception'

export type VerificationResult = 'passed' | 'failed' | 'skipped'

/** A single simulated MCP tool invocation within a runbook. */
export interface MCPToolExecution {
  tool: string
  category: string
  input: Record<string, unknown>
  output: Record<string, unknown>
  duration_ms: number
  status: MCPToolStatus
}

/** The safety router's rationale for the chosen execution path. */
export interface SafetyDecision {
  why_safe: string
  approval_required: boolean
  rollback_available: boolean
}

/** Compliance metadata attached to a remediation result. */
export interface AuditCompliance {
  approval_type: ApprovalType
  policy_compliance: PolicyCompliance
  rollback_available: boolean
  retention_expires: string
  persistent_data_modified: boolean
}

/** Module 3 output: full remediation record + report. */
export interface RemediationResult {
  remediation_id: string
  recommendation_id: string
  issue_id: string
  workload_id: string
  execution_path: ExecutionPath
  execution_status: ExecutionStatus
  action_taken: Record<string, unknown>
  reason_for_action: string
  safety_decision: SafetyDecision
  ai_decision_steps: Array<Record<string, unknown>>
  mcp_tools_executed: MCPToolExecution[]
  impact_result: Record<string, unknown>
  execution_timeline: Array<Record<string, unknown>>
  audit_compliance: AuditCompliance
  user_facing_report: string
  rollback_triggered: boolean
  verification_result: VerificationResult
}
