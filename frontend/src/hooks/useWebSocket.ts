// React binding for the WebSocket channel (task 17.2).
//
// A single {@link WebSocketManager} is owned by the {@link WebSocketProvider}
// and shared across the whole app via context. Components read connection
// state, the latest message per stream type, and a stale flag; or register a
// raw message callback via the returned `subscribe`.
//
// Staleness: we record the timestamp of the *last received message of any kind*
// (including heartbeats, which arrive ~every 15s). If nothing arrives within
// STALE_AFTER_INTERVALS heartbeat windows, or the socket isn't open, the data
// is considered stale — driving the "data stale" indicator (Requirement 20.3,
// UI spec §1: "data stale" if refresh > 2 intervals).

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { WebSocketManager } from '../api/websocket'
import { STALE_AFTER_INTERVALS } from '../lib/constants'
import type {
  WsConnectionStatus,
  WsEnvelope,
  WsMessage,
  WsStreamType,
} from '../types'

/** Heartbeat cadence on the server (backend/api/websocket.py `_HEARTBEAT_INTERVAL`). */
const HEARTBEAT_INTERVAL_MS = 15_000

/** No message for this long ⇒ data is stale. */
const STALE_THRESHOLD_MS = HEARTBEAT_INTERVAL_MS * STALE_AFTER_INTERVALS

/** How often the provider re-evaluates the stale clock. */
const STALE_CHECK_INTERVAL_MS = 5_000

type Unsubscribe = () => void

/** Latest stream message keyed by stream type (control messages excluded). */
type LatestByType = Partial<{
  [K in WsStreamType]: WsEnvelope<K>
}>

export interface WebSocketContextValue {
  /** Current socket lifecycle state. */
  status: WsConnectionStatus
  /** True when the socket is open. */
  connected: boolean
  /** True when no message has arrived recently or the socket is down. */
  isStale: boolean
  /** Epoch ms of the last received message (any type), or null. */
  lastMessageAt: number | null
  /** Most recent message per stream type. */
  latest: LatestByType
  /** Register a raw message listener. Returns an unsubscribe function. */
  subscribe: (listener: (message: WsMessage) => void) => Unsubscribe
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null)

export interface WebSocketProviderProps {
  children: ReactNode
  /** Inject a manager (tests); defaults to a real one bound to WS_BASE. */
  manager?: WebSocketManager
}

/**
 * Owns the singleton connection and publishes its state via context. Wrap the
 * app (or the routed shell) so any page can consume real-time updates without
 * opening its own socket.
 */
export function WebSocketProvider({ children, manager }: WebSocketProviderProps) {
  // One manager for the provider's lifetime.
  const managerRef = useRef<WebSocketManager | null>(manager ?? null)
  if (managerRef.current === null) {
    managerRef.current = new WebSocketManager()
  }
  const mgr = managerRef.current

  const [status, setStatus] = useState<WsConnectionStatus>(mgr.getStatus())
  const [latest, setLatest] = useState<LatestByType>({})
  const [lastMessageAt, setLastMessageAt] = useState<number | null>(null)
  const [now, setNow] = useState<number>(() => Date.now())

  // Connect on mount, disconnect on unmount.
  useEffect(() => {
    const offStatus = mgr.onStatus(setStatus)
    const offMessage = mgr.onMessage((message) => {
      setLastMessageAt(Date.now())
      // Track the latest message for each real stream type.
      if (
        message.type === 'heatmap_update' ||
        message.type === 'alert_new' ||
        message.type === 'healing_status' ||
        message.type === 'approval_count' ||
        message.type === 'prediction_update'
      ) {
        setLatest((prev) => ({
          ...prev,
          [message.type]: message,
        }))
      }
    })
    mgr.connect()
    return () => {
      offStatus()
      offMessage()
      mgr.disconnect()
    }
  }, [mgr])

  // Tick a clock so `isStale` recomputes even when no messages arrive.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), STALE_CHECK_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  const connected = status === 'open'

  const isStale = useMemo(() => {
    if (!connected) return true
    if (lastMessageAt === null) return false // just connected; give it a beat
    return now - lastMessageAt > STALE_THRESHOLD_MS
  }, [connected, lastMessageAt, now])

  const subscribe = useCallback(
    (listener: (message: WsMessage) => void) => mgr.onMessage(listener),
    [mgr],
  )

  const value = useMemo<WebSocketContextValue>(
    () => ({ status, connected, isStale, lastMessageAt, latest, subscribe }),
    [status, connected, isStale, lastMessageAt, latest, subscribe],
  )

  // Avoid JSX here so this file stays a plain .ts module.
  return createElement(WebSocketContext.Provider, { value }, children)
}

/**
 * Access the shared WebSocket context. Throws if used outside the provider so
 * misuse fails loudly during development.
 */
export function useWebSocket(): WebSocketContextValue {
  const ctx = useContext(WebSocketContext)
  if (ctx === null) {
    throw new Error('useWebSocket must be used within a <WebSocketProvider>')
  }
  return ctx
}

/**
 * Subscribe to messages of a single stream type. The callback fires for each
 * matching message; the latest such message is also returned for convenience.
 */
export function useWsSubscription<T extends WsStreamType>(
  type: T,
  onMessage?: (message: WsEnvelope<T>) => void,
): WsEnvelope<T> | undefined {
  const { subscribe, latest } = useWebSocket()
  const handlerRef = useRef(onMessage)
  handlerRef.current = onMessage

  useEffect(() => {
    return subscribe((message) => {
      if (message.type === type) {
        handlerRef.current?.(message as WsEnvelope<T>)
      }
    })
  }, [subscribe, type])

  return latest[type]
}

export default useWebSocket
