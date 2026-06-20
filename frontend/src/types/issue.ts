// Mirrors backend/schemas/issue.py.

export type IssueCategory =
  | 'security'
  | 'cost'
  | 'energy'
  | 'carbon'
  | 'performance'
  | 'monitoring'
  | 'cost_energy_carbon'

export type Severity = 'low' | 'medium' | 'high' | 'critical'

/** Risk level used inside EstimatedImpact (no "critical" — matches backend). */
export type ImpactRiskLevel = 'low' | 'medium' | 'high'

export type IssueStatus =
  | 'new'
  | 'recommended'
  | 'pending_approval'
  | 'approved'
  | 'auto_fixed'
  | 'remediated'
  | 'escalated'
  | 'rejected'
  | 'dismissed'

/** Output of the anomaly detection model (or its fallback). */
export interface MLResult {
  model_name: string
  anomaly_score: number
  is_anomaly: boolean
}

/** A single feature contribution within an XAI explanation. */
export interface XAIFactor {
  feature: string
  value: number | string
  impact: string
}

/** Explainable-AI summary of top contributing factors. */
export interface XAIExplanation {
  method: string
  top_contributing_factors: XAIFactor[]
}

/** Per-dimension risk assessment for an issue. */
export interface EstimatedImpact {
  cost_risk: ImpactRiskLevel
  energy_risk: ImpactRiskLevel
  carbon_risk: ImpactRiskLevel
  security_risk: ImpactRiskLevel
  workflow_disruption_risk: ImpactRiskLevel
}

/** Detection output / Module 2 input. */
export interface Issue {
  issue_id: string
  workload_id: string
  issue_type: string
  issue_category: IssueCategory
  severity: Severity
  confidence_score: number
  detected_evidence: Record<string, unknown>
  ml_result: MLResult
  xai_explanation: XAIExplanation
  llm_user_explanation: string
  estimated_impact: EstimatedImpact
  status: IssueStatus
  detected_at: string
}
