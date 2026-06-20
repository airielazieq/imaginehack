import { useMemo, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { useApprovals } from '../hooks/useApprovals'
import { useWorkloads } from '../hooks/useWorkloads'
import {
  approveRecommendation,
  denyApproval,
  snoozeApproval,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import type { ApprovalItem as ApprovalItemModel, Severity } from '../types'
import ApprovalItem from '../components/workflow/ApprovalItem'
import Modal from '../components/ui/Modal'

// Higher rank = more urgent. Mirrors backend severity ordering so the queue
// stays Critical → High → Medium → Low even if the API order ever changes.
const SEVERITY_RANK: Record<Severity, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
}

/** Default snooze window (minutes) — matches the backend default. */
const SNOOZE_MINUTES = 30

type PendingAction =
  | { kind: 'approve'; item: ApprovalItemModel }
  | { kind: 'deny'; item: ApprovalItemModel }

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Unexpected error'
}

export default function Approvals() {
  const { data: approvals, loading, error, refetch } = useApprovals()
  const { data: workloads } = useWorkloads()

  const [action, setAction] = useState<PendingAction | null>(null)
  const [selectedTools, setSelectedTools] = useState<string[]>([])
  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  // Map workload_id → display name.
  const workloadNames = useMemo(() => {
    const map = new Map<string, string>()
    workloads?.forEach((w) => map.set(w.workload_id, w.workload_name))
    return map
  }, [workloads])

  // Defensive client-side sort (Critical → High → Medium → Low, oldest first).
  const sorted = useMemo(() => {
    const items = approvals ?? []
    return [...items].sort((a, b) => {
      const rank = (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0)
      if (rank !== 0) return rank
      return a.created_at.localeCompare(b.created_at)
    })
  }, [approvals])

  const workloadName = (item: ApprovalItemModel) =>
    workloadNames.get(item.workload_id) ?? item.workload_id

  const openApprove = (item: ApprovalItemModel) => {
    setActionError(null)
    setSelectedTools([...item.mcp_tools]) // default: run every tool
    setAction({ kind: 'approve', item })
  }

  const openDeny = (item: ApprovalItemModel) => {
    setActionError(null)
    setAction({ kind: 'deny', item })
  }

  const closeModal = () => {
    setAction(null)
    setActionError(null)
  }

  const toggleTool = (tool: string) => {
    setSelectedTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool],
    )
  }

  const handleSnooze = async (item: ApprovalItemModel) => {
    setBusyId(item.approval_id)
    setActionError(null)
    try {
      await snoozeApproval(item.approval_id, SNOOZE_MINUTES)
      await refetch()
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  const confirmAction = async () => {
    if (!action) return
    const { kind, item } = action
    setBusyId(item.approval_id)
    setActionError(null)
    try {
      if (kind === 'approve') {
        await approveRecommendation(item.approval_id, selectedTools)
      } else {
        await denyApproval(item.approval_id)
      }
      await refetch()
      closeModal()
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center gap-3">
        <ShieldCheck className="h-6 w-6 text-warning-700" aria-hidden />
        <div>
          <p className="eyebrow">Clover · Guardrailed Self-Healing</p>
          <h1 className="mt-1 text-2xl font-semibold text-navy-50">Approval Queue</h1>
          <p className="mt-1 text-sm text-navy-300">
            Remediations awaiting review, sorted by severity. High-risk items
            auto-escalate when their countdown expires.
          </p>
        </div>
      </header>

      {actionError && !action && (
        <div className="card border-critical-700/50 bg-critical-900/20 p-4 text-sm text-critical-700">
          {actionError}
        </div>
      )}

      {error ? (
        <div className="card border-critical-700/50 bg-critical-900/20 p-6 text-sm text-critical-700">
          Failed to load the approval queue: {error}
        </div>
      ) : loading ? (
        <div className="card p-10 text-center text-sm text-navy-300">
          Loading approval queue…
        </div>
      ) : sorted.length === 0 ? (
        <div className="card p-10 text-center text-sm text-navy-300">
          No remediations are awaiting approval. The queue is clear.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {sorted.map((item) => (
            <ApprovalItem
              key={item.approval_id}
              item={item}
              workloadName={workloadName(item)}
              busy={busyId === item.approval_id}
              onApprove={() => openApprove(item)}
              onDeny={() => openDeny(item)}
              onSnooze={() => handleSnooze(item)}
            />
          ))}
        </div>
      )}

      {/* Approve / Deny confirmation modal */}
      <Modal
        open={action !== null}
        onClose={closeModal}
        title={
          action?.kind === 'approve'
            ? 'Approve remediation'
            : 'Deny remediation'
        }
        footer={
          <>
            <button
              type="button"
              onClick={closeModal}
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-navy-200 transition-colors hover:bg-navy-900"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={confirmAction}
              disabled={busyId !== null}
              className={[
                'rounded-lg px-4 py-1.5 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                action?.kind === 'approve'
                  ? 'bg-healthy-500 text-navy-950 hover:bg-healthy-400'
                  : 'bg-critical-500 text-white hover:bg-critical-400',
              ].join(' ')}
            >
              {busyId !== null
                ? 'Working…'
                : action?.kind === 'approve'
                  ? 'Approve & execute'
                  : 'Confirm deny'}
            </button>
          </>
        }
      >
        {action && (
          <div className="flex flex-col gap-3">
            <p>
              <span className="font-medium text-navy-50">
                {action.item.recommended_action}
              </span>{' '}
              on{' '}
              <span className="font-medium text-navy-50">
                {workloadName(action.item)}
              </span>
              .
            </p>

            {action.kind === 'approve' ? (
              action.item.mcp_tools.length > 0 ? (
                <div>
                  <p className="eyebrow">MCP tools to run</p>
                  <div className="mt-2 flex flex-col gap-2">
                    {action.item.mcp_tools.map((tool) => (
                      <label
                        key={tool}
                        className="flex items-center gap-2.5 text-sm text-navy-100"
                      >
                        <input
                          type="checkbox"
                          checked={selectedTools.includes(tool)}
                          onChange={() => toggleTool(tool)}
                          className="h-4 w-4 rounded border-navy-600 bg-navy-900 text-healthy-500 focus:ring-healthy-500"
                        />
                        <span className="font-mono text-xs">{tool}</span>
                      </label>
                    ))}
                  </div>
                  {selectedTools.length === 0 && (
                    <p className="mt-2 text-xs text-warning-700">
                      No tools selected — the runbook will run with no MCP tools.
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-xs text-navy-300">
                  This remediation has no MCP tools to select.
                </p>
              )
            ) : (
              <p className="text-sm text-navy-300">
                Denying closes this remediation. It will not be executed.
              </p>
            )}

            {actionError && (
              <p className="text-sm text-critical-700">{actionError}</p>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
