import { Link } from 'react-router-dom'
import { Clock3 } from 'lucide-react'

interface HeaderProps {
  /**
   * Number of remediations awaiting approval. Wired to a placeholder default for
   * now; task 9.2 / later tasks supply the live count via the approvals hook.
   */
  pendingApprovals?: number
}

export default function Header({ pendingApprovals = 0 }: HeaderProps) {
  return (
    <header className="sticky top-0 z-20 bg-navy-900/85 backdrop-blur border-b border-navy-700">
      <div className="h-16 px-6 flex items-center gap-4">
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">
            Clover Cloud Intelligence Platform
          </div>
          <div className="text-[11px] text-navy-300">Secure &amp; Energy-Aware Cloud Ops</div>
        </div>

        <div className="ml-auto flex items-center gap-3">
          <Link
            to="/approvals"
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium
                       bg-warning-500/15 text-warning-300 border border-warning-500/30
                       hover:bg-warning-500/25 transition-colors"
          >
            <Clock3 size={15} />
            {pendingApprovals} pending {pendingApprovals === 1 ? 'approval' : 'approvals'}
          </Link>

          <span className="flex items-center gap-1.5 text-xs text-navy-300">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-healthy-400 opacity-60 animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-healthy-500" />
            </span>
            Live
          </span>
        </div>
      </div>
    </header>
  )
}
