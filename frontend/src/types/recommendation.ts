// Mirrors backend/schemas/recommendation.py.

// Recommendation risk level includes "critical" (unlike EstimatedImpact risk).
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'

export type ExecutionMode =
  | 'auto_fix'
  | 'user_approval_required'
  | 'human_escalation_required'

/** The recommendation rule that fired and the conditions it matched. */
export interface RuleTriggered {
  rule_id: string
  conditions_matched: string[]
}

/** Raw 30-day forecast output from the forecasting model (or fallback). */
export interface ForecastModelResult {
  model_name: string
  predicted_cost_30d: number
  predicted_energy_kwh_30d: number
  predicted_carbon_kgco2e_30d: number
}

/** A single forecast bundle across cost / energy / carbon dimensions. */
export interface ForecastComponent {
  cost_30d: number
  energy_30d_kwh: number
  carbon_30d_kgco2e: number
}

/** Before / after / savings projection for a recommended action. */
export interface OptimizationImpactForecast {
  forecast_without_action: ForecastComponent
  forecast_after_action: ForecastComponent
  projected_savings: ForecastComponent
}

/** Module 2 output / Module 3 input. */
export interface Recommendation {
  recommendation_id: string
  issue_id: string
  workload_id: string
  recommended_action: string
  action_category: string
  recommendation_type: string
  rule_triggered: RuleTriggered
  forecast_model_result: ForecastModelResult
  optimization_impact_forecast: OptimizationImpactForecast
  risk_level: RiskLevel
  required_execution_mode: ExecutionMode
  approval_required: boolean
  mcp_tools: string[]
  llm_recommendation_explanation: string
  rollback_note: string | null
  created_at: string
}
