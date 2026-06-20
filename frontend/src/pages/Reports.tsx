import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Undo2 } from 'lucide-react'
import {
  getRecentActions,
  getRemediationReport,
  getSavingsSummary,
  type RecentAction,
  type SavingsSummary,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { useWorkloads } from '../hooks/useWorkloads'
import type { RemediationResult } from '../types'
import { formatNumber } from '../lib/formatters'
import DataTable, { type Column } from '../components/ui/DataTable'
import Badge from '../components/ui/Badge'
import SavingsBadge from '../components/cards/SavingsBadge'
import RemediationReport, {
  executionPathTone,
  executionStatusTone,
  verificationTone,
} from '../components/workflow/RemediationReport'

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Unexpected error'
}

/** Turn a snake_case enum value into a readable label. */
function humanize(value: string): string {
  return value
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export default function Reports() {
  const [actions, setActions] = useState<RecentAction[] | null>(null)
  const [savings, setSavings] = useState<SavingsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Drill-in state for the selected remediation report.
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [report, setReport] = useState<RemediationResult | null>(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportError, setReportError] = useState<string | null>(null)

  const { data: workloads } = useWorkloads()

  const workloadNames = useMemo(() => {
    const map = new Map<string, string>()
    workloads?.forEach((w) => map.set(w.workload_id, w.workload_name))
    return map
  }, [workloads])

  const workloadLabel = useCallback(
    (id: string) => workloadNames.get(id) ?? id,
    [workloadNames],
  )

  // Load the recent-actions feed and savings rollup together.
  useEffect(() => {
    let active = true
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const [recent, savingsSummary] = await Promise.all([
          getRecentActions(),
          getSavingsSummary(),
        ])
        if (active) {
          setActions(recent)
          setSavings(savingsSummary)
          setLoading(false)
        }
      } catch (err) {
        if (active) {
          setError(errorMessage(err))
          setLoading(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [])

  // Fetch the full report whenever a remediation is selected.
  useEffect(() => {
    if (!selectedId) {
      setReport(null)
      return
    }
    let active = true
    ;(async () => {
      setReportLoading(true)
      setReportError(null)
      try {
        const result = await getRemediationReport(selectedId)
        if (active) {
          setReport(result)
          setReportLoading(false)
        }
      } catch (err) {
        if (active) {
          setReportError(errorMessage(err))
          setReportLoading(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [selectedId])

  const columns = useMemo<Column<RecentAction>[]>(
    () => [
      {
        key: 'workload',
        header: 'Workload',
        accessor: (a) => workloadLabel(a.workload_id),
        render: (a) => (
          <span className="font-medium text-navy-50">{workloadLabel(a.workload_id)}</span>
        ),
        sortable: true,
      },
      {
        key: 'execution_path',
        header: 'Path',
        accessor: (a) => a.execution_path,
        render: (a) => (
          <Badge tone={executionPathTone(a.execution_path)} uppercase>
            {humanize(a.execution_path)}
          </Badge>
        ),
        sortable: true,
      },
      {
        key: 'execution_status',
        header: 'Status',
        accessor: (a) => a.execution_status,
        render: (a) => (
          <Badge tone={executionStatusTone(a.execution_status)} uppercase>
            {humanize(a.execution_status)}
          </Badge>
        ),
        sortable: true,
      },
      {
        key: 'verification',
        header: 'Verification',
        accessor: (a) => a.verification_result ?? '',
        render: (a) =>
          a.verification_result ? (
            <Badge tone={verificationTone(a.verification_result)} uppercase>
              {a.verification_result}
            </Badge>
          ) : (
            <span className="text-navy-400">—</span>
          ),
        sortable: true,
      },
      {
        key: 'rollback',
        header: 'Rollback',
        accessor: (a) => (a.rollback_triggered ? 1 : 0),
        render: (a) =>
          a.rollback_triggered ? (
            <Badge tone="high" uppercase>
              <Undo2 className="h-3 w-3" aria-hidden /> Yes
            </Badge>
          ) : (
            <span className="text-navy-400">No</span>
          ),
        sortable: true,
      },
      {
        key: 'remediation_id',
        header: 'Remediation ID',
        accessor: (a) => a.remediation_id,
        render: (a) => (
          <span className="font-mono text-xs text-navy-300">{a.remediation_id}</span>
        ),
        sortable: true,
      },
    ],
    [workloadLabel],
  )

  // --- Detail (drill-in) view -------------------------------------------- //
  if (selectedId) {
    return (
      <div className="flex flex-col gap-6">
        <header>
          <button
            type="button"
            onClick={() => setSelectedId(null)}
            className="inline-flex items-center gap-1.5 text-sm text-navy-300 transition-colors hover:text-navy-50"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden /> Back to reports
          </button>
          <h1 className="mt-3 text-2xl font-semibold text-navy-50">Remediation Report</h1>
        </header>

        {reportError ? (
          <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
            Failed to load report: {reportError}
          </div>
        ) : reportLoading || !report ? (
          <div className="card p-10 text-center text-sm text-navy-300">
            Loading report…
          </div>
        ) : (
          <RemediationReport
            report={report}
            workloadName={workloadLabel(report.workload_id)}
          />
        )}
      </div>
    )
  }

  // --- List view --------------------------------------------------------- //
  return (
    <div className="flex flex-col gap-6">
      <header>
        <p className="eyebrow">Clover · Self-Healing</p>
        <h1 className="mt-2 text-2xl font-semibold text-navy-50">Reports</h1>
        <p className="mt-1 text-sm text-navy-300">
          Completed remediation actions and projected savings across your workloads.
        </p>
      </header>

      {/* Savings rollup */}
      {savings && (
        <div className="card flex flex-wrap items-center justify-between gap-4 p-5">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-navy-400">
              Projected 30-day savings
            </p>
            <p className="mt-1 text-sm text-navy-300">
              Across {formatNumber(savings.recommendation_count)} open recommendation
              {savings.recommendation_count === 1 ? '' : 's'}
            </p>
          </div>
          <SavingsBadge savings={savings.projected_savings} />
        </div>
      )}

      {error ? (
        <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
          Failed to load reports: {error}
        </div>
      ) : loading ? (
        <div className="card p-10 text-center text-sm text-navy-300">
          Loading reports…
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={actions ?? []}
          getRowId={(a) => a.remediation_id}
          onRowClick={(a) => setSelectedId(a.remediation_id)}
          enableSearch
          searchPlaceholder="Search remediations…"
          emptyMessage="No remediation reports yet. Trigger a scenario to generate one."
        />
      )}
    </div>
  )
}
