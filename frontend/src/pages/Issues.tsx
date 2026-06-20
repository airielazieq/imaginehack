import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useIssues } from '../hooks/useIssues'
import { useWorkloads } from '../hooks/useWorkloads'
import type { IssueFilters } from '../api/endpoints'
import type { Issue, Severity } from '../types'
import { formatDateTime, formatPercent } from '../lib/formatters'
import DataTable, { type Column } from '../components/ui/DataTable'
import Badge, { severityTone } from '../components/ui/Badge'

// Filter option sets (mirror backend literals — see design.md §Issue schema).
const ISSUE_TYPES = [
  'public_storage',
  'critical_exposed_vulnerability',
  'idle_or_overprovisioned_workload',
  'carbon_heavy_workload',
  'no_monitoring',
  'high_error_rate',
  'cost_spike_or_waste',
] as const

const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low']

const ISSUE_CATEGORIES = [
  'security',
  'cost',
  'energy',
  'carbon',
  'performance',
  'monitoring',
  'cost_energy_carbon',
] as const

// Higher rank = more urgent, so the table can sort severity semantically.
const SEVERITY_RANK: Record<Severity, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
}

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
  options: readonly string[]
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
          <option key={opt} value={opt}>
            {humanize(opt)}
          </option>
        ))}
      </select>
    </label>
  )
}

export default function Issues() {
  const navigate = useNavigate()

  const [issueType, setIssueType] = useState('')
  const [severity, setSeverity] = useState('')
  const [category, setCategory] = useState('')

  // Build a stable filter object; omit empty selections.
  const filters = useMemo<IssueFilters | undefined>(() => {
    const f: IssueFilters = {}
    if (issueType) f.issue_type = issueType
    if (severity) f.severity = severity
    if (category) f.issue_category = category
    return Object.keys(f).length > 0 ? f : undefined
  }, [issueType, severity, category])

  const { data: issues, loading, error } = useIssues(filters)
  const { data: workloads } = useWorkloads()

  // Map workload_id → display name for the first column.
  const workloadNames = useMemo(() => {
    const map = new Map<string, string>()
    workloads?.forEach((w) => map.set(w.workload_id, w.workload_name))
    return map
  }, [workloads])

  const workloadName = (issue: Issue) =>
    workloadNames.get(issue.workload_id) ?? issue.workload_id

  const columns = useMemo<Column<Issue>[]>(
    () => [
      {
        key: 'workload',
        header: 'Workload',
        accessor: (i) => workloadName(i),
        render: (i) => (
          <span className="font-medium text-navy-50">{workloadName(i)}</span>
        ),
        sortable: true,
      },
      {
        key: 'issue_type',
        header: 'Type',
        accessor: (i) => i.issue_type,
        render: (i) => humanize(i.issue_type),
        sortable: true,
      },
      {
        key: 'severity',
        header: 'Severity',
        accessor: (i) => SEVERITY_RANK[i.severity] ?? 0,
        render: (i) => (
          <Badge tone={severityTone(i.severity)} uppercase>
            {i.severity}
          </Badge>
        ),
        sortable: true,
      },
      {
        key: 'confidence',
        header: 'Confidence',
        accessor: (i) => i.confidence_score,
        render: (i) => formatPercent(i.confidence_score, { fromRatio: true }),
        sortable: true,
      },
      {
        key: 'detected_at',
        header: 'Detected',
        accessor: (i) => i.detected_at,
        render: (i) => formatDateTime(i.detected_at),
        sortable: true,
      },
    ],
    // workloadNames drives the workload column label; include it as a dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workloadNames],
  )

  return (
    <div className="flex flex-col gap-6">
      <header>
        <p className="eyebrow">Clover · Detection</p>
        <h1 className="mt-2 text-2xl font-semibold text-navy-50">Issues</h1>
        <p className="mt-1 text-sm text-navy-300">
          All active issues detected across your workloads.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-4">
        <FilterSelect
          label="Issue type"
          value={issueType}
          options={ISSUE_TYPES}
          onChange={setIssueType}
        />
        <FilterSelect
          label="Severity"
          value={severity}
          options={SEVERITIES}
          onChange={setSeverity}
        />
        <FilterSelect
          label="Category"
          value={category}
          options={ISSUE_CATEGORIES}
          onChange={setCategory}
        />
      </div>

      {error ? (
        <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
          Failed to load issues: {error}
        </div>
      ) : loading ? (
        <div className="card p-10 text-center text-sm text-navy-300">
          Loading issues…
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={issues ?? []}
          getRowId={(i) => i.issue_id}
          onRowClick={(i) => navigate(`/issues/${i.issue_id}`)}
          emptyMessage="No issues match the current filters."
        />
      )}
    </div>
  )
}
