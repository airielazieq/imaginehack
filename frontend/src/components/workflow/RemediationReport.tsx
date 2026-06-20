import { useMemo } from 'react'
import {
  CheckCircle2,
  ShieldCheck,
  Undo2,
  XCircle,
} from 'lucide-react'
import type {
  ExecutionPath,
  ExecutionStatus,
  MCPToolExecution,
  RemediationResult,
  VerificationResult,
} from '../../types'
import type { BadgeTone } from '../ui/Badge'
import Badge from '../ui/Badge'
import { formatDateTime, formatDuration } from '../../lib/formatters'

/** Turn a snake_case enum value into a readable label. */
function humanize(value: string): string {
  return value
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** Map an execution path to a Badge tone. */
export function executionPathTone(path: ExecutionPath): BadgeTone {
  switch (path) {
    case 'auto_fix':
      return 'low'
    case 'user_approved':
      return 'medium'
    case 'human_escalation':
      return 'high'
    default:
      return 'neutral'
  }
}

/** Map an execution status to a Badge tone. */
export function executionStatusTone(status: ExecutionStatus): BadgeTone {
  switch (status) {
    case 'completed':
      return 'low'
    case 'failed':
    case 'rejected':
      return 'critical'
    case 'escalated':
      return 'high'
    case 'pending_approval':
    case 'in_progress':
      return 'medium'
    default:
      return 'neutral'
  }
}

/** Map a verification result to a Badge tone. */
export function verificationTone(result: VerificationResult): BadgeTone {
  switch (result) {
    case 'passed':
      return 'low'
    case 'failed':
      return 'critical'
    default:
      return 'neutral'
  }
}

/** Render an arbitrary JSON value as a compact, readable string. */
function stringifyValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/** A titled section card. */
function Section({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <section className="card p-5">
      <header className="mb-3">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-navy-200">
          {title}
        </h3>
        {subtitle && <p className="mt-1 text-xs text-navy-400">{subtitle}</p>}
      </header>
      {children}
    </section>
  )
}

/** Render a flat key/value grid for a generic record. */
function KeyValueGrid({ record }: { record: Record<string, unknown> }) {
  const entries = Object.entries(record)
  if (entries.length === 0) {
    return <p className="text-sm text-navy-400">No details recorded.</p>
  }
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="flex flex-col">
          <dt className="text-xs font-medium uppercase tracking-wide text-navy-400">
            {humanize(key)}
          </dt>
          <dd className="text-sm text-navy-100">{stringifyValue(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Render a single MCP tool invocation with full JSON I/O. */
function MCPToolRow({ tool }: { tool: MCPToolExecution }) {
  const tone: BadgeTone =
    tool.status === 'success' ? 'low' : tool.status === 'failed' ? 'critical' : 'neutral'
  return (
    <div className="rounded-lg border border-navy-800 bg-navy-900/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-navy-50">{tool.tool}</span>
          <Badge>{humanize(tool.category)}</Badge>
        </div>
        <div className="flex items-center gap-2 text-xs text-navy-300">
          <span>{formatDuration(tool.duration_ms)}</span>
          <Badge tone={tone} uppercase>
            {tool.status}
          </Badge>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-navy-400">
            Input
          </p>
          <pre className="overflow-x-auto rounded bg-navy-950/60 p-3 text-xs text-navy-200">
            {JSON.stringify(tool.input, null, 2)}
          </pre>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-navy-400">
            Output
          </p>
          <pre className="overflow-x-auto rounded bg-navy-950/60 p-3 text-xs text-navy-200">
            {JSON.stringify(tool.output, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  )
}

interface RemediationReportProps {
  /** The full remediation record to render. */
  report: RemediationResult
  /** Optional human-readable workload name for the header. */
  workloadName?: string
}

/**
 * Full post-incident remediation report (UI spec §7):
 * What happened → AI Decision Process → MCP Tools Executed (JSON I/O) →
 * Before/After → Execution Timeline → Safety Decision → Audit & Compliance.
 */
export default function RemediationReport({ report, workloadName }: RemediationReportProps) {
  const timeline = useMemo(
    () => report.execution_timeline ?? [],
    [report.execution_timeline],
  )

  return (
    <div className="flex flex-col gap-5">
      {/* Header: narrative + status badges */}
      <header className="card p-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={executionPathTone(report.execution_path)} uppercase>
            {humanize(report.execution_path)}
          </Badge>
          <Badge tone={executionStatusTone(report.execution_status)} uppercase>
            {humanize(report.execution_status)}
          </Badge>
          <Badge tone={verificationTone(report.verification_result)} uppercase>
            Verify: {report.verification_result}
          </Badge>
          {report.rollback_triggered && (
            <Badge tone="high" uppercase>
              <Undo2 className="h-3 w-3" aria-hidden /> Rolled back
            </Badge>
          )}
        </div>
        <h2 className="mt-3 text-lg font-semibold text-navy-50">
          {workloadName ?? report.workload_id}
        </h2>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-navy-200">
          {report.user_facing_report}
        </p>
        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-1 text-xs text-navy-400 sm:grid-cols-3">
          <div>
            <dt className="inline font-medium">Remediation: </dt>
            <dd className="inline text-navy-200">{report.remediation_id}</dd>
          </div>
          <div>
            <dt className="inline font-medium">Issue: </dt>
            <dd className="inline text-navy-200">{report.issue_id}</dd>
          </div>
          <div>
            <dt className="inline font-medium">Recommendation: </dt>
            <dd className="inline text-navy-200">{report.recommendation_id}</dd>
          </div>
        </dl>
      </header>

      {/* What happened */}
      <Section title="What Happened" subtitle="Reason for the action and what was changed.">
        <p className="text-sm leading-relaxed text-navy-100">{report.reason_for_action}</p>
        <div className="mt-3">
          <KeyValueGrid record={report.action_taken} />
        </div>
      </Section>

      {/* AI Decision Process */}
      <Section
        title="AI Decision Process"
        subtitle="Ordered reasoning steps that led to this action."
      >
        {report.ai_decision_steps.length === 0 ? (
          <p className="text-sm text-navy-400">No decision steps recorded.</p>
        ) : (
          <ol className="flex flex-col gap-3">
            {report.ai_decision_steps.map((step, index) => (
              <li
                key={index}
                className="rounded-lg border border-navy-800 bg-navy-900/40 p-3"
              >
                <div className="mb-2 text-xs font-semibold text-healthy-700">
                  Step {index + 1}
                </div>
                <KeyValueGrid record={step} />
              </li>
            ))}
          </ol>
        )}
      </Section>

      {/* MCP Tools Executed */}
      <Section
        title="MCP Tools Executed"
        subtitle="Each connector invocation with full JSON input and output."
      >
        {report.mcp_tools_executed.length === 0 ? (
          <p className="text-sm text-navy-400">No MCP tools were invoked.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {report.mcp_tools_executed.map((tool, index) => (
              <MCPToolRow key={`${tool.tool}-${index}`} tool={tool} />
            ))}
          </div>
        )}
      </Section>

      {/* Before / After */}
      <Section title="Before / After Impact" subtitle="Projected impact of the remediation.">
        <KeyValueGrid record={report.impact_result} />
      </Section>

      {/* Execution Timeline */}
      <Section title="Execution Timeline" subtitle="Chronological execution events.">
        {timeline.length === 0 ? (
          <p className="text-sm text-navy-400">No timeline events recorded.</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {timeline.map((event, index) => {
              const ts = event['timestamp']
              const label = event['event'] ?? event['step'] ?? event['status']
              return (
                <li
                  key={index}
                  className="flex flex-col gap-1 border-l-2 border-navy-700 pl-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-navy-100">
                      {label != null ? stringifyValue(label) : `Event ${index + 1}`}
                    </span>
                    {typeof ts === 'string' && (
                      <span className="text-xs text-navy-400">{formatDateTime(ts)}</span>
                    )}
                  </div>
                  <KeyValueGrid record={event} />
                </li>
              )
            })}
          </ol>
        )}
      </Section>

      {/* Safety Decision */}
      <Section title="Safety Decision" subtitle="Why the chosen path was considered safe.">
        <p className="flex items-start gap-2 text-sm text-navy-100">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-healthy-700" aria-hidden />
          {report.safety_decision.why_safe}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Badge tone={report.safety_decision.approval_required ? 'medium' : 'low'}>
            {report.safety_decision.approval_required
              ? 'Approval required'
              : 'No approval required'}
          </Badge>
          <Badge tone={report.safety_decision.rollback_available ? 'low' : 'neutral'}>
            {report.safety_decision.rollback_available
              ? 'Rollback available'
              : 'No rollback'}
          </Badge>
        </div>
      </Section>

      {/* Audit & Compliance */}
      <Section title="Audit & Compliance">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          <div className="flex flex-col">
            <dt className="text-xs font-medium uppercase tracking-wide text-navy-400">
              Approval Type
            </dt>
            <dd className="text-sm text-navy-100">
              {humanize(report.audit_compliance.approval_type)}
            </dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-xs font-medium uppercase tracking-wide text-navy-400">
              Policy Compliance
            </dt>
            <dd className="flex items-center gap-1.5 text-sm text-navy-100">
              {report.audit_compliance.policy_compliance === 'compliant' ? (
                <CheckCircle2 className="h-4 w-4 text-healthy-700" aria-hidden />
              ) : (
                <XCircle className="h-4 w-4 text-warning-700" aria-hidden />
              )}
              {humanize(report.audit_compliance.policy_compliance)}
            </dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-xs font-medium uppercase tracking-wide text-navy-400">
              Rollback Available
            </dt>
            <dd className="text-sm text-navy-100">
              {report.audit_compliance.rollback_available ? 'Yes' : 'No'}
            </dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-xs font-medium uppercase tracking-wide text-navy-400">
              Persistent Data Modified
            </dt>
            <dd className="text-sm text-navy-100">
              {report.audit_compliance.persistent_data_modified ? 'Yes' : 'No'}
            </dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-xs font-medium uppercase tracking-wide text-navy-400">
              Retention Expires
            </dt>
            <dd className="text-sm text-navy-100">
              {formatDateTime(report.audit_compliance.retention_expires)}
            </dd>
          </div>
        </dl>
      </Section>
    </div>
  )
}
