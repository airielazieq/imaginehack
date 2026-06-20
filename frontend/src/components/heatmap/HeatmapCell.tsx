// A single composite-heatmap cell: one Workload colored by its Priority Score
// on a continuous green→red gradient. Hovering reveals a tooltip with the
// workload name, score, status, and the top contributing factor (derived from
// the PriorityScore detail); clicking navigates to the Workload detail page.
//
// Requirements: 16.1 (gradient by Priority Score), 16.3 (hover tooltip),
// 16.4 (click → Workload detail).

import { Link } from 'react-router-dom'
import type { CompositeHeatmapCell } from '../../api/endpoints'
import type { PriorityScore } from '../../types'
import { priorityScoreColor, severityFromScore } from '../../lib/colorScale'

interface HeatmapCellProps {
  cell: CompositeHeatmapCell
}

/** Human-readable status label, capitalized. */
function statusLabel(status: string | null): string {
  if (!status) return 'Unknown'
  return status.charAt(0).toUpperCase() + status.slice(1)
}

/**
 * The six weighted factors of a PriorityScore, with display labels. Used to
 * surface the single biggest contributor in the tooltip.
 */
const FACTOR_LABELS: ReadonlyArray<{ key: keyof PriorityScore; label: string }> = [
  { key: 'security_severity', label: 'Security severity' },
  { key: 'energy_waste', label: 'Energy waste' },
  { key: 'cost_waste', label: 'Cost waste' },
  { key: 'workflow_criticality', label: 'Workflow criticality' },
  { key: 'environment_type', label: 'Environment type' },
  { key: 'self_healing_safety', label: 'Self-healing safety' },
]

/** Pick the highest-contributing factor from a PriorityScore detail. */
function topFactor(detail: PriorityScore | null | undefined): string {
  if (!detail) return 'None'
  let best: { label: string; value: number } | null = null
  for (const { key, label } of FACTOR_LABELS) {
    const value = detail[key]
    if (typeof value === 'number' && (best === null || value > best.value)) {
      best = { label, value }
    }
  }
  return best ? `${best.label} (${best.value.toFixed(0)})` : 'None'
}

export default function HeatmapCell({ cell }: HeatmapCellProps) {
  const { workload_id, workload_name, priority_score, status, score_detail } = cell

  const name = workload_name ?? workload_id
  const background = priorityScoreColor(priority_score)
  const severity = severityFromScore(priority_score)
  const factor = topFactor(score_detail)
  const unavailable = score_detail?.unavailable_factors ?? []

  return (
    <Link
      to={`/workloads/${workload_id}`}
      aria-label={`${name} — priority score ${priority_score.toFixed(1)}, ${severity}`}
      className="group relative block rounded-lg p-3 min-h-[84px] text-white shadow-card
                 ring-1 ring-white/10 transition-transform duration-150
                 hover:-translate-y-0.5 hover:shadow-lift hover:ring-white/30
                 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
      style={{ backgroundColor: background }}
    >
      {/* Cell face: score + workload name. */}
      <div className="flex h-full flex-col justify-between">
        <span className="text-lg font-semibold leading-none tabular-nums drop-shadow-sm">
          {priority_score.toFixed(1)}
        </span>
        <span className="mt-2 line-clamp-2 text-xs font-medium leading-tight text-white/90">
          {name}
        </span>
      </div>

      {/* Hover/focus tooltip. */}
      <div
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-56
                   -translate-x-1/2 scale-95 rounded-lg border border-navy-600 bg-navy-950/95
                   p-3 text-left opacity-0 shadow-lift backdrop-blur-sm transition
                   duration-150 group-hover:scale-100 group-hover:opacity-100
                   group-focus-visible:scale-100 group-focus-visible:opacity-100"
      >
        <p className="truncate text-sm font-semibold text-navy-50">{name}</p>
        <dl className="mt-2 space-y-1 text-xs">
          <div className="flex justify-between gap-3">
            <dt className="text-navy-300">Priority score</dt>
            <dd className="font-medium tabular-nums text-navy-50">
              {priority_score.toFixed(1)}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-navy-300">Status</dt>
            <dd className="font-medium text-navy-50">{statusLabel(status)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-navy-300">Top factor</dt>
            <dd className="max-w-[60%] truncate text-right font-medium text-navy-50">
              {factor}
            </dd>
          </div>
          {unavailable.length > 0 && (
            <div className="flex justify-between gap-3">
              <dt className="text-navy-300">Unavailable</dt>
              <dd className="font-medium tabular-nums text-navy-50">
                {unavailable.length} factor{unavailable.length === 1 ? '' : 's'}
              </dd>
            </div>
          )}
        </dl>
        {/* Caret */}
        <span
          className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent
                     border-t-navy-950/95"
        />
      </div>
    </Link>
  )
}
