// Color mapping helpers for heatmaps and badges.
//
// Two scales with opposite polarity:
//   - Priority Score (0-100): 0 = healthy (green), 100 = critical (red).
//   - Dimension Score (0-100): 0 = bad (red), 100 = good (green).

import type { DimensionState, Severity } from '../types'
import { DIMENSION_THRESHOLDS, SCORE_THRESHOLDS } from './constants'

const clamp = (n: number, min = 0, max = 100): number =>
  Math.min(Math.max(n, min), max)

/**
 * The three discrete status tones used by the Status heatmap. White cell text
 * sits on top of these, so each is a mid-dark 600-level tone with adequate
 * contrast. Matches the dimension-matrix green/yellow/red for visual consistency.
 */
export const PRIORITY_STATUS_COLORS = {
  green: '#16a34a', // green-600  — healthy
  yellow: '#ca8a04', // yellow-600 — watch
  red: '#dc2626', // red-600    — at risk
} as const

/**
 * Cut-points for the Status heatmap's three tones (higher score = worse).
 * Heatmap-specific on purpose, so tuning these never shifts the shared
 * SCORE_THRESHOLDS used by severity badges/alerts.
 */
export const PRIORITY_STATUS_THRESHOLDS = {
  red: 70, // ≥ 70 → at risk
  yellow: 35, // ≥ 35 → watch
} as const

/**
 * Priority Score → one of three discrete status tones (green / yellow / red).
 * Higher score = worse: < 35 healthy (green), 35–70 watch (yellow), ≥ 70 at risk
 * (red).
 */
export function priorityScoreColor(score: number): string {
  const s = clamp(score)
  if (s >= PRIORITY_STATUS_THRESHOLDS.red) return PRIORITY_STATUS_COLORS.red
  if (s >= PRIORITY_STATUS_THRESHOLDS.yellow) return PRIORITY_STATUS_COLORS.yellow
  return PRIORITY_STATUS_COLORS.green
}

/**
 * Dimension Score → continuous red→amber→green gradient (inverse polarity).
 * Returns an HSL string. score 0 → red, score 100 → green.
 * Pass null/undefined for "not monitored" → neutral gray.
 */
export function dimensionScoreColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return '#9ca3af' // gray-400
  const s = clamp(score)
  const hue = (s / 100) * 140 // 0 (red) → 140 (green)
  return `hsl(${hue.toFixed(0)}, 55%, 42%)`
}

/** Map a Priority Score (0-100) to a severity bucket. */
export function severityFromScore(score: number): Severity {
  const s = clamp(score)
  if (s >= SCORE_THRESHOLDS.critical) return 'critical'
  if (s >= SCORE_THRESHOLDS.high) return 'high'
  if (s >= SCORE_THRESHOLDS.medium) return 'medium'
  return 'low'
}

/** Map a Dimension Score (0-100) to a discrete state. null → gray. */
export function dimensionStateFromScore(
  score: number | null | undefined,
): DimensionState {
  if (score === null || score === undefined) return 'gray'
  const s = clamp(score)
  if (s >= DIMENSION_THRESHOLDS.green) return 'green'
  if (s >= DIMENSION_THRESHOLDS.yellow) return 'yellow'
  return 'red'
}

/** Tailwind/CSS hex colors for each discrete dimension state. */
export const DIMENSION_STATE_COLORS: Record<DimensionState, string> = {
  green: '#16a34a', // green-600
  yellow: '#ca8a04', // yellow-600
  red: '#dc2626', // red-600
  gray: '#9ca3af', // gray-400
}

/** Resolve a dimension state directly to its display color. */
export function dimensionStateColor(state: DimensionState): string {
  return DIMENSION_STATE_COLORS[state]
}

/** Hex colors per severity, for badges and accents. */
export const SEVERITY_COLORS: Record<Severity, string> = {
  critical: '#dc2626', // red-600
  high: '#ea580c', // orange-600
  medium: '#ca8a04', // yellow-600
  low: '#16a34a', // green-600
}

/** Resolve a severity to its display color. */
export function severityColor(severity: Severity): string {
  return SEVERITY_COLORS[severity]
}
