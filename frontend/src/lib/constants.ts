// Shared frontend constants: API base, polling intervals, and score thresholds.

/**
 * Base URL for all REST calls. Defaults to `/api` so the Vite dev proxy
 * (see vite.config.ts) forwards to the FastAPI backend on :8000. Override
 * with VITE_API_BASE for non-proxied deployments.
 */
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ??
  '/api'

/**
 * WebSocket endpoint for real-time events. Defaults to `/ws/events`, proxied
 * by Vite. Override with VITE_WS_BASE.
 */
export const WS_BASE: string =
  (import.meta.env.VITE_WS_BASE as string | undefined) ?? '/ws/events'

/** Polling intervals (ms) for data that is not yet pushed over WebSocket. */
export const POLLING_INTERVALS = {
  /** Dashboard heatmap + summary cards. */
  dashboard: 10_000,
  /** Issues list. */
  issues: 15_000,
  /** Approval queue (escalation countdowns are time-sensitive). */
  approvals: 5_000,
  /** Workload detail / telemetry. */
  workloadDetail: 10_000,
  /** Mock controller stream status. */
  mockStatus: 5_000,
} as const

/**
 * Priority Score (0-100) → severity thresholds.
 * Higher score = more urgent. Mirrors backend alert thresholds
 * (>80 critical, 60-80 high, 30-60 medium, <=30 low).
 */
export const SCORE_THRESHOLDS = {
  critical: 80,
  high: 60,
  medium: 30,
} as const

/**
 * Dimension Score (0-100) → state thresholds.
 * Higher score = healthier. Mirrors backend mapping
 * (>=75 green, 50-74 yellow, <50 red, no data gray).
 */
export const DIMENSION_THRESHOLDS = {
  green: 75,
  yellow: 50,
} as const

/** Maximum WebSocket reconnect backoff (ms). */
export const WS_MAX_BACKOFF_MS = 30_000

/** Data considered stale after this many missed refresh windows. */
export const STALE_AFTER_INTERVALS = 2
