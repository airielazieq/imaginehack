import type { UptimeSegment, UptimeStatus } from '../../api/endpoints'
import { formatDate } from '../../lib/formatters'

interface UptimeBarProps {
  /** Daily uptime segments, oldest first (typically 90 days). */
  segments: UptimeSegment[]
  /** Overall uptime percentage across the window (for the summary label). */
  overallUptimePercent: number
  /** Number of days the window spans (for the caption). */
  windowDays?: number
}

// Status → fill color for each daily segment.
const STATUS_COLORS: Record<UptimeStatus, string> = {
  up: '#10b981', // healthy-500
  degraded: '#f59e0b', // warning/amber-500
  down: '#f43f6e', // critical-500
}

const STATUS_LABELS: Record<UptimeStatus, string> = {
  up: 'Operational',
  degraded: 'Degraded',
  down: 'Outage',
}

/**
 * 90-day segmented uptime strip (Requirement 17.3). Renders one thin vertical
 * bar per day colored by availability status, plus an overall uptime summary.
 */
export default function UptimeBar({
  segments,
  overallUptimePercent,
  windowDays,
}: UptimeBarProps) {
  const days = windowDays ?? segments.length

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-navy-50">
          {overallUptimePercent.toFixed(2)}%
          <span className="ml-1.5 text-xs font-normal text-navy-400">
            uptime · last {days} days
          </span>
        </p>
        <div className="flex items-center gap-3 text-[11px] text-navy-300">
          {(Object.keys(STATUS_COLORS) as UptimeStatus[]).map((status) => (
            <span key={status} className="inline-flex items-center gap-1">
              <span
                className="h-2 w-2 rounded-sm"
                style={{ backgroundColor: STATUS_COLORS[status] }}
                aria-hidden
              />
              {STATUS_LABELS[status]}
            </span>
          ))}
        </div>
      </div>

      <div className="flex h-10 items-stretch gap-[2px] overflow-hidden rounded-md">
        {segments.map((segment) => {
          const status = (segment.status as UptimeStatus) ?? 'up'
          return (
            <div
              key={segment.date}
              className="group relative min-w-[2px] flex-1 rounded-[1px] transition-transform hover:scale-y-110"
              style={{ backgroundColor: STATUS_COLORS[status] ?? STATUS_COLORS.up }}
              title={`${formatDate(segment.date)} · ${segment.uptime_percent.toFixed(
                2,
              )}% · ${STATUS_LABELS[status] ?? status}`}
            />
          )
        })}
      </div>

      <div className="flex justify-between text-[11px] text-navy-400">
        <span>{segments[0] ? formatDate(segments[0].date) : ''}</span>
        <span>
          {segments[segments.length - 1]
            ? formatDate(segments[segments.length - 1].date)
            : ''}
        </span>
      </div>
    </div>
  )
}
