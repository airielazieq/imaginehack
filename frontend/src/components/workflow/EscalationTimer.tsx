import { useEffect, useState } from 'react'
import { AlarmClock } from 'lucide-react'
import type { Severity } from '../../types'
import { formatCountdown } from '../../lib/formatters'

interface EscalationTimerProps {
  /**
   * Seconds remaining until auto-escalation, as reported by the backend
   * (`seconds_until_escalation`). Null/undefined means the item carries no
   * escalation timer.
   */
  seconds: number | null | undefined
  /** Drives the pulsing emphasis: critical items pulse red. */
  severity: Severity
  /** Whether the item has already escalated (status === 'escalated'). */
  escalated?: boolean
}

/**
 * Live escalation countdown. Ticks down locally once per second and resyncs
 * whenever the backing `seconds` prop changes (e.g. on poll). Critical-severity
 * items pulse to draw the eye (design.md §Approval Queue).
 */
export default function EscalationTimer({
  seconds,
  severity,
  escalated = false,
}: EscalationTimerProps) {
  const [remaining, setRemaining] = useState<number>(seconds ?? 0)

  // Resync the local countdown whenever the backend value changes.
  useEffect(() => {
    setRemaining(seconds ?? 0)
  }, [seconds])

  // Tick down once per second while there is time left.
  useEffect(() => {
    if (seconds == null || escalated) return
    const id = window.setInterval(() => {
      setRemaining((r) => (r > 0 ? r - 1 : 0))
    }, 1000)
    return () => window.clearInterval(id)
  }, [seconds, escalated])

  // No timer on this item.
  if (seconds == null && !escalated) {
    return <span className="text-xs text-navy-400">No escalation timer</span>
  }

  if (escalated || remaining <= 0) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-critical-700">
        <AlarmClock className="h-3.5 w-3.5" aria-hidden />
        Escalated
      </span>
    )
  }

  const urgent = severity === 'critical' || remaining <= 60
  const color = urgent ? 'text-critical-700' : 'text-warning-700'

  return (
    <span
      className={[
        'inline-flex items-center gap-1.5 font-mono text-xs font-semibold tabular-nums',
        color,
        severity === 'critical' ? 'animate-pulseRing' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      title="Time until auto-escalation"
    >
      <AlarmClock className="h-3.5 w-3.5" aria-hidden />
      {formatCountdown(remaining)}
    </span>
  )
}
