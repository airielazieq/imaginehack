import { AlertTriangle, Clock, Activity, Zap } from 'lucide-react'
import type { DowntimePrediction as DowntimePredictionModel } from '../../types'
import Badge, { type BadgeTone } from '../ui/Badge'
import RiskTimeline from '../charts/RiskTimeline'

interface DowntimePredictionProps {
  prediction: DowntimePredictionModel
}

// Prediction confidence → badge tone.
const CONFIDENCE_TONE: Record<DowntimePredictionModel['confidence'], BadgeTone> = {
  low: 'low',
  medium: 'medium',
  high: 'high',
}

/** Map a failure probability (0-100) to a severity-style accent. */
function probabilityTone(probability: number): {
  tone: BadgeTone
  color: string
  label: string
} {
  if (probability >= 70)
    return { tone: 'critical', color: '#f43f6e', label: 'High risk' }
  if (probability >= 40)
    return { tone: 'medium', color: '#f59e0b', label: 'Elevated risk' }
  return { tone: 'low', color: '#10b981', label: 'Low risk' }
}

/**
 * AI Downtime Prediction panel (Requirements 14.1, 14.2): probability gauge,
 * estimated time-to-failure, contributing signals, a 12-point hourly risk
 * timeline, and a preemptive-action CTA when the probability exceeds 70%.
 */
export default function DowntimePrediction({ prediction }: DowntimePredictionProps) {
  const {
    probability,
    estimated_time_to_failure,
    primary_signal,
    secondary_signal,
    pattern_match,
    confidence,
    risk_timeline,
    recommended_preemptive_action,
  } = prediction

  const risk = probabilityTone(probability)
  const dashOffset = 100 - Math.min(Math.max(probability, 0), 100)

  return (
    <section className="card p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">AI Downtime Prediction</p>
          <h2 className="mt-1 text-lg font-semibold text-navy-50">
            Failure forecast
          </h2>
        </div>
        <Badge tone={CONFIDENCE_TONE[confidence]} uppercase>
          {confidence} confidence
        </Badge>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-6 sm:grid-cols-[auto,1fr]">
        {/* Probability gauge */}
        <div className="flex items-center gap-4">
          <div className="relative h-28 w-28 shrink-0">
            <svg viewBox="0 0 36 36" className="h-full w-full -rotate-90">
              <circle
                cx="18"
                cy="18"
                r="15.915"
                fill="none"
                stroke="#e2e8f0"
                strokeWidth="3"
              />
              <circle
                cx="18"
                cy="18"
                r="15.915"
                fill="none"
                stroke={risk.color}
                strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray="100 100"
                strokeDashoffset={dashOffset}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-2xl font-semibold tabular-nums text-navy-50">
                {probability.toFixed(0)}%
              </span>
              <span className="text-[10px] uppercase tracking-wide text-navy-400">
                probability
              </span>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <Badge tone={risk.tone} uppercase>
              {risk.label}
            </Badge>
            <p className="flex items-center gap-1.5 text-sm text-navy-200">
              <Clock className="h-4 w-4 text-navy-400" aria-hidden />
              <span className="text-navy-400">Est. time to failure:</span>{' '}
              <span className="font-medium text-navy-50">
                {estimated_time_to_failure}
              </span>
            </p>
          </div>
        </div>

        {/* Contributing signals */}
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg bg-navy-900/60 p-3 ring-1 ring-inset ring-navy-700">
            <dt className="flex items-center gap-1.5 text-xs text-navy-400">
              <Activity className="h-3.5 w-3.5" aria-hidden /> Primary signal
            </dt>
            <dd className="mt-1 text-sm font-medium text-navy-50">{primary_signal}</dd>
          </div>
          <div className="rounded-lg bg-navy-900/60 p-3 ring-1 ring-inset ring-navy-700">
            <dt className="flex items-center gap-1.5 text-xs text-navy-400">
              <Activity className="h-3.5 w-3.5" aria-hidden /> Secondary signal
            </dt>
            <dd className="mt-1 text-sm font-medium text-navy-50">
              {secondary_signal ?? '—'}
            </dd>
          </div>
          {pattern_match && (
            <div className="rounded-lg bg-navy-900/60 p-3 ring-1 ring-inset ring-navy-700 sm:col-span-2">
              <dt className="text-xs text-navy-400">Pattern match</dt>
              <dd className="mt-1 text-sm font-medium text-navy-50">{pattern_match}</dd>
            </div>
          )}
        </dl>
      </div>

      {/* 12-point hourly risk timeline */}
      <div className="mt-6">
        <p className="mb-2 text-xs font-medium text-navy-300">
          12-hour projected risk timeline
        </p>
        <RiskTimeline timeline={risk_timeline} />
      </div>

      {/* Preemptive action CTA (probability > 70%) */}
      {recommended_preemptive_action && (
        <div className="mt-5 flex items-start gap-3 rounded-lg border border-critical-700/50 bg-critical-900/20 p-4">
          <AlertTriangle
            className="mt-0.5 h-5 w-5 shrink-0 text-critical-700"
            aria-hidden
          />
          <div>
            <p className="flex items-center gap-1.5 text-sm font-semibold text-critical-700">
              <Zap className="h-4 w-4" aria-hidden /> Preemptive action recommended
            </p>
            <p className="mt-1 text-sm text-critical-700">
              {recommended_preemptive_action}
            </p>
          </div>
        </div>
      )}
    </section>
  )
}
