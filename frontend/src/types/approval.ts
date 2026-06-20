// Mirrors backend ApprovalItem.to_dict()
// (backend/modules/self_healing/approval_queue.py).
//
// An entry in the global remediation approval queue. The backend wraps the
// list in `{ approvals, count }`; individual decision endpoints return a single
// ApprovalItem.

import type { Severity } from './issue'
import type { RiskLevel } from './recommendation'

/** Lifecycle state of a queued remediation. */
export type ApprovalStatus =
  | 'pending'
  | 'snoozed'
  | 'approved'
  | 'denied'
  | 'escalated'

/** A single remediation awaiting (or having received) a human decision. */
export interface ApprovalItem {
  approval_id: string
  recommendation_id: string
  issue_id: string
  workload_id: string
  severity: Severity
  risk_level: RiskLevel
  recommended_action: string
  action_category: string
  /** Full set of MCP tools the runbook may invoke. */
  mcp_tools: string[]
  environment: string | null
  ai_rationale: string
  status: ApprovalStatus
  created_at: string
  /** ISO timestamp when the item auto-escalates, or null if no timer. */
  escalation_deadline: string | null
  snoozed_until: string | null
  resolved_at: string | null
  /** Live countdown to escalation in seconds, or null if no timer. */
  seconds_until_escalation: number | null
  /** Subset of mcp_tools chosen by the operator at approval time. */
  selected_mcp_tools: string[]
}

/** Envelope payload for `GET /api/approvals`. */
export interface ApprovalsListResponse {
  approvals: ApprovalItem[]
  count: number
}
