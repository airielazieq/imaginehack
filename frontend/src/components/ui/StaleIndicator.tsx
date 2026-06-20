// Real-time connection / "data stale" indicator (task 17.2, Requirement 20.3).
//
// Renders a compact badge in the app chrome that reflects the live WebSocket
// channel state:
//   - open + fresh      → green "Live" with a pulsing dot
//   - stale / down       → amber "Data stale" while it reconnects in the
//                          background (exponential backoff handled by the manager)
//
// Drop it into the header's status cluster. It self-subscribes to the shared
// WebSocket context, so no props are required.

import { Wifi, WifiOff } from 'lucide-react'
import { useRealtimeStatus } from '../../hooks/useRealtime'

interface StaleIndicatorProps {
  /** Extra classes for layout tweaks. */
  className?: string
}

export default function StaleIndicator({ className = '' }: StaleIndicatorProps) {
  const { connected, isStale, status } = useRealtimeStatus()

  // Fresh + connected: the happy path.
  if (connected && !isStale) {
    return (
      <span
        className={['flex items-center gap-1.5 text-xs text-navy-300', className]
          .filter(Boolean)
          .join(' ')}
        title="Live — receiving real-time updates"
        role="status"
      >
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full rounded-full bg-healthy-400 opacity-60 animate-ping" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-healthy-500" />
        </span>
        Live
      </span>
    )
  }

  // Stale or disconnected: surface a clear warning; the manager keeps retrying.
  const label = status === 'reconnecting' || status === 'connecting' ? 'Reconnecting…' : 'Data stale'

  return (
    <span
      className={[
        'flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-medium',
        'bg-warning-500/15 text-warning-700 border border-warning-500/30',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      title="Real-time updates interrupted — data may be out of date while reconnecting"
      role="alert"
    >
      {connected ? <Wifi size={13} /> : <WifiOff size={13} />}
      {label}
    </span>
  )
}
