import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { useAuditLogs } from '../hooks/useAuditLogs'
import { useWorkloads } from '../hooks/useWorkloads'
import type { AuditLogFilters } from '../api/endpoints'
import type { AuditLog } from '../types'
import { formatDateTime } from '../lib/formatters'
import DataTable, { type Column } from '../components/ui/DataTable'
import Badge from '../components/ui/Badge'
import Modal from '../components/ui/Modal'

// Known audit event types written by the backend audit service
// (see backend/services/audit_service.py). Drives the event-type filter.
const EVENT_TYPES = [
  'issue_detected',
  'recommendation_generated',
  'remediation_completed',
  'score_updated',
  'rollback_triggered',
] as const

/** Turn a snake_case enum value into a readable label. */
function humanize(value: string): string {
  return value
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

interface FilterSelectProps {
  label: string
  value: string
  options: readonly { value: string; label: string }[]
  onChange: (value: string) => void
}

function FilterSelect({ label, value, options, onChange }: FilterSelectProps) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-navy-300">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-[12rem] rounded-lg border border-navy-700 bg-navy-900 px-3 py-2 text-sm text-navy-100 focus:border-healthy-500 focus:outline-none"
      >
        <option value="">All</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  )
}

interface DateFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
}

function DateField({ label, value, onChange }: DateFieldProps) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-navy-300">
      {label}
      <input
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-[10rem] rounded-lg border border-navy-700 bg-navy-900 px-3 py-2 text-sm text-navy-100 focus:border-healthy-500 focus:outline-none"
      />
    </label>
  )
}

/** Small reference chip for an entity id (issue / recommendation / remediation). */
function RefChip({
  prefix,
  id,
  onClick,
}: {
  prefix: string
  id: string
  onClick?: () => void
}) {
  const className =
    'inline-flex items-center gap-1 rounded-md bg-navy-900 px-1.5 py-0.5 font-mono text-[11px] text-navy-200 ring-1 ring-inset ring-navy-700'
  if (onClick) {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onClick()
        }}
        className={`${className} transition-colors hover:text-navy-50 hover:ring-healthy-500/40`}
        title={`${prefix}: ${id}`}
      >
        {prefix} {id.slice(0, 8)}
      </button>
    )
  }
  return (
    <span className={className} title={`${prefix}: ${id}`}>
      {prefix} {id.slice(0, 8)}
    </span>
  )
}

/** Render a previous → new status transition, or a dash when none applies. */
function StatusTransition({ log }: { log: AuditLog }) {
  if (!log.previous_status && !log.new_status) {
    return <span className="text-navy-500">—</span>
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className="text-navy-300">{log.previous_status ?? '∅'}</span>
      <ArrowRight className="h-3 w-3 text-navy-500" aria-hidden />
      <span className="font-medium text-navy-50">{log.new_status ?? '∅'}</span>
    </span>
  )
}

