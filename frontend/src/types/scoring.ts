// Mirrors backend/schemas/scoring.py and prediction.py.

export type DimensionState = 'green' | 'yellow' | 'red' | 'gray'

/** 6-factor weighted priority score that drives the composite heatmap. */
export interface PriorityScore {
  workload_id: string
  score: number // 0-100, 1 decimal place
  security_severity: number
  energy_waste: number
  cost_waste: number
  workflow_criticality: number
  environment_type: number
  self_healing_safety: number
  unavailable_factors: string[]
  detection_timestamp: string
  computed_at: string
}

/** A single dimension's numeric score plus its state color. */
export interface DimensionScore {
  score: number // 0-100
  state: DimensionState
}

/** Per-dimension scores that drive the matrix heatmap. */
export interface DimensionScores {
  workload_id: string
  security: DimensionScore
  energy: DimensionScore
  carbon: DimensionScore
  cost: DimensionScore
  performance: DimensionScore
  monitoring: DimensionScore
}

export type PredictionConfidence = 'low' | 'medium' | 'high'

/** Failure probability, timeline and contributing signals for a workload. */
export interface DowntimePrediction {
  workload_id: string
  probability: number // 0-100
  estimated_time_to_failure: string // "4h 30m" format
  primary_signal: string
  secondary_signal: string | null
  pattern_match: string | null
  confidence: PredictionConfidence
  risk_timeline: number[] // 12 points (hourly)
  recommended_preemptive_action: string | null // set when probability > 70%
}
