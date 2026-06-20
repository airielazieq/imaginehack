import { Brain } from 'lucide-react'
import type { XAIExplanation } from '../../types'
import { formatNumber } from '../../lib/formatters'

interface XAICardProps {
  /** Structured SHAP-style explanation attached to an Issue. */
  explanation: XAIExplanation
}

/** Render a factor value: numbers get thousands separators, strings pass through. */
function formatValue(value: number | string): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? formatNumber(value) : formatNumber(value, 2)
  }
  return value
}

/**
 * Explainable-AI card showing the SHAP-style top contributing factors behind a
 * detection, as a Feature · Value · Impact table (Requirement 4.2).
 */
export default function XAICard({ explanation }: XAICardProps) {
  const factors = explanation.top_contributing_factors ?? []

  return (
    <section className="card p-6">
      <div className="flex items-center gap-2">
        <Brain className="h-5 w-5 text-healthy-700" aria-hidden />
        <div>
          <p className="eyebrow">Explainable AI</p>
          <h2 className="mt-0.5 text-lg font-semibold text-navy-50">Why this was flagged</h2>
        </div>
      </div>
      <p className="mt-2 text-xs text-navy-300">
        Method: <span className="font-medium text-navy-100">{explanation.method}</span>
      </p>

      {factors.length === 0 ? (
        <p className="mt-4 text-sm text-navy-300">
          No contributing factors were recorded for this detection.
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-navy-700 text-left text-xs uppercase tracking-wide text-navy-400">
                <th className="px-3 py-2 font-medium">Feature</th>
                <th className="px-3 py-2 font-medium">Value</th>
                <th className="px-3 py-2 font-medium">Impact</th>
              </tr>
            </thead>
            <tbody>
              {factors.map((factor, idx) => (
                <tr
                  key={`${factor.feature}-${idx}`}
                  className="border-b border-navy-800 last:border-0"
                >
                  <td className="px-3 py-2 font-medium text-navy-50">{factor.feature}</td>
                  <td className="px-3 py-2 tabular-nums text-navy-100">
                    {formatValue(factor.value)}
                  </td>
                  <td className="px-3 py-2 text-navy-200">{factor.impact}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