export default function AuditLogs() {
  const navigate = useNavigate()

  const [workloadId, setWorkloadId] = useState('')
  const [eventType, setEventType] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selected, setSelected] = useState<AuditLog | null>(null)

  // Build a stable filter object; omit empty selections. Date inputs are
  // YYYY-MM-DD; the backend accepts ISO date strings for range bounds.
  const filters = useMemo<AuditLogFilters | undefined>(() => {
    const f: AuditLogFilters = {}
    if (workloadId) f.workload_id = workloadId
    if (eventType) f.event_type = eventType
    if (startDate) f.start_date = startDate
    if (endDate) f.end_date = endDate
    return Object.keys(f).length > 0 ? f : undefined
  }, [workloadId, eventType, startDate, endDate])

  const { data: logs, loading, error } = useAuditLogs(filters)
  const { data: workloads } = useWorkloads()

  // Map workload_id → display name for the workload column + filter.
  const workloadNames = useMemo(() => {
    const map = new Map<string, string>()
    workloads?.forEach((w) => map.set(w.workload_id, w.workload_name))
    return map
  }, [workloads])

  const workloadName = (id: string) => workloadNames.get(id) ?? id

  const workloadOptions = useMemo(
    () =>
      (workloads ?? []).map((w) => ({
        value: w.workload_id,
        label: w.workload_name,
      })),
    [workloads],
  )

  const eventTypeOptions = useMemo(
    () => EVENT_TYPES.map((t) => ({ value: t, label: humanize(t) })),
    [],
  )

  const hasFilters = Boolean(filters)
  const resetFilters = () => {
    setWorkloadId('')
    setEventType('')
    setStartDate('')
    setEndDate('')
  }

  const columns = useMemo<Column<AuditLog>[]>(
    () => [
      {
        key: 'timestamp',
        header: 'Timestamp',
        accessor: (l) => l.timestamp,
        render: (l) => (
          <span className="whitespace-nowrap text-navy-200">
            {formatDateTime(l.timestamp)}
          </span>
        ),
        sortable: true,
      },
      {
        key: 'event_type',
        header: 'Event',
        accessor: (l) => l.event_type,
        render: (l) => <Badge>{humanize(l.event_type)}</Badge>,
        sortable: true,
      },
      {
        key: 'actor',
        header: 'Actor',
        accessor: (l) => l.actor,
        render: (l) => <span className="text-navy-200">{humanize(l.actor)}</span>,
        sortable: true,
      },
      {
        key: 'workload',
        header: 'Workload',
        accessor: (l) => workloadName(l.workload_id),
        render: (l) => (
          <span className="font-medium text-navy-50">
            {workloadName(l.workload_id)}
          </span>
        ),
        sortable: true,
      },
      {
        key: 'status',
        header: 'Status Change',
        accessor: (l) => l.new_status ?? '',
        render: (l) => <StatusTransition log={l} />,
        sortable: true,
      },
      {
        key: 'references',
        header: 'References',
        render: (l) => {
          const refs: ReactNode[] = []
          if (l.issue_id) {
            refs.push(
              <RefChip
                key="issue"
                prefix="Issue"
                id={l.issue_id}
                onClick={() => navigate(`/issues/${l.issue_id}`)}
              />,
            )
          }
          if (l.recommendation_id) {
            refs.push(
              <RefChip key="rec" prefix="Rec" id={l.recommendation_id} />,
            )
          }
          if (l.remediation_id) {
            refs.push(
              <RefChip key="rem" prefix="Rem" id={l.remediation_id} />,
            )
          }
          return refs.length > 0 ? (
            <span className="flex flex-wrap items-center gap-1.5">{refs}</span>
          ) : (
            <span className="text-navy-500">—</span>
          )
        },
      },
    ],
    // workloadNames drives the workload column/filter labels.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workloadNames],
  )

  return (
    <div className="flex flex-col gap-6">
      <header>
        <p className="eyebrow">Clover · Governance</p>
        <h1 className="mt-2 text-2xl font-semibold text-navy-50">Audit Logs</h1>
        <p className="mt-1 text-sm text-navy-300">
          An append-only, immutable trail of every platform state transition.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-4">
        <FilterSelect
          label="Workload"
          value={workloadId}
          options={workloadOptions}
          onChange={setWorkloadId}
        />
        <FilterSelect
          label="Event type"
          value={eventType}
          options={eventTypeOptions}
          onChange={setEventType}
        />
        <DateField label="From" value={startDate} onChange={setStartDate} />
        <DateField label="To" value={endDate} onChange={setEndDate} />
        {hasFilters && (
          <button
            type="button"
            onClick={resetFilters}
            className="rounded-lg border border-navy-700 px-3 py-2 text-sm text-navy-200 transition-colors hover:border-healthy-500 hover:text-navy-50"
          >
            Clear filters
          </button>
        )}
      </div>

      {error ? (
        <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
          Failed to load audit logs: {error}
        </div>
      ) : loading ? (
        <div className="card p-10 text-center text-sm text-navy-300">
          Loading audit logs…
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={logs ?? []}
          getRowId={(l) => l.audit_id}
          onRowClick={(l) => setSelected(l)}
          enableSearch
          searchPlaceholder="Search audit trail…"
          emptyMessage="No audit entries match the current filters."
        />
      )}

      <Modal
        open={selected != null}
        title="Audit Entry"
        onClose={() => setSelected(null)}
      >
        {selected && <AuditDetail log={selected} workloadName={workloadName} />}
      </Modal>
    </div>
  )
}

/** Read-only detail view for a single audit entry (immutable record). */
function AuditDetail({
  log,
  workloadName,
}: {
  log: AuditLog
  workloadName: (id: string) => string
}) {
  const rows: { label: string; value: ReactNode }[] = [
    { label: 'Audit ID', value: <span className="font-mono text-xs">{log.audit_id}</span> },
    { label: 'Event', value: <Badge>{humanize(log.event_type)}</Badge> },
    { label: 'Actor', value: humanize(log.actor) },
    { label: 'Workload', value: workloadName(log.workload_id) },
    { label: 'Timestamp', value: formatDateTime(log.timestamp) },
    { label: 'Status change', value: <StatusTransition log={log} /> },
  ]
  if (log.issue_id) {
    rows.push({ label: 'Issue ID', value: <span className="font-mono text-xs">{log.issue_id}</span> })
  }
  if (log.recommendation_id) {
    rows.push({
      label: 'Recommendation ID',
      value: <span className="font-mono text-xs">{log.recommendation_id}</span>,
    })
  }
  if (log.remediation_id) {
    rows.push({
      label: 'Remediation ID',
      value: <span className="font-mono text-xs">{log.remediation_id}</span>,
    })
  }

  const hasDetails = log.details && Object.keys(log.details).length > 0

  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        {rows.map((r) => (
          <div key={r.label} className="contents">
            <dt className="text-navy-400">{r.label}</dt>
            <dd className="text-navy-100">{r.value}</dd>
          </div>
        ))}
      </dl>

      {log.rollback_note && (
        <div className="rounded-lg border border-warning-700/50 bg-warning-900/20 p-3 text-sm text-warning-700">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-warning-700">
            Rollback note
          </p>
          {log.rollback_note}
        </div>
      )}

      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-navy-400">
          Details
        </p>
        {hasDetails ? (
          <pre className="max-h-72 overflow-auto rounded-lg border border-navy-700 bg-navy-950 p-3 font-mono text-xs leading-relaxed text-navy-200">
            {JSON.stringify(log.details, null, 2)}
          </pre>
        ) : (
          <p className="text-sm text-navy-500">No additional details recorded.</p>
        )}
      </div>
    </div>
  )
}
