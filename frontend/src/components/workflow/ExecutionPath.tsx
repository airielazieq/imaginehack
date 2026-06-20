import { Bot, ShieldCheck, UserCog } from 'lucide-react'
import type { ReactNode } from 'react'

/** The three guardrailed execution routes (design.md §Safety Router). */
export type ExecutionPathKind = 'auto_fix' | 'approval' | 'escalation'

interface ExecutionPathProps {
  /** Which route this remediation is taking. */
  path: ExecutionPathKind
  className?: string
}

interface PathStyle {
  label: string
  icon: ReactNode
  classes: string
}

const PATH_STYLES: Record<ExecutionPathKind, PathStyle> = {
  auto_fix: {
    label: 'Auto-Fix',
    icon: <Bot className="h-3.5 w-3.5" aria-hidden />,
    classes: 'bg-healthy-500/15 text-healthy-700 ring-healthy-500/30',
  },
  approval: {
    label: 'Approval',
    icon: <ShieldCheck className="h-3.5 w-3.5" aria-hidden />,
    classes: 'bg-warning-500/15 text-warning-700 ring-warning-500/30',
  },
  escalation: {
    label: 'Escalation',
    icon: <UserCog className="h-3.5 w-3.5" aria-hidden />,
    classes: 'bg-critical-500/15 text-critical-700 ring-critical-500/30',
  },
}

/**
 * Small indicator chip showing whether a remediation is auto-fixed, awaiting
 * approval, or escalated to a human (design.md §Self-Healing workflow).
 */
export default function ExecutionPath({ path, className = '' }: ExecutionPathProps) {
  const style = PATH_STYLES[path]
  return (
    <span
      className={[
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        style.classes,
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {style.icon}
      {style.label}
    </span>
  )
}
