// WebSocket envelope + stream-payload types.
//
// Mirrors the contract emitted by backend/api/websocket.py (task 17.1). Every
// message shares the same envelope; the `type` field selects the stream and
// determines the shape of `data`. Control messages (`hello`, `heartbeat`) carry
// `event_type: null` and an empty/ignored `data` payload.

import type { Alert } from './alert'
import type { DowntimePrediction } from './scoring'
import type { Recommendation } from './recommendation'
import type { RemediationResult } from './remediation'

/** Frontend-facing stream `type` values plus the two control types. */
export type WsStreamType =
  | 'heatmap_update'
  | 'alert_new'
  | 'healing_status'
  | 'approval_count'
  | 'prediction_update'

export type WsControlType = 'hello' | 'heartbeat'

export type WsMessageType = WsStreamType | WsControlType

/**
 * Internal backend EventType values surfaced in the envelope's `event_type`.
 * `null` for control messages (`hello` / `heartbeat`).
 */
export type WsEventType =
  | 'score_updated'
  | 'alert_fired'
  | 'remediation_completed'
  | 'recommendation_generated'
  | 'prediction_updated'
  | null

// --------------------------------------------------------------------------- //
// Per-stream payloads (the `data` field).
// --------------------------------------------------------------------------- //

/** `heatmap_update` <- SCORE_UPDATED: a single cell's priority score change. */
export interface HeatmapUpdatePayload {
  workload_id: string
  score: number
  priority_score: number
}

/** `alert_new` <- ALERT_FIRED: a freshly fired alert for the badge/feed. */
export interface AlertNewPayload {
  workload_id: string
  alert_id: string
  severity: string
  priority_score: number
  alert?: Alert
}

/** `healing_status` <- REMEDIATION_COMPLETED: a self-healing transition. */
export interface HealingStatusPayload {
  workload_id?: string
  remediation_id?: string
  issue_id?: string
  execution_status?: string
  execution_path?: string
  remediation?: RemediationResult
  [key: string]: unknown
}

/** `approval_count` <- RECOMMENDATION_GENERATED: approval-queue change. */
export interface ApprovalCountPayload {
  workload_id?: string
  recommendation_id?: string
  pending_count?: number
  recommendation?: Recommendation
  [key: string]: unknown
}

/** `prediction_update` <- PREDICTION_UPDATED: refreshed downtime forecast. */
export interface PredictionUpdatePayload {
  workload_id: string
  prediction: DowntimePrediction
}

/** Maps each stream `type` to the shape of its `data` payload. */
export interface WsPayloadByType {
  heatmap_update: HeatmapUpdatePayload
  alert_new: AlertNewPayload
  healing_status: HealingStatusPayload
  approval_count: ApprovalCountPayload
  prediction_update: PredictionUpdatePayload
  hello: Record<string, unknown>
  heartbeat: Record<string, unknown>
}

// --------------------------------------------------------------------------- //
// Envelope.
// --------------------------------------------------------------------------- //

/** The full message envelope, generic over the message `type`. */
export interface WsEnvelope<T extends WsMessageType = WsMessageType> {
  type: T
  event_type: WsEventType
  data: WsPayloadByType[T]
  timestamp: string
  /** Trace id; absent on control messages (`hello` / `heartbeat`). */
  correlation_id?: string
}

/** Any incoming message after JSON parsing. */
export type WsMessage = WsEnvelope

/** Lifecycle states for the underlying socket. */
export type WsConnectionStatus =
  | 'connecting'
  | 'open'
  | 'closed'
  | 'reconnecting'

/** Set of stream `type` values (excludes control types). */
export const WS_STREAM_TYPES: readonly WsStreamType[] = [
  'heatmap_update',
  'alert_new',
  'healing_status',
  'approval_count',
  'prediction_update',
] as const

/** Type guard: is this a real stream message (not a control message)? */
export function isStreamMessage(
  message: WsMessage,
): message is WsEnvelope<WsStreamType> {
  return (WS_STREAM_TYPES as readonly string[]).includes(message.type)
}
