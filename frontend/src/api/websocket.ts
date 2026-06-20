// Framework-agnostic WebSocket manager with auto-reconnect (task 17.2).
//
// Connects to the backend `GET /ws/events` endpoint (see
// backend/api/websocket.py), parses the JSON envelope, and fans messages out
// to subscribers. On close/error it reconnects with exponential backoff
// (1s → 30s max, per the design "Error Handling" table). Connection-state
// changes are reported to a separate set of listeners so the UI can surface a
// "data stale" / "reconnecting" indicator.
//
// This module is deliberately UI-free; the React layer (hooks/useWebSocket.ts)
// owns a single instance and adapts it to component state.

import { WS_BASE, WS_MAX_BACKOFF_MS } from '../lib/constants'
import type { WsConnectionStatus, WsMessage } from '../types'

type MessageListener = (message: WsMessage) => void
type StatusListener = (status: WsConnectionStatus) => void

/** Initial reconnect delay; doubles each attempt up to {@link WS_MAX_BACKOFF_MS}. */
const INITIAL_BACKOFF_MS = 1_000

/**
 * Resolve the WebSocket URL from {@link WS_BASE}, keeping it consistent with
 * how the REST client resolves its base.
 *
 * - Absolute `ws://` / `wss://` values are used verbatim.
 * - Absolute `http(s)://` values are converted to `ws(s)://`.
 * - Relative values (default `/ws/events`) are resolved against the current
 *   page origin, mapping `https → wss` and `http → ws`. In dev this hits the
 *   Vite proxy (`/ws` → `ws://localhost:8000`), matching the REST `/api` proxy.
 */
export function resolveWebSocketUrl(base: string = WS_BASE): string {
  if (/^wss?:\/\//i.test(base)) return base
  if (/^https?:\/\//i.test(base)) return base.replace(/^http/i, 'ws')

  // Relative path → resolve against the page origin (SSR-safe fallback).
  if (typeof window === 'undefined' || !window.location) {
    return `ws://localhost:8000${base.startsWith('/') ? base : `/${base}`}`
  }
  const { protocol, host } = window.location
  const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:'
  const path = base.startsWith('/') ? base : `/${base}`
  return `${wsProtocol}//${host}${path}`
}

export interface WebSocketManagerOptions {
  /** Override the resolved URL (mainly for tests). */
  url?: string
  /** Initial backoff in ms (defaults to 1s). */
  initialBackoffMs?: number
  /** Maximum backoff in ms (defaults to {@link WS_MAX_BACKOFF_MS}). */
  maxBackoffMs?: number
}

/**
 * Owns a single WebSocket connection and its reconnect lifecycle. Subscribers
 * register via {@link onMessage} / {@link onStatus} and receive an unsubscribe
 * function.
 */
export class WebSocketManager {
  private readonly url: string
  private readonly initialBackoffMs: number
  private readonly maxBackoffMs: number

  private socket: WebSocket | null = null
  private status: WsConnectionStatus = 'closed'
  private backoffMs: number
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  /** True once {@link connect} is called; cleared by {@link disconnect}. */
  private shouldRun = false

  private readonly messageListeners = new Set<MessageListener>()
  private readonly statusListeners = new Set<StatusListener>()

  constructor(options: WebSocketManagerOptions = {}) {
    this.url = options.url ?? resolveWebSocketUrl()
    this.initialBackoffMs = options.initialBackoffMs ?? INITIAL_BACKOFF_MS
    this.maxBackoffMs = options.maxBackoffMs ?? WS_MAX_BACKOFF_MS
    this.backoffMs = this.initialBackoffMs
  }

  getStatus(): WsConnectionStatus {
    return this.status
  }

  /** Open the connection (idempotent while already running). */
  connect(): void {
    if (this.shouldRun) return
    this.shouldRun = true
    this.backoffMs = this.initialBackoffMs
    this.open()
  }

  /** Close the connection and stop reconnecting. */
  disconnect(): void {
    this.shouldRun = false
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.socket) {
      // Detach handlers so the close below doesn't schedule a reconnect.
      this.socket.onopen = null
      this.socket.onmessage = null
      this.socket.onerror = null
      this.socket.onclose = null
      try {
        this.socket.close()
      } catch {
        // Ignore — socket may already be closing.
      }
      this.socket = null
    }
    this.setStatus('closed')
  }

  /** Subscribe to parsed messages. Returns an unsubscribe function. */
  onMessage(listener: MessageListener): () => void {
    this.messageListeners.add(listener)
    return () => this.messageListeners.delete(listener)
  }

  /**
   * Subscribe to connection-status changes. The current status is delivered
   * immediately. Returns an unsubscribe function.
   */
  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener)
    listener(this.status)
    return () => this.statusListeners.delete(listener)
  }

  private open(): void {
    if (!this.shouldRun) return
    this.setStatus(this.socket ? 'reconnecting' : 'connecting')

    let socket: WebSocket
    try {
      socket = new WebSocket(this.url)
    } catch {
      this.scheduleReconnect()
      return
    }
    this.socket = socket

    socket.onopen = () => {
      this.backoffMs = this.initialBackoffMs
      this.setStatus('open')
    }

    socket.onmessage = (event: MessageEvent) => {
      const parsed = this.parse(event.data)
      if (parsed) this.emitMessage(parsed)
    }

    socket.onerror = () => {
      // The browser fires `close` right after `error`; reconnect is handled there.
    }

    socket.onclose = () => {
      this.socket = null
      if (this.shouldRun) this.scheduleReconnect()
      else this.setStatus('closed')
    }
  }

  private scheduleReconnect(): void {
    if (!this.shouldRun || this.reconnectTimer !== null) return
    this.setStatus('reconnecting')
    const delay = this.backoffMs
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      // Exponential backoff, capped at the configured maximum.
      this.backoffMs = Math.min(this.backoffMs * 2, this.maxBackoffMs)
      this.open()
    }, delay)
  }

  private parse(raw: unknown): WsMessage | null {
    if (typeof raw !== 'string') return null
    try {
      const value = JSON.parse(raw) as unknown
      if (
        typeof value === 'object' &&
        value !== null &&
        typeof (value as { type?: unknown }).type === 'string'
      ) {
        return value as WsMessage
      }
    } catch {
      // Malformed frame — ignore rather than break the stream.
    }
    return null
  }

  private emitMessage(message: WsMessage): void {
    for (const listener of this.messageListeners) {
      try {
        listener(message)
      } catch {
        // A faulty listener must not break delivery to the others.
      }
    }
  }

  private setStatus(status: WsConnectionStatus): void {
    if (this.status === status) return
    this.status = status
    for (const listener of this.statusListeners) {
      try {
        listener(status)
      } catch {
        // Ignore listener errors.
      }
    }
  }
}

export default WebSocketManager
