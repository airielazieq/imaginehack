// Real-time convenience hooks (task 17.2).
//
// Thin, page-friendly wrappers over `useWebSocket` / `useWsSubscription`. Pages
// opt in to a single stream (heatmap, alerts, approvals, healing, predictions)
// without touching the raw envelope plumbing. Each hook returns the latest
// payload for its stream and accepts an optional callback for every update.

import { useWebSocket, useWsSubscription } from './useWebSocket'
import type {
  AlertNewPayload,
  ApprovalCountPayload,
  HealingStatusPayload,
  HeatmapUpdatePayload,
  PredictionUpdatePayload,
  WsConnectionStatus,
  WsEnvelope,
} from '../types'

/** Live heatmap cell updates (priority score changes). */
export function useRealtimeHeatmap(
  onUpdate?: (payload: HeatmapUpdatePayload, message: WsEnvelope<'heatmap_update'>) => void,
): HeatmapUpdatePayload | undefined {
  const latest = useWsSubscription('heatmap_update', (m) => onUpdate?.(m.data, m))
  return latest?.data
}

/** Newly fired alerts (badge / feed). */
export function useRealtimeAlerts(
  onAlert?: (payload: AlertNewPayload, message: WsEnvelope<'alert_new'>) => void,
): AlertNewPayload | undefined {
  const latest = useWsSubscription('alert_new', (m) => onAlert?.(m.data, m))
  return latest?.data
}

/** Approval-queue changes. */
export function useRealtimeApprovals(
  onChange?: (payload: ApprovalCountPayload, message: WsEnvelope<'approval_count'>) => void,
): ApprovalCountPayload | undefined {
  const latest = useWsSubscription('approval_count', (m) => onChange?.(m.data, m))
  return latest?.data
}

/** Self-healing status transitions. */
export function useRealtimeHealing(
  onChange?: (payload: HealingStatusPayload, message: WsEnvelope<'healing_status'>) => void,
): HealingStatusPayload | undefined {
  const latest = useWsSubscription('healing_status', (m) => onChange?.(m.data, m))
  return latest?.data
}

/** Downtime-prediction refreshes. */
export function useRealtimePredictions(
  onUpdate?: (payload: PredictionUpdatePayload, message: WsEnvelope<'prediction_update'>) => void,
): PredictionUpdatePayload | undefined {
  const latest = useWsSubscription('prediction_update', (m) => onUpdate?.(m.data, m))
  return latest?.data
}

export interface RealtimeStatus {
  status: WsConnectionStatus
  connected: boolean
  isStale: boolean
  lastMessageAt: number | null
}

/** Connection/staleness summary for status indicators. */
export function useRealtimeStatus(): RealtimeStatus {
  const { status, connected, isStale, lastMessageAt } = useWebSocket()
  return { status, connected, isStale, lastMessageAt }
}
