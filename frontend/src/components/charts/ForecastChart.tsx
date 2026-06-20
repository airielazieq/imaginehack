import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { OptimizationImpactForecast } from '../../types'
import { formatCurrency, formatNumber } from '../../lib/formatters'

interface ForecastChartProps {
  /** Before/after/savings projection to visualize. */
  forecast: OptimizationImpactForecast
}

// Per-dimension chart config. Cost, energy, and carbon use different units and
// scales, so each renders as its own small "without vs after" bar chart rather
// than being forced onto one shared axis.
interface MetricConfig {
  key: string
  label: string
  unit: string
  without: number
  after: number
  format: (value: number) => string
}

const WITHOUT_COLOR = '#f43f6e' // critical-500
const AFTER_COLOR = '#10b981' // healthy-500

/**
 * Grouped bar charts comparing the 30-day forecast with no action versus after
 * the recommended action, one panel each for cost, energy, and carbon.
 */
export default function ForecastChart({ forecast }: ForecastChartProps) {
  const { forecast_without_action: without, forecast_after_action: after } = forecast

  const metrics: MetricConfig[] = [
    {
      key: 'cost',
      label: 'Cost',
      unit: 'USD',
      without: without.cost_30d,
      after: after.cost_30d,
      format: (v) => formatCurrency(v),
    },
    {
      key: 'energy',
      label: 'Energy',
      unit: 'kWh',
      without: without.energy_30d_kwh,
      after: after.energy_30d_kwh,
      format: (v) => `${formatNumber(v, 1)} kWh`,
    },
    {
      key: 'carbon',
      label: 'Carbon',
      unit: 'kgCO₂e',
      without: without.carbon_30d_kgco2e,
      after: after.carbon_30d_kgco2e,
      format: (v) => `${formatNumber(v, 1)} kgCO₂e`,
    },
  ]

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {metrics.map((metric) => {
        const data = [
          { name: 'Without action', value: metric.without, fill: WITHOUT_COLOR },
          { name: 'After action', value: metric.after, fill: AFTER_COLOR },
        ]
        return (
          <div key={metric.key} className="rounded-lg bg-navy-900/60 p-3 ring-1 ring-inset ring-navy-700">
            <p className="mb-2 text-xs font-medium text-navy-300">
              {metric.label} <span className="text-navy-400">· 30-day ({metric.unit})</span>
            </p>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={data} margin={{ top: 16, right: 8, bottom: 0, left: 8 }}>
                <XAxis
                  dataKey="name"
                  tick={{ fill: '#475569', fontSize: 11 }}
                  axisLine={{ stroke: '#e2e8f0' }}
                  tickLine={false}
                />
                <YAxis hide />
                <Tooltip
                  cursor={{ fill: 'rgba(15,23,42,0.04)' }}
                  formatter={(value: number) => [metric.format(value), metric.label]}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={56}>
                  {data.map((entry) => (
                    <Cell key={entry.name} fill={entry.fill} />
                  ))}
                  <LabelList
                    dataKey="value"
                    position="top"
                    formatter={(value: number) => metric.format(value)}
                    fill="#475569"
                    fontSize={11}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )
      })}
    </div>
  )
}
