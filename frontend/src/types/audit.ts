// Mirrors backend/schemas/audit.py.

/** An immutable audit-trail entry for a platform state transition. */
export interface AuditLog {
  audit_id: string
  event_type: string
  actor: string // "system", "user", "auto_fix", etc.
  workload_id: string
  issue_id: string | null
  recommendation_id: string | null
  remediation_id: string | null
  timestamp: string
  previous_status: string | null
  new_status: string | null
  details: Record<string, unknown>
  rollback_note: string | null
}
