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
 * Priority Score → continuous green→amber→red gradient.
 * Returns an HSL string. score 0 → green (hue 140), score 100 → red (hue 0).
 */
export function priorityScoreColor(score: number): string {
  const s = clamp(score)
  const hue = 140 - (s / 100) * 140 // 140 (green) → 0 (red)
  const lightness = s > 55 ? 42 : 40
  return `hsl(${hue.toFixed(0)}, 62%, ${lightness}%)`
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
