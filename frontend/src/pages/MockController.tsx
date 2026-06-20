import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CheckCircle2,
  PlayCircle,
  Radio,
  RotateCcw,
  StopCircle,
  XCircle,
  Zap,
} from 'lucide-react'
import {
  getMockScenarios,
  getMockStatus,
  resetMock,
  startMockStream,
  stopMockStream,
  triggerMockScenario,
} from '../api/endpoints'
import type { MockScenario, MockStatus } from '../api/endpoints'
import { ApiError } from '../api/client'
import { useWorkloads } from '../hooks/useWorkloads'
import { POLLING_INTERVALS } from '../lib/constants'
import Badge from '../components/ui/Badge'

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Unexpected error'
}

/** Toast-style feedback shown after an action. */
type Feedback = { kind: 'success' | 'error'; message: string }

/** Map an execution-path string to a Badge tone (escalation = critical). */
function pathTone(path: string | null): 'critical' | 'medium' | 'neutral' {
  if (!path) return 'neutral'
  if (path.includes('escalation')) return 'critical'
  if (path.includes('approval') || path.includes('user')) return 'medium'
  return 'neutral'
}

/** Humanize a snake_case identifier for display (e.g. "auto_fix" → "Auto fix"). */
function humanize(value: string | null): string {
  if (!value) return '—'
  const spaced = value.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export default function MockController() {
  const { data: workloads } = useWorkloads()

  const [scenarios, setScenarios] = useState<MockScenario[]>([])
  const [scenariosLoading, setScenariosLoading] = useState(true)
  const [scenariosError, setScenariosError] = useState<string | null>(null)

  const [status, setStatus] = useState<MockStatus | null>(null)

  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [busyScenario, setBusyScenario] = useState<string | null>(null)
  const [streamBusy, setStreamBusy] = useState(false)
  const [resetBusy, setResetBusy] = useState(false)

  const activeRef = useRef(true)

  // Map workload_id → display name for friendlier scenario targets.
  const workloadNames = useMemo(() => {
    const map = new Map<string, string>()
    workloads?.forEach((w) => map.set(w.workload_id, w.workload_name))
    return map
  }, [workloads])

  const targetName = (id: string | null) =>
    (id && workloadNames.get(id)) || id || '—'

  // Load scenarios once on mount.
  useEffect(() => {
    activeRef.current = true
    ;(async () => {
      try {
        const data = await getMockScenarios()
        if (activeRef.current) {
          setScenarios(data)
          setScenariosError(null)
        }
      } catch (err) {
        if (activeRef.current) setScenariosError(errorMessage(err))
      } finally {
        if (activeRef.current) setScenariosLoading(false)
      }
    })()
    return () => {
      activeRef.current = false
    }
  }, [])

  // Poll the stream status so the toggle reflects live `streaming` state.
  const loadStatus = useCallback(async () => {
    try {
      const data = await getMockStatus()
      if (activeRef.current) setStatus(data)
    } catch {
      // Status polling failures are non-fatal; keep the last known state.
    }
  }, [])

  useEffect(() => {
    loadStatus()
    const id = window.setInterval(loadStatus, POLLING_INTERVALS.mockStatus)
    return () => window.clearInterval(id)
  }, [loadStatus])

  const streaming = status?.streaming ?? false

  const handleTrigger = async (scenario: MockScenario) => {
    setBusyScenario(scenario.scenario_id)
    setFeedback(null)
    try {
      const result = await triggerMockScenario(scenario.scenario_id)
      setFeedback({
        kind: 'success',
        message: `Triggered "${scenario.name ?? scenario.scenario_id}" on ${targetName(
          result.workload_id,
        )}. Expected path: ${humanize(result.expected_execution_path)}.`,
      })
    } catch (err) {
      setFeedback({ kind: 'error', message: errorMessage(err) })
    } finally {
      setBusyScenario(null)
    }
  }

  const handleToggleStream = async () => {
    setStreamBusy(true)
    setFeedback(null)
    try {
      if (streaming) {
        const result = await stopMockStream()
        setStatus((s) => (s ? { ...s, streaming: result.streaming } : s))
        setFeedback({
          kind: 'success',
          message: result.stopped
            ? 'Telemetry stream stopped.'
            : 'Telemetry stream was not running.',
        })
      } else {
        const result = await startMockStream()
        setStatus((s) => (s ? { ...s, streaming: result.streaming } : s))
        setFeedback({
          kind: 'success',
          message: result.started
            ? 'Telemetry stream started.'
            : 'Telemetry stream already running.',
        })
      }
      await loadStatus()
    } catch (err) {
      setFeedback({ kind: 'error', message: errorMessage(err) })
    } finally {
      setStreamBusy(false)
    }
  }

  const handleReset = async () => {
    setResetBusy(true)
    setFeedback(null)
    try {
      const result = await resetMock()
      setFeedback({
        kind: 'success',
        message: `Reset to healthy baseline — ${result.baseline_snapshots} snapshot(s) emitted.`,
      })
      await loadStatus()
    } catch (err) {
      setFeedback({ kind: 'error', message: errorMessage(err) })
    } finally {
      setResetBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center gap-3">
        <Zap className="h-6 w-6 text-warning-700" aria-hidden />
        <div>
          <p className="eyebrow">Clover · Demo Console</p>
          <h1 className="mt-1 text-2xl font-semibold text-navy-50">Mock Controller</h1>
          <p className="mt-1 text-sm text-navy-300">
            Inject engineered scenarios to drive the detection-to-remediation
            pipeline, stream healthy telemetry, or reset everything to green.
          </p>
        </div>
      </header>

      {/* Control bar: stream toggle + reset + live status */}
      <div className="card flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Radio
            className={[
              'h-5 w-5',
              streaming ? 'text-healthy-700 animate-pulse' : 'text-navy-500',
            ].join(' ')}
            aria-hidden
          />
          <div>
            <p className="text-sm font-semibold text-navy-50">Telemetry stream</p>
            <p className="text-xs text-navy-300">
              {streaming ? (
                <span className="text-healthy-700">
                  Live — emitting every{' '}
                  {status?.stream_interval_seconds?.[0] ?? 3}–
                  {status?.stream_interval_seconds?.[1] ?? 10}s
                </span>
              ) : (
                'Stopped'
              )}
            </p>
          </div>
          <Badge tone={streaming ? 'low' : 'neutral'} uppercase>
            {streaming ? 'Streaming' : 'Idle'}
          </Badge>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleToggleStream}
            disabled={streamBusy}
            className={[
              'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50',
              streaming
                ? 'bg-critical-500 text-white hover:bg-critical-400'
                : 'bg-healthy-500 text-navy-950 hover:bg-healthy-400',
            ].join(' ')}
          >
            {streaming ? (
              <StopCircle className="h-4 w-4" aria-hidden />
            ) : (
              <PlayCircle className="h-4 w-4" aria-hidden />
            )}
            {streamBusy
              ? 'Working…'
              : streaming
                ? 'Stop stream'
                : 'Start stream'}
          </button>

          <button
            type="button"
            onClick={handleReset}
            disabled={resetBusy}
            className="inline-flex items-center gap-2 rounded-lg border border-navy-600 px-4 py-2 text-sm font-medium text-navy-100 transition-colors hover:bg-navy-900 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RotateCcw className="h-4 w-4" aria-hidden />
            {resetBusy ? 'Resetting…' : 'Reset to healthy'}
          </button>
        </div>
      </div>

      {/* Action feedback */}
      {feedback && (
        <div
          role="status"
          className={[
            'card flex items-start gap-2.5 p-4 text-sm',
            feedback.kind === 'success'
              ? 'border-healthy-700/50 bg-healthy-900/20 text-healthy-700'
              : 'border-critical-700/50 bg-critical-900/20 text-critical-700',
          ].join(' ')}
        >
          {feedback.kind === 'success' ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          ) : (
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          )}
          <span>{feedback.message}</span>
        </div>
      )}

      {/* Scenario grid */}
      {scenariosError ? (
        <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
          Failed to load scenarios: {scenariosError}
        </div>
      ) : scenariosLoading ? (
        <div className="card p-10 text-center text-sm text-navy-300">
          Loading demo scenarios…
        </div>
      ) : scenarios.length === 0 ? (
        <div className="card p-10 text-center text-sm text-navy-300">
          No demo scenarios are available.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {scenarios.map((scenario) => {
            const triggered =
              status?.triggered_scenarios?.includes(scenario.scenario_id) ?? false
            const busy = busyScenario === scenario.scenario_id
            return (
              <div
                key={scenario.scenario_id}
                className="card flex flex-col gap-3 p-5"
              >
                <div className="flex items-start justify-between gap-2">
                  <h2 className="text-sm font-semibold text-navy-50">
                    {scenario.name ?? scenario.scenario_id}
                  </h2>
                  {triggered && (
                    <Badge tone="low" uppercase>
                      Triggered
                    </Badge>
                  )}
                </div>

                <p className="text-xs leading-relaxed text-navy-300">
                  {scenario.description ?? 'No description provided.'}
                </p>

                <dl className="flex flex-col gap-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-navy-400">Target workload</dt>
                    <dd className="font-medium text-navy-100">
                      {targetName(scenario.target_workload_id)}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-navy-400">Expected issue</dt>
                    <dd>
                      <Badge tone="neutral">
                        {humanize(scenario.expected_issue_type)}
                      </Badge>
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-navy-400">Execution path</dt>
                    <dd>
                      <Badge tone={pathTone(scenario.expected_execution_path)}>
                        {humanize(scenario.expected_execution_path)}
                      </Badge>
                    </dd>
                  </div>
                </dl>

                <button
                  type="button"
                  onClick={() => handleTrigger(scenario)}
                  disabled={busy}
                  className="mt-1 inline-flex items-center justify-center gap-2 rounded-lg bg-warning-500 px-4 py-2 text-sm font-semibold text-navy-950 transition-colors hover:bg-warning-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Zap className="h-4 w-4" aria-hidden />
                  {busy ? 'Triggering…' : 'Trigger scenario'}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
