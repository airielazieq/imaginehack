import type { ForecastComponent, OptimizationImpactForecast } from '../../types'
import { formatCurrency, formatNumber } from '../../lib/formatters'
import ForecastChart from '../charts/ForecastChart'
import SavingsBadge from './SavingsBadge'

interface OptimizationForecastProps {
  /** Module 2 before/after/savings projection for the recommended action. */
  forecast: OptimizationImpactForecast
}

// One row per dimension in the before/after/savings comparison cards.
interface MetricRow {
  label: string
  format: (value: number) => string
  pick: (c: ForecastComponent) => number
}

const METRIC_ROWS: MetricRow[] = [
  { label: 'Cost', format: (v) => formatCurrency(v), pick: (c) => c.cost_30d },
  {
    label: 'Energy',
    format: (v) => `${formatNumber(v, 1)} kWh`,
    pick: (c) => c.energy_30d_kwh,
  },
  {
    label: 'Carbon',
    format: (v) => `${formatNumber(v, 1)} kgCO₂e`,
    pick: (c) => c.carbon_30d_kgco2e,
  },
]

interface ComparisonCardProps {
  title: string
  subtitle: string
  component: ForecastComponent
  tone: 'without' | 'after' | 'savings'
}

const TONE_STYLES: Record<ComparisonCardProps['tone'], string> = {
  without: 'ring-critical-500/30 bg-critical-900/15',
  after: 'ring-navy-700 bg-navy-900/60',
  savings: 'ring-healthy-500/30 bg-healthy-500/10',
}

const VALUE_STYLES: Record<ComparisonCardProps['tone'], string> = {
  without: 'text-critical-700',
  after: 'text-navy-100',
  savings: 'text-healthy-700',
}

function ComparisonCard({ title, subtitle, component, tone }: ComparisonCardProps) {
  return (
    <div className={`rounded-lg p-4 ring-1 ring-inset ${TONE_STYLES[tone]}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-navy-300">{title}</p>
      <p className="mt-0.5 text-[11px] text-navy-400">{subtitle}</p>
      <dl className="mt-3 space-y-2">
        {METRIC_ROWS.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-3">
            <dt className="text-xs text-navy-300">{row.label}</dt>
            <dd className={`text-sm font-medium tabular-nums ${VALUE_STYLES[tone]}`}>
              {tone === 'savings' ? '−' : ''}
              {row.format(row.pick(component))}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/**
 * Optimization Impact Forecast panel: side-by-side before / after / savings
 * cards, a savings callout badge, and a per-dimension bar chart comparison.
 * Renders Requirement 6.2's three forecast components.
 */
export default function OptimizationForecast({ forecast }: OptimizationForecastProps) {
  return (
    <section className="card p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Next Best Action · 30-day projection</p>
          <h2 className="mt-1 text-lg font-semibold text-navy-50">Optimization Impact Forecast</h2>
        </div>
        <SavingsBadge savings={forecast.projected_savings} />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-3">
        <ComparisonCard
          title="Without action"
          subtitle="Projected if nothing changes"
          component={forecast.forecast_without_action}
          tone="without"
        />
        <ComparisonCard
          title="After action"
          subtitle="Projected once remediated"
          component={forecast.forecast_after_action}
          tone="after"
        />
        <ComparisonCard
          title="Projected savings"
          subtitle="Without minus after"
          component={forecast.projected_savings}
          tone="savings"
        />
      </div>

      <div className="mt-6">
        <ForecastChart forecast={forecast} />
      </div>
    </section>
  )
}
