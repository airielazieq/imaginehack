// Mirrors backend/schemas/alert.py.

import type { Severity } from './issue'

export type AlertStatus = 'active' | 'resolved' | 'delivery_failed' | 'suppressed'

/** Threshold-based alert with suppression / retry / SLA metadata. */
export interface Alert {
  alert_id: string
  title: string // max 120 chars
  workload_id: string
  construction_workflow: string
  severity: Severity
  security_impact: string // max 500 chars
  energy_impact: string // max 500 chars
  cost_impact: string // max 500 chars
  recommended_action: string
  self_healing_eligible: boolean
  status: AlertStatus
  priority_score: number
  created_at: string
  resolved_at: string | null
  resolution_method: string | null
  suppressed_until: string | null
  // Delivery / suppression metadata (backend tasks 16.2 / 21.1). All optional
  // and additive so existing alert consumers stay compatible.
  suppression_count?: number
  delivery_attempts?: number
  delivered_at?: string | null
  delivery_sla_seconds?: number | null
  first_attempt_at?: string | null
  last_attempt_at?: string | null
  sla_breached?: boolean
  escalated?: boolean
  escalated_at?: string | null
}
