import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, ShieldCheck, UserCheck } from 'lucide-react'
import { generateRecommendation, getRecommendation } from '../api/endpoints'
import { ApiError } from '../api/client'
import { useIssue } from '../hooks/useIssues'
import type { ExecutionMode, IssueStatus, Recommendation } from '../types'
import { formatDateTime, formatPercent } from '../lib/formatters'
import Badge, { type BadgeTone, severityTone } from '../components/ui/Badge'
import XAICard from '../components/cards/XAICard'
import OptimizationForecast from '../components/cards/OptimizationForecast'

/** Turn a snake_case enum value into a readable label. */
function humanize(value: string): string {
  return value
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

// Issue status → badge tone (statuses aren't severities, so map explicitly).
const STATUS_TONE: Record<IssueStatus, BadgeTone> = {
  new: 'neutral',
  recommended: 'neutral',
  pending_approval: 'medium',
  approved: 'low',
  auto_fixed: 'low',
  remediated: 'low',
  escalated: 'high',
  rejected: 'critical',
  dismissed: 'neutral',
}

// Execution-mode presentation for the CTA panel.
const EXECUTION_MODE: Record<
  ExecutionMode,
  { label: string; tone: BadgeTone; cta: string; icon: typeof ShieldCheck }
> = {
  auto_fix: {
    label: 'Auto-fix eligible',
    tone: 'low',
    cta: 'View remediation report',
    icon: ShieldCheck,
  },
  user_approval_required: {
    label: 'Approval required',
    tone: 'medium',
    cta: 'Review in approval queue',
    icon: UserCheck,
  },
  human_escalation_required: {
    label: 'Human escalation required',
    tone: 'high',
    cta: 'Open escalation queue',
    icon: AlertTriangle,
  },
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Unexpected error'
}

type RecState =
  | { kind: 'loading' }
  | { kind: 'ready'; rec: Recommendation }
  | { kind: 'unavailable'; reason: string }
  | { kind: 'error'; message: string }

/**
 * Resolve the recommendation for an issue. The Issue payload may carry a
 * `recommendation_id` (not in the shared type, so narrowed locally); if so we
 * read it directly, otherwise we generate one on demand. A 422 means no rule
 * covers this issue type — surfaced as a non-error "unavailable" state.
 */
function useIssueRecommendation(
  issueId: string | undefined,
  recommendationId: string | undefined,
) {
  const [state, setState] = useState<RecState>({ kind: 'loading' })

  const load = useCallback(async () => {
    if (!issueId) return
    setState({ kind: 'loading' })
    try {
      const rec = recommendationId
        ? await getRecommendation(recommendationId)
        : await generateRecommendation(issueId)
      setState({ kind: 'ready', rec })
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setState({ kind: 'unavailable', reason: err.message })
      } else {
        setState({ kind: 'error', message: errorMessage(err) })
      }
    }
  }, [issueId, recommendationId])

  useEffect(() => {
    let active = true
    if (!issueId) {
      setState({ kind: 'unavailable', reason: 'No issue selected.' })
      return
    }
    ;(async () => {
      setState({ kind: 'loading' })
      try {
        const rec = recommendationId
          ? await getRecommendation(recommendationId)
          : await generateRecommendation(issueId)
        if (active) setState({ kind: 'ready', rec })
      } catch (err) {
        if (!active) return
        if (err instanceof ApiError && err.status === 422) {
          setState({ kind: 'unavailable', reason: err.message })
        } else {
          setState({ kind: 'error', message: errorMessage(err) })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [issueId, recommendationId])

  return { state, reload: load }
}

export default function IssueDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: issue, loading, error } = useIssue(id)

  // The backend may include a recommendation_id on the issue document even
  // though the shared Issue type doesn't declare it — narrow it locally.
  const maybeRecId = issue
    ? (issue as unknown as Record<string, unknown>).recommendation_id
    : undefined
  const recommendationId = typeof maybeRecId === 'string' ? maybeRecId : undefined

  const { state: recState, reload } = useIssueRecommendation(issue?.issue_id, recommendationId)

  if (loading) {
    return (
      <div className="card p-10 text-center text-sm text-navy-300">Loading issue…</div>
    )
  }

  if (error) {
    return (
      <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
        Failed to load issue: {error}
      </div>
    )
  }

  if (!issue) {
    return (
      <div className="card p-8">
        <p className="eyebrow">Clover · Detection</p>
        <h1 className="mt-2 text-2xl font-semibold text-navy-50">Issue not found</h1>
        <p className="mt-1 text-sm text-navy-300">
          We couldn&apos;t find an issue with id <span className="font-mono">{id}</span>.
        </p>
        <Link to="/issues" className="mt-4 inline-flex items-center gap-2 text-sm text-healthy-700 hover:text-healthy-700">
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back to issues
        </Link>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <header>
        <Link
          to="/issues"
          className="inline-flex items-center gap-1.5 text-xs text-navy-300 hover:text-navy-50"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Issues
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold text-navy-50">{humanize(issue.issue_type)}</h1>
          <Badge tone={severityTone(issue.severity)} uppercase>
            {issue.severity}
          </Badge>
          <Badge>{humanize(issue.issue_category)}</Badge>
          <Badge tone={STATUS_TONE[issue.status]}>{humanize(issue.status)}</Badge>
        </div>
        <p className="mt-2 text-sm text-navy-300">
          Workload{' '}
          <Link
            to={`/workloads/${issue.workload_id}`}
            className="font-medium text-healthy-700 hover:text-healthy-700"
          >
            {issue.workload_id}
          </Link>{' '}
          · Confidence {formatPercent(issue.confidence_score, { fromRatio: true })} · Detected{' '}
          {formatDateTime(issue.detected_at)}
        </p>
      </header>

      {/* Anomaly result + LLM explanation */}
      <section className="card p-6">
        <p className="eyebrow">Detection summary</p>
        <p className="mt-2 text-sm leading-relaxed text-navy-100">{issue.llm_user_explanation}</p>
        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-navy-400">ML model</dt>
            <dd className="mt-0.5 font-medium text-navy-50">{issue.ml_result.model_name}</dd>
          </div>
          <div>
            <dt className="text-xs text-navy-400">Anomaly score</dt>
            <dd className="mt-0.5 font-medium tabular-nums text-navy-50">
              {issue.ml_result.anomaly_score.toFixed(3)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-navy-400">Anomaly</dt>
            <dd className="mt-0.5">
              <Badge tone={issue.ml_result.is_anomaly ? 'high' : 'low'}>
                {issue.ml_result.is_anomaly ? 'Detected' : 'Within range'}
              </Badge>
            </dd>
          </div>
        </dl>
      </section>

      {/* XAI explanation */}
      <XAICard explanation={issue.xai_explanation} />

      {/* Next Best Action: recommendation + forecast + CTA */}
      {recState.kind === 'loading' && (
        <div className="card p-8 text-center text-sm text-navy-300">
          Generating recommendation…
        </div>
      )}

      {recState.kind === 'error' && (
        <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
          Failed to load recommendation: {recState.message}
          <button
            type="button"
            onClick={reload}
            className="ml-3 rounded-md bg-navy-700 px-3 py-1 text-xs font-medium text-navy-50 hover:bg-navy-600"
          >
            Retry
          </button>
        </div>
      )}

      {recState.kind === 'unavailable' && (
        <section className="card p-6">
          <p className="eyebrow">Next Best Action</p>
          <h2 className="mt-1 text-lg font-semibold text-navy-50">No recommendation yet</h2>
          <p className="mt-2 max-w-prose text-sm text-navy-300">{recState.reason}</p>
          <button
            type="button"
            onClick={reload}
            className="mt-4 rounded-lg bg-healthy-600 px-4 py-2 text-sm font-semibold text-white hover:bg-healthy-500"
          >
            Generate recommendation
          </button>
        </section>
      )}

      {recState.kind === 'ready' && (
        <>
          <RecommendationCTA rec={recState.rec} onNavigate={navigate} />
          <OptimizationForecast forecast={recState.rec.optimization_impact_forecast} />
        </>
      )}
    </div>
  )
}

interface RecommendationCTAProps {
  rec: Recommendation
  onNavigate: (to: string) => void
}

/** Recommended-action summary with execution mode and a context-aware CTA. */
function RecommendationCTA({ rec, onNavigate }: RecommendationCTAProps) {
  const mode = EXECUTION_MODE[rec.required_execution_mode]
  const Icon = mode.icon
  const target = rec.required_execution_mode === 'auto_fix' ? '/reports' : '/approvals'

  return (
    <section className="card p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Next Best Action</p>
          <h2 className="mt-1 text-lg font-semibold text-navy-50">{rec.recommended_action}</h2>
        </div>
        <Badge tone={mode.tone}>
          <Icon className="h-3.5 w-3.5" aria-hidden /> {mode.label}
        </Badge>
      </div>

      <p className="mt-3 max-w-prose text-sm leading-relaxed text-navy-200">
        {rec.llm_recommendation_explanation}
      </p>

      <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-navy-400">Category</dt>
          <dd className="mt-0.5 font-medium text-navy-50">{humanize(rec.action_category)}</dd>
        </div>
        <div>
          <dt className="text-xs text-navy-400">Risk level</dt>
          <dd className="mt-0.5">
            <Badge tone={severityTone(rec.risk_level)} uppercase>
              {rec.risk_level}
            </Badge>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-navy-400">Triggered rule</dt>
          <dd className="mt-0.5 font-mono text-xs text-navy-100">{rec.rule_triggered.rule_id}</dd>
        </div>
        <div>
          <dt className="text-xs text-navy-400">Forecast model</dt>
          <dd className="mt-0.5 font-medium text-navy-50">{rec.forecast_model_result.model_name}</dd>
        </div>
      </dl>

      {rec.rollback_note && (
        <p className="mt-4 rounded-lg bg-navy-900/60 px-3 py-2 text-xs text-navy-300 ring-1 ring-inset ring-navy-700">
          <span className="font-medium text-navy-100">Rollback:</span> {rec.rollback_note}
        </p>
      )}

      <button
        type="button"
        onClick={() => onNavigate(target)}
        className="mt-5 inline-flex items-center gap-2 rounded-lg bg-healthy-600 px-4 py-2 text-sm font-semibold text-white hover:bg-healthy-500"
      >
        <Icon className="h-4 w-4" aria-hidden /> {mode.cta}
      </button>
    </section>
  )
}
