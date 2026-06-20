import { AlertTriangle, Clock, Activity, Zap, Info } from 'lucide-react'
import type { DowntimePrediction as DowntimePredictionModel } from '../../types'
import Badge, { type BadgeTone } from '../ui/Badge'
import HealthTimeline from '../charts/HealthTimeline'

interface DowntimePredictionProps {
  prediction: DowntimePredictionModel
}

// Prediction confidence → badge tone.
const CONFIDENCE_TONE: Record<DowntimePredictionModel['confidence'], BadgeTone> = {
  low: 'low',
  medium: 'medium',
  high: 'high',
}

/**
 * Map a projected health score (0-100, higher = healthier) to a status accent.
 * Polarity is the inverse of the backend's risk number: health = 100 − risk, so
 * the old risk bands (≥70 high, ≥40 elevated) become health ≤30 critical,
 * ≤60 at-risk, the rest healthy.
 */
function healthTone(health: number): {
  tone: BadgeTone
  color: string
  label: string
} {
  if (health > 60) return { tone: 'low', color: '#10b981', label: 'Healthy' }
  if (health > 30) return { tone: 'medium', color: '#f59e0b', label: 'At risk' }
  return { tone: 'critical', color: '#f43f6e', label: 'Critical' }
}

/** Plain-language explanation of the projected health score, shown in a
 * hover/focus tooltip behind a small (i) button next to the gauge. Clarifies
 * that the number is a forward-looking health projection (higher = healthier),
 * not the server's current state or a calibrated probability. */
function HealthScoreInfo() {
  return (
    <span className="group/info relative inline-flex">
      <button
        type="button"
        aria-label="What does the health score mean?"
        className="inline-flex h-4 w-4 items-center justify-center rounded-full text-navy-400
                   transition-colors hover:text-navy-100 focus:outline-none
                   focus-visible:ring-2 focus-visible:ring-healthy-500"
      >
        <Info className="h-4 w-4" aria-hidden />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 w-64
                   -translate-x-1/2 scale-95 rounded-lg border border-navy-600 bg-navy-950/95
                   p-3 text-left opacity-0 shadow-lift backdrop-blur-sm transition duration-150
                   group-hover/info:scale-100 group-hover/info:opacity-100
                   group-focus-within/info:scale-100 group-focus-within/info:opacity-100"
      >
        <p className="text-xs font-semibold text-navy-50">What this score means</p>
        <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-navy-300">
          <li>
            • Forward-looking projection —{' '}
            <span className="text-navy-100">higher is healthier</span>.
          </li>
          <li>• Based on recent telemetry (error rate, memory, CPU, latency), ~12h ahead.</li>
          <li>• 100 = all signals well clear of failure; the closer the worst one gets to its limit, the lower the score.</li>
          <li>• Early-warning signal, not a guaranteed outcome.</li>
        </ul>
        <p className="mt-2 text-xs text-navy-400">
          Bands:
          <span className="text-healthy-700"> &gt;60 Healthy</span> ·
          <span className="text-warning-700"> 30–60 At risk</span> ·
          <span className="text-critical-700"> ≤30 Critical</span>.
        </p>
        <span
          className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent
                     border-t-navy-950/95"
        />
      </span>
    </span>
  )
}

/**
 * Server Health Forecast panel (Requirements 14.1, 14.2): a projected-health
 * gauge (health = 100 − the backend's failure risk, higher = healthier, with an
 * (i) explainer), estimated time-to-failure, contributing signals, a 12-point
 * hourly risk timeline, and a preemptive-action CTA when the underlying risk
 * exceeds 70% (i.e. projected health drops below 30).
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

  // The backend returns a failure-risk number (higher = worse). We present its
  // complement as a projected health score (higher = healthier) so the gauge
  // matches the "Server Health Forecast" framing.
  const health = 100 - Math.min(Math.max(probability, 0), 100)
  const status = healthTone(health)
  const dashOffset = 100 - health // arc grows as health improves

  return (
    <section className="card p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Server Health Forecast</p>
          <h2 className="mt-1 text-lg font-semibold text-navy-50">
            Health outlook
          </h2>
        </div>
        <Badge tone={CONFIDENCE_TONE[confidence]} uppercase>
          {confidence} confidence
        </Badge>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-6 sm:grid-cols-[auto,1fr]">
        {/* Projected-health gauge */}
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
                stroke={status.color}
                strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray="100 100"
                strokeDashoffset={dashOffset}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-2xl font-semibold tabular-nums text-navy-50">
                {health.toFixed(0)}%
              </span>
              <span className="text-[10px] uppercase tracking-wide text-navy-400">
                health score
              </span>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-1.5">
              <Badge tone={status.tone} uppercase>
                {status.label}
              </Badge>
              <HealthScoreInfo />
            </div>
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

      {/* 12-point hourly projected-health timeline */}
      <div className="mt-6">
        <p className="mb-2 text-xs font-medium text-navy-300">
          12-hour projected health timeline
        </p>
        <HealthTimeline timeline={risk_timeline} />
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
