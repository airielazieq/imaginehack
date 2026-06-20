import { TrendingDown } from 'lucide-react'
import type { ForecastComponent } from '../../types'
import { formatCurrency, formatNumber } from '../../lib/formatters'

interface SavingsBadgeProps {
  /** Projected 30-day savings across cost / energy / carbon. */
  savings: ForecastComponent
  /** Extra classes to merge onto the badge. */
  className?: string
}

/**
 * Callout badge summarizing projected 30-day savings. Leads with the dollar
 * figure (the headline number) and surfaces energy + carbon as supporting
 * context. When every dimension is zero (e.g. a security-only fix) it renders a
 * neutral "no projected savings" state instead of a green win.
 */
export default function SavingsBadge({ savings, className = '' }: SavingsBadgeProps) {
  const hasSavings =
    savings.cost_30d > 0 || savings.energy_30d_kwh > 0 || savings.carbon_30d_kgco2e > 0

  if (!hasSavings) {
    return (
      <span
        className={[
          'inline-flex items-center gap-2 rounded-lg bg-navy-900 px-3 py-2 text-sm font-medium text-navy-200 ring-1 ring-inset ring-navy-700',
          className,
        ]
          .filter(Boolean)
          .join(' ')}
      >
        No projected savings — this action protects without changing spend.
      </span>
    )
  }

  return (
    <span
      className={[
        'inline-flex items-center gap-3 rounded-lg bg-healthy-500/15 px-4 py-2 text-healthy-700 ring-1 ring-inset ring-healthy-500/30',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <TrendingDown className="h-5 w-5 shrink-0" aria-hidden />
      <span className="flex flex-col leading-tight">
        <span className="text-base font-semibold text-healthy-700">
          {formatCurrency(savings.cost_30d)} / 30 days
        </span>
        <span className="text-xs text-healthy-700">
          {formatNumber(savings.energy_30d_kwh, 1)} kWh ·{' '}
          {formatNumber(savings.carbon_30d_kgco2e, 1)} kgCO₂e saved
        </span>
      </span>
    </span>
  )
}
