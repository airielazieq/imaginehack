// SummaryCards — the dashboard stat-card row (Requirement 16.1 summary bar).
//
// Renders four at-a-glance stat cards from `GET /api/dashboard/summary`:
//   - Total workloads
//   - Active issues (with critical count as context)
//   - Pending approvals
//   - Projected savings (30-day cost), with energy/carbon context
//
// Currency and numbers are formatted via lib/formatters so the display stays
// consistent with the rest of the app.

import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { AlertTriangle, CheckSquare, Layers, PiggyBank } from 'lucide-react'
import { ApiError } from '../../api/client'
import { getDashboardSummary, type DashboardSummary } from '../../api/endpoints'
import { formatCurrency, formatNumber } from '../../lib/formatters'

interface FetchState {
  data: DashboardSummary | null
  loading: boolean
  error: string | null
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Unexpected error'
}

interface StatCardProps {
  label: string
  value: string
  icon: ReactNode
  accent: string
  context?: string
}

function StatCard({ label, value, icon, accent, context }: StatCardProps) {
  return (
    <div className="card flex items-start gap-4 p-5">
      <span
        className={`mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${accent}`}
        aria-hidden
      >
        {icon}
      </span>
      <div className="min-w-0">
        <p className="eyebrow">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums text-navy-50">{value}</p>
        {context && <p className="mt-0.5 truncate text-xs text-navy-300">{context}</p>}
      </div>
    </div>
  )
}

/** Layout used for the loading and populated states (4 columns on large screens). */
function CardsGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
  )
}

export default function SummaryCards() {
  const [state, setState] = useState<FetchState>({
    data: null,
    loading: true,
    error: null,
  })

  useEffect(() => {
    let active = true
    ;(async () => {
      setState((s) => ({ ...s, loading: true, error: null }))
      try {
        const data = await getDashboardSummary()
        if (active) setState({ data, loading: false, error: null })
      } catch (err) {
        if (active) setState({ data: null, loading: false, error: errorMessage(err) })
      }
    })()
    return () => {
      active = false
    }
  }, [])

  if (state.loading) {
    return (
      <CardsGrid>
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-[88px] animate-pulse rounded-xl bg-navy-800 ring-1 ring-navy-700"
          />
        ))}
      </CardsGrid>
    )
  }

  if (state.error) {
    return (
      <div className="rounded-lg border border-critical-700 bg-critical-900/30 p-4 text-sm text-critical-700">
        Failed to load dashboard summary: {state.error}
      </div>
    )
  }

  const summary = state.data
  if (!summary) return null

  const { projected_savings } = summary
  const savingsContext = `${formatNumber(projected_savings.energy_30d_kwh)} kWh · ${formatNumber(
    projected_savings.carbon_30d_kgco2e,
  )} kg CO₂e`

  return (
    <CardsGrid>
      <StatCard
        label="Total workloads"
        value={formatNumber(summary.total_workloads)}
        icon={<Layers size={20} className="text-navy-100" />}
        accent="bg-navy-700"
      />
      <StatCard
        label="Active issues"
        value={formatNumber(summary.active_issues)}
        icon={<AlertTriangle size={20} className="text-sev-high" />}
        accent="bg-sev-high/15"
        context={`${formatNumber(summary.critical_issues)} critical`}
      />
      <StatCard
        label="Pending approvals"
        value={formatNumber(summary.pending_approvals)}
        icon={<CheckSquare size={20} className="text-healthy-700" />}
        accent="bg-healthy-500/15"
        context={`${formatNumber(summary.open_recommendations)} open recommendations`}
      />
      <StatCard
        label="Projected savings (30d)"
        value={formatCurrency(projected_savings.cost_30d)}
        icon={<PiggyBank size={20} className="text-healthy-700" />}
        accent="bg-healthy-500/15"
        context={savingsContext}
      />
    </CardsGrid>
  )
}
