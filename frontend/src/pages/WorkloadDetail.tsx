import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowUpRight,
  Cpu,
  MemoryStick,
  Gauge,
  ShieldAlert,
  Leaf,
  DollarSign,
  Server,
} from 'lucide-react'
import {
  LineChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import {
  getWorkloadPrediction,
  getWorkloadTelemetry,
  getWorkloadUptime,
  getMCPLog,
  type WorkloadUptime,
  type MCPLogEntry,
} from '../api/endpoints'
import { useWorkload } from '../hooks/useWorkloads'
import { useIssues } from '../hooks/useIssues'
import type {
  DowntimePrediction as DowntimePredictionModel,
  Issue,
  TelemetrySnapshot,
  WorkloadStatus,
} from '../types'
import {
  formatCurrency,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatTime,
} from '../lib/formatters'
import Badge, { type BadgeTone, severityTone } from '../components/ui/Badge'
import DataTable, { type Column } from '../components/ui/DataTable'
import DowntimePrediction from '../components/cards/DowntimePrediction'
import UptimeBar from '../components/charts/UptimeBar'

/** Turn a snake_case enum value into a readable label. */
function humanize(value: string): string {
  return value
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

// Workload status → badge tone.
const STATUS_TONE: Record<WorkloadStatus, BadgeTone> = {
  healthy: 'low',
  warning: 'medium',
  critical: 'critical',
  unreachable: 'high',
}

const TABS = [
  'Overview',
  'Security',
  'GreenOps',
  'AI Recommendations',
  'Self-Healing',
  'MCP Activity',
] as const
type Tab = (typeof TABS)[number]

/** Bundled async state for the detail-only datasets (telemetry/uptime/etc.). */
interface DetailData {
  telemetry: TelemetrySnapshot[]
  uptime: WorkloadUptime | null
  prediction: DowntimePredictionModel | null
  mcpLog: MCPLogEntry[]
}

/**
 * Fetch the supplementary datasets for the workload detail view. Each call is
 * best-effort and independent — a failing endpoint (e.g. the not-yet-built MCP
 * log) leaves its slice empty rather than failing the whole page.
 */
function useWorkloadDetailData(id: string | undefined) {
  const [data, setData] = useState<DetailData>({
    telemetry: [],
    uptime: null,
    prediction: null,
    mcpLog: [],
  })
  const [loading, setLoading] = useState(Boolean(id))

  useEffect(() => {
    if (!id) {
      setLoading(false)
      return
    }
    let active = true
    setLoading(true)
    ;(async () => {
      const [telemetry, uptime, prediction, mcpLog] = await Promise.all([
        getWorkloadTelemetry(id, 60).catch(() => [] as TelemetrySnapshot[]),
        getWorkloadUptime(id).catch(() => null),
        getWorkloadPrediction(id).catch(() => null),
        getMCPLog(id).catch(() => [] as MCPLogEntry[]),
      ])
      if (active) {
        setData({ telemetry, uptime, prediction, mcpLog })
        setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [id])

  return { data, loading }
}

export default function WorkloadDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: workload, loading, error } = useWorkload(id)
  const { data: detail, loading: detailLoading } = useWorkloadDetailData(id)
  const { data: issues } = useIssues(id ? { workload_id: id } : undefined)
  const [tab, setTab] = useState<Tab>('Overview')

  const workloadIssues = issues ?? []

  if (loading) {
    return (
      <div className="card p-10 text-center text-sm text-navy-300">
        Loading workload…
      </div>
    )
  }

  if (error) {
    return (
      <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
        Failed to load workload: {error}
      </div>
    )
  }

  if (!workload) {
    return (
      <div className="card p-8">
        <p className="eyebrow">Clover · Workloads</p>
        <h1 className="mt-2 text-2xl font-semibold text-navy-50">Workload not found</h1>
        <p className="mt-1 text-sm text-navy-300">
          We couldn&apos;t find a workload with id <span className="font-mono">{id}</span>.
        </p>
        <Link
          to="/workloads"
          className="mt-4 inline-flex items-center gap-2 text-sm text-healthy-700 hover:text-healthy-700"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back to workloads
        </Link>
      </div>
    )
  }

  const latest = detail.telemetry[0] ?? null

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <header>
        <Link
          to="/workloads"
          className="inline-flex items-center gap-1.5 text-xs text-navy-300 hover:text-navy-50"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Workloads
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Server className="h-6 w-6 text-navy-300" aria-hidden />
          <h1 className="text-2xl font-semibold text-navy-50">{workload.workload_name}</h1>
          <Badge tone={STATUS_TONE[workload.status]} uppercase>
            {workload.status}
          </Badge>
          <Badge tone={severityTone(workload.workflow_criticality)} uppercase>
            {workload.workflow_criticality}
          </Badge>
        </div>
        <p className="mt-2 text-sm text-navy-300">
          <span className="font-mono text-navy-200">{workload.workload_id}</span> ·{' '}
          {humanize(workload.cloud_service_type)} · {humanize(workload.environment)} ·{' '}
          {workload.region} · {workload.owner_team}
        </p>
        <p className="mt-1 text-xs text-navy-400">
          Workflow: {humanize(workload.construction_workflow)}
        </p>
      </header>

      {/* Tab navigation */}
      <nav className="flex flex-wrap gap-1 border-b border-navy-700">
        {TABS.map((t) => {
          const active = t === tab
          return (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={[
                '-mb-px border-b-2 px-3.5 py-2 text-sm font-medium transition-colors',
                active
                  ? 'border-healthy-500 text-navy-50'
                  : 'border-transparent text-navy-300 hover:text-navy-50',
              ].join(' ')}
            >
              {t}
            </button>
          )
        })}
      </nav>

      {/* Tab content */}
      {tab === 'Overview' && (
        <OverviewTab
          prediction={detail.prediction}
          uptime={detail.uptime}
          latest={latest}
          loading={detailLoading}
          issues={workloadIssues}
        />
      )}
      {tab === 'Security' && (
        <SecurityTab latest={latest} issues={workloadIssues} />
      )}
      {tab === 'GreenOps' && (
        <GreenOpsTab telemetry={detail.telemetry} latest={latest} />
      )}
      {tab === 'AI Recommendations' && <RecommendationsTab issues={workloadIssues} />}
      {tab === 'Self-Healing' && <SelfHealingTab issues={workloadIssues} />}
      {tab === 'MCP Activity' && <MCPActivityTab entries={detail.mcpLog} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared presentational helpers
// ---------------------------------------------------------------------------

interface KpiProps {
  icon: typeof Cpu
  label: string
  value: string
  tone?: string
}

/** Compact metric tile used across the telemetry-driven tabs. */
function Kpi({ icon: Icon, label, value, tone = 'text-navy-50' }: KpiProps) {
  return (
    <div className="rounded-lg bg-navy-900/60 p-3 ring-1 ring-inset ring-navy-700">
      <p className="flex items-center gap-1.5 text-xs text-navy-400">
        <Icon className="h-3.5 w-3.5" aria-hidden /> {label}
      </p>
      <p className={`mt-1 text-lg font-semibold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}

/** Small section heading reused inside tabs. */
function SectionTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div>
      <p className="eyebrow">{eyebrow}</p>
      <h2 className="mt-1 text-lg font-semibold text-navy-50">{title}</h2>
    </div>
  )
}

/** Empty-state placeholder card. */
function EmptyState({ message }: { message: string }) {
  return (
    <div className="card p-8 text-center text-sm text-navy-300">{message}</div>
  )
}

// Issue category → badge tone (security/cost/etc. are not severities).
function categoryTone(category: Issue['issue_category']): BadgeTone {
  if (category === 'security') return 'high'
  if (category === 'performance') return 'medium'
  return 'neutral'
}

// ---------------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------------

interface OverviewTabProps {
  prediction: DowntimePredictionModel | null
  uptime: WorkloadUptime | null
  latest: TelemetrySnapshot | null
  loading: boolean
  issues: Issue[]
}

function OverviewTab({
  prediction,
  uptime,
  latest,
  loading,
  issues,
}: OverviewTabProps) {
  if (loading) {
    return <EmptyState message="Loading workload telemetry…" />
  }

  const topIssues = issues.slice(0, 5)

  return (
    <div className="flex flex-col gap-6">
      {prediction ? (
        <DowntimePrediction prediction={prediction} />
      ) : (
        <EmptyState message="No downtime prediction available for this workload yet." />
      )}

      {/* 90-day uptime strip */}
      <section className="card p-6">
        <SectionTitle eyebrow="Availability" title="90-day uptime" />
        <div className="mt-4">
          {uptime && uptime.segments.length > 0 ? (
            <UptimeBar
              segments={uptime.segments}
              overallUptimePercent={uptime.overall_uptime_percent}
              windowDays={uptime.window_days}
            />
          ) : (
            <p className="text-sm text-navy-300">No uptime history available.</p>
          )}
        </div>
      </section>

      {/* Latest telemetry KPIs */}
      <section className="card p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionTitle eyebrow="Telemetry" title="Latest reading" />
          {latest && (
            <span className="text-xs text-navy-400">
              {formatDateTime(latest.timestamp)}
            </span>
          )}
        </div>
        {latest ? (
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Kpi
              icon={Cpu}
              label="CPU"
              value={formatPercent(latest.cpu_usage_percent)}
            />
            <Kpi
              icon={MemoryStick}
              label="Memory"
              value={formatPercent(latest.memory_usage_percent)}
            />
            <Kpi
              icon={Gauge}
              label="Latency"
              value={`${formatNumber(latest.latency_ms)} ms`}
            />
            <Kpi
              icon={Gauge}
              label="Error rate"
              value={formatPercent(latest.error_rate_percent, { decimals: 2 })}
              tone={latest.error_rate_percent > 1 ? 'text-critical-700' : 'text-navy-50'}
            />
            <Kpi
              icon={DollarSign}
              label="Cost / hr"
              value={formatCurrency(latest.cost_per_hour, true)}
            />
          </dl>
        ) : (
          <p className="mt-4 text-sm text-navy-300">No telemetry recorded yet.</p>
        )}
      </section>

      {/* Related issues */}
      <section className="card p-6">
        <SectionTitle eyebrow="Issues" title="Related issues" />
        {topIssues.length > 0 ? (
          <ul className="mt-4 flex flex-col gap-2">
            {topIssues.map((issue) => (
              <li key={issue.issue_id}>
                <Link
                  to={`/issues/${issue.issue_id}`}
                  className="flex items-center justify-between gap-3 rounded-lg bg-navy-900/60 px-3 py-2 ring-1 ring-inset ring-navy-700 transition-colors hover:bg-navy-900"
                >
                  <span className="flex items-center gap-2 text-sm text-navy-100">
                    <Badge tone={severityTone(issue.severity)} uppercase>
                      {issue.severity}
                    </Badge>
                    {humanize(issue.issue_type)}
                  </span>
                  <ArrowUpRight className="h-4 w-4 text-navy-400" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 text-sm text-navy-300">No issues detected.</p>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Security tab
// ---------------------------------------------------------------------------

interface SecurityTabProps {
  latest: TelemetrySnapshot | null
  issues: Issue[]
}

function SecurityTab({ latest, issues }: SecurityTabProps) {
  const securityIssues = issues.filter((i) => i.issue_category === 'security')

  return (
    <div className="flex flex-col gap-6">
      <section className="card p-6">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-navy-300" aria-hidden />
          <SectionTitle eyebrow="Posture" title="Security posture" />
        </div>
        {latest ? (
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Kpi
              icon={ShieldAlert}
              label="Public exposure"
              value={latest.public_exposure ? 'Exposed' : 'Private'}
              tone={latest.public_exposure ? 'text-critical-700' : 'text-healthy-700'}
            />
            <Kpi
              icon={ShieldAlert}
              label="Public storage"
              value={latest.public_storage ? 'Public' : 'Private'}
              tone={latest.public_storage ? 'text-critical-700' : 'text-healthy-700'}
            />
            <Kpi
              icon={ShieldAlert}
              label="Vulnerability"
              value={humanize(latest.vulnerability_severity)}
              tone={
                latest.vulnerability_severity === 'critical' ||
                latest.vulnerability_severity === 'high'
                  ? 'text-critical-700'
                  : 'text-navy-50'
              }
            />
            <Kpi
              icon={ShieldAlert}
              label="Critical CVEs"
              value={formatNumber(latest.critical_vulnerability_count)}
              tone={
                latest.critical_vulnerability_count > 0
                  ? 'text-critical-700'
                  : 'text-healthy-700'
              }
            />
            <Kpi
              icon={ShieldAlert}
              label="Access anomaly"
              value={latest.access_anomaly_detected ? 'Detected' : 'None'}
              tone={
                latest.access_anomaly_detected ? 'text-critical-700' : 'text-healthy-700'
              }
            />
            <Kpi
              icon={ShieldAlert}
              label="Monitoring"
              value={latest.monitoring_enabled ? 'Enabled' : 'Disabled'}
              tone={latest.monitoring_enabled ? 'text-healthy-700' : 'text-warning-700'}
            />
          </dl>
        ) : (
          <p className="mt-4 text-sm text-navy-300">No telemetry available.</p>
        )}
      </section>

      <section className="card p-6">
        <SectionTitle eyebrow="Findings" title="Security issues" />
        {securityIssues.length > 0 ? (
          <ul className="mt-4 flex flex-col gap-2">
            {securityIssues.map((issue) => (
              <li key={issue.issue_id}>
                <Link
                  to={`/issues/${issue.issue_id}`}
                  className="flex items-center justify-between gap-3 rounded-lg bg-navy-900/60 px-3 py-2 ring-1 ring-inset ring-navy-700 transition-colors hover:bg-navy-900"
                >
                  <span className="flex items-center gap-2 text-sm text-navy-100">
                    <Badge tone={severityTone(issue.severity)} uppercase>
                      {issue.severity}
                    </Badge>
                    {humanize(issue.issue_type)}
                  </span>
                  <span className="text-xs text-navy-400">
                    {formatDateTime(issue.detected_at)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 text-sm text-navy-300">No security issues detected.</p>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// GreenOps tab
// ---------------------------------------------------------------------------

interface GreenOpsTabProps {
  telemetry: TelemetrySnapshot[]
  latest: TelemetrySnapshot | null
}

function GreenOpsTab({ telemetry, latest }: GreenOpsTabProps) {
  // Telemetry arrives newest-first; chart wants chronological order.
  const series = [...telemetry].reverse().map((t) => ({
    time: formatTime(t.timestamp),
    energy: Number(t.energy_kwh_24h.toFixed(2)),
    carbon: Number(t.carbon_kgco2e_24h.toFixed(2)),
    cost: Number(t.cost_24h.toFixed(2)),
  }))

  return (
    <div className="flex flex-col gap-6">
      <section className="card p-6">
        <div className="flex items-center gap-2">
          <Leaf className="h-5 w-5 text-healthy-700" aria-hidden />
          <SectionTitle eyebrow="Sustainability" title="GreenOps snapshot" />
        </div>
        {latest ? (
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi
              icon={Leaf}
              label="Energy 24h"
              value={`${formatNumber(latest.energy_kwh_24h, 2)} kWh`}
            />
            <Kpi
              icon={Leaf}
              label="Carbon 24h"
              value={`${formatNumber(latest.carbon_kgco2e_24h, 2)} kgCO₂e`}
            />
            <Kpi
              icon={Gauge}
              label="Carbon intensity"
              value={`${formatNumber(latest.carbon_intensity_gco2_per_kwh)} g/kWh`}
            />
            <Kpi
              icon={DollarSign}
              label="Cost 24h"
              value={formatCurrency(latest.cost_24h, true)}
            />
          </dl>
        ) : (
          <p className="mt-4 text-sm text-navy-300">No telemetry available.</p>
        )}
      </section>

      <section className="card p-6">
        <SectionTitle eyebrow="Trend" title="Energy & carbon over time" />
        {series.length > 1 ? (
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="time" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    background: '#ffffff',
                    border: '1px solid #e2e8f0',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelStyle={{ color: '#475569' }}
                />
                <Line
                  type="monotone"
                  dataKey="energy"
                  name="Energy (kWh)"
                  stroke="#10b981"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="carbon"
                  name="Carbon (kgCO₂e)"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="mt-4 text-sm text-navy-300">
            Not enough telemetry to plot a trend yet.
          </p>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AI Recommendations tab
// ---------------------------------------------------------------------------

function RecommendationsTab({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) {
    return <EmptyState message="No AI recommendations for this workload." />
  }

  return (
    <section className="card p-6">
      <SectionTitle eyebrow="Next best action" title="AI recommendations" />
      <ul className="mt-4 flex flex-col gap-3">
        {issues.map((issue) => (
          <li
            key={issue.issue_id}
            className="rounded-lg bg-navy-900/60 p-4 ring-1 ring-inset ring-navy-700"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <Badge tone={severityTone(issue.severity)} uppercase>
                  {issue.severity}
                </Badge>
                <Badge tone={categoryTone(issue.issue_category)} uppercase>
                  {humanize(issue.issue_category)}
                </Badge>
                <span className="text-sm font-medium text-navy-50">
                  {humanize(issue.issue_type)}
                </span>
              </span>
              <Link
                to={`/issues/${issue.issue_id}`}
                className="inline-flex items-center gap-1 text-xs text-healthy-700 hover:text-healthy-700"
              >
                View issue <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
              </Link>
            </div>
            {issue.llm_user_explanation && (
              <p className="mt-2 text-sm text-navy-200">{issue.llm_user_explanation}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Self-Healing tab
// ---------------------------------------------------------------------------

// Statuses that represent the remediation lifecycle.
const REMEDIATION_STATUSES: ReadonlySet<Issue['status']> = new Set<Issue['status']>([
  'recommended',
  'pending_approval',
  'approved',
  'auto_fixed',
  'remediated',
  'escalated',
])

// Remediation status → badge tone.
function remediationTone(status: Issue['status']): BadgeTone {
  if (status === 'auto_fixed' || status === 'remediated') return 'low'
  if (status === 'escalated') return 'critical'
  if (status === 'pending_approval' || status === 'approved') return 'medium'
  return 'neutral'
}

function SelfHealingTab({ issues }: { issues: Issue[] }) {
  const remediating = issues.filter((i) => REMEDIATION_STATUSES.has(i.status))

  if (remediating.length === 0) {
    return <EmptyState message="No active or completed remediations for this workload." />
  }

  return (
    <section className="card p-6">
      <SectionTitle eyebrow="Automation" title="Self-healing activity" />
      <ul className="mt-4 flex flex-col gap-2">
        {remediating.map((issue) => (
          <li
            key={issue.issue_id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-navy-900/60 px-3 py-2 ring-1 ring-inset ring-navy-700"
          >
            <span className="flex items-center gap-2 text-sm text-navy-100">
              <Badge tone={remediationTone(issue.status)} uppercase>
                {humanize(issue.status)}
              </Badge>
              {humanize(issue.issue_type)}
            </span>
            <Link
              to={`/issues/${issue.issue_id}`}
              className="inline-flex items-center gap-1 text-xs text-healthy-700 hover:text-healthy-700"
            >
              Details <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ---------------------------------------------------------------------------
// MCP Activity tab
// ---------------------------------------------------------------------------

function MCPActivityTab({ entries }: { entries: MCPLogEntry[] }) {
  const columns: Column<MCPLogEntry>[] = [
    {
      key: 'timestamp',
      header: 'Time',
      accessor: (r) => r.timestamp,
      sortable: true,
      render: (r) => (
        <span className="whitespace-nowrap text-navy-200">
          {formatDateTime(r.timestamp)}
        </span>
      ),
    },
    {
      key: 'category',
      header: 'Category',
      accessor: (r) => r.category,
      sortable: true,
      render: (r) => <Badge tone="neutral">{humanize(r.category)}</Badge>,
    },
    {
      key: 'tool',
      header: 'Tool',
      accessor: (r) => r.tool,
      sortable: true,
      render: (r) => <span className="font-mono text-xs text-navy-100">{r.tool}</span>,
    },
    {
      key: 'policy',
      header: 'Policy',
      accessor: (r) => r.policy_compliance,
      sortable: true,
      render: (r) => (
        <Badge tone={r.policy_compliance === 'compliant' ? 'low' : 'high'} uppercase>
          {humanize(r.policy_compliance)}
        </Badge>
      ),
    },
    {
      key: 'remediation',
      header: 'Remediation',
      accessor: (r) => r.remediation_id ?? '',
      render: (r) =>
        r.remediation_id ? (
          <span className="font-mono text-xs text-navy-300">{r.remediation_id}</span>
        ) : (
          <span className="text-navy-500">—</span>
        ),
    },
  ]

  return (
    <div className="flex flex-col gap-3">
      <SectionTitle eyebrow="Connectors" title="MCP activity log" />
      <DataTable
        columns={columns}
        rows={entries}
        getRowId={(r, i) => `${r.timestamp}-${i}`}
        enableSearch
        searchPlaceholder="Search MCP log…"
        emptyMessage="No MCP tool invocations recorded for this workload."
      />
    </div>
  )
}
