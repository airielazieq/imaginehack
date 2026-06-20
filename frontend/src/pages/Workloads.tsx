import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWorkloads } from '../hooks/useWorkloads'
import type { Workload, WorkloadStatus, WorkflowCriticality } from '../types'
import DataTable, { type Column } from '../components/ui/DataTable'
import Badge, { type BadgeTone } from '../components/ui/Badge'

/** Turn a snake_case enum value into a readable label. */
function humanize(value: string): string {
  return value
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

// Status → badge tone. Healthy maps to the low (green) tone; degraded states
// escalate through the severity palette so the table reads at a glance.
const STATUS_TONE: Record<WorkloadStatus, BadgeTone> = {
  healthy: 'low',
  warning: 'medium',
  critical: 'critical',
  unreachable: 'high',
}

// Criticality → badge tone (mirrors the severity palette polarity).
const CRITICALITY_TONE: Record<WorkflowCriticality, BadgeTone> = {
  critical: 'critical',
  high: 'high',
  medium: 'medium',
  low: 'low',
}

// Higher rank = more urgent, so the table can sort status/criticality semantically.
const STATUS_RANK: Record<WorkloadStatus, number> = {
  critical: 4,
  unreachable: 3,
  warning: 2,
  healthy: 1,
}

const CRITICALITY_RANK: Record<WorkflowCriticality, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
}

export default function Workloads() {
  const navigate = useNavigate()
  const { data: workloads, loading, error } = useWorkloads()

  const columns = useMemo<Column<Workload>[]>(
    () => [
      {
        key: 'name',
        header: 'Workload',
        accessor: (w) => w.workload_name,
        render: (w) => (
          <div className="flex flex-col">
            <span className="font-medium text-navy-50">{w.workload_name}</span>
            <span className="text-xs text-navy-400">
              {humanize(w.construction_workflow)}
            </span>
          </div>
        ),
        sortable: true,
      },
      {
        key: 'type',
        header: 'Type',
        accessor: (w) => w.cloud_service_type,
        render: (w) => (
          <div className="flex flex-col">
            <span>{humanize(w.cloud_service_type)}</span>
            <span className="text-xs text-navy-400">{w.workload_type}</span>
          </div>
        ),
        sortable: true,
      },
      {
        key: 'environment',
        header: 'Environment',
        accessor: (w) => w.environment,
        render: (w) => <Badge>{humanize(w.environment)}</Badge>,
        sortable: true,
      },
      {
        key: 'region',
        header: 'Region',
        accessor: (w) => w.region,
        sortable: true,
      },
      {
        key: 'owner_team',
        header: 'Owner',
        accessor: (w) => w.owner_team,
        sortable: true,
      },
      {
        key: 'criticality',
        header: 'Criticality',
        accessor: (w) => CRITICALITY_RANK[w.workflow_criticality] ?? 0,
        render: (w) => (
          <Badge tone={CRITICALITY_TONE[w.workflow_criticality] ?? 'neutral'} uppercase>
            {w.workflow_criticality}
          </Badge>
        ),
        sortable: true,
      },
      {
        key: 'status',
        header: 'Status',
        accessor: (w) => STATUS_RANK[w.status] ?? 0,
        render: (w) => (
          <Badge tone={STATUS_TONE[w.status] ?? 'neutral'} uppercase>
            {w.status}
          </Badge>
        ),
        sortable: true,
      },
    ],
    [],
  )

  return (
    <div className="flex flex-col gap-6">
      <header>
        <p className="eyebrow">Clover · Inventory</p>
        <h1 className="mt-2 text-2xl font-semibold text-navy-50">Workloads</h1>
        <p className="mt-1 text-sm text-navy-300">
          Every monitored workload, with environment, criticality, and current health.
        </p>
      </header>

      {error ? (
        <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
          Failed to load workloads: {error}
        </div>
      ) : loading ? (
        <div className="card p-10 text-center text-sm text-navy-300">
          Loading workloads…
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={workloads ?? []}
          getRowId={(w) => w.workload_id}
          onRowClick={(w) => navigate(`/workloads/${w.workload_id}`)}
          enableSearch
          searchPlaceholder="Search workloads…"
          emptyMessage="No workloads found."
        />
      )}
    </div>
  )
}
