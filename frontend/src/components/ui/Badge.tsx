import type { ReactNode } from 'react'
import type { Severity } from '../../types'

/**
 * Visual tone for a Badge. Severity tones map to the Tailwind `sev` palette
 * (critical/high/medium/low); `neutral` is used for statuses and generic tags.
 */
export type BadgeTone = Severity | 'neutral'

interface BadgeProps {
  /** Color tone. Defaults to `neutral` (used for status/category chips). */
  tone?: BadgeTone
  /** Badge label / content. */
  children: ReactNode
  /** Render the label in uppercase with wider tracking. */
  uppercase?: boolean
  /** Extra classes to merge onto the badge. */
  className?: string
}

// Static class maps so Tailwind's JIT can see every variant at build time.
const TONE_STYLES: Record<BadgeTone, string> = {
  critical: 'bg-sev-critical/15 text-sev-critical ring-sev-critical/30',
  high: 'bg-sev-high/15 text-sev-high ring-sev-high/30',
  medium: 'bg-sev-medium/15 text-sev-medium ring-sev-medium/30',
  low: 'bg-sev-low/15 text-sev-low ring-sev-low/30',
  neutral: 'bg-navy-900 text-navy-200 ring-navy-700',
}

/**
 * Small pill used for severities, statuses, and categories. Severity values
 * are color-coded via the `sev` palette; everything else uses neutral styling.
 */
export default function Badge({
  tone = 'neutral',
  children,
  uppercase = false,
  className = '',
}: BadgeProps) {
  return (
    <span
      className={[
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        TONE_STYLES[tone],
        uppercase ? 'uppercase tracking-wide' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </span>
  )
}

/** Set of severities that map to a colored Badge tone. */
const SEVERITY_TONES: ReadonlySet<string> = new Set<Severity>([
  'critical',
  'high',
  'medium',
  'low',
])

/** Resolve an arbitrary severity-ish string to a safe BadgeTone. */
export function severityTone(value: string): BadgeTone {
  return SEVERITY_TONES.has(value) ? (value as Severity) : 'neutral'
}
