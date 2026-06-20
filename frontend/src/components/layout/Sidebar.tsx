import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Boxes,
  TriangleAlert,
  ShieldCheck,
  FileText,
  ScrollText,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react'
import CloverMark from './CloverMark'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** `end` ensures the Dashboard link is only active on the exact `/` path. */
  end?: boolean
}

// Primary navigation. Detail routes (/workloads/:id, /issues/:id) are reached by
// drilling in, so they are intentionally not listed here.
const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/workloads', label: 'Workloads', icon: Boxes },
  { to: '/issues', label: 'Issues', icon: TriangleAlert },
  { to: '/approvals', label: 'Approvals', icon: ShieldCheck },
  { to: '/reports', label: 'Reports', icon: FileText },
  { to: '/audit', label: 'Audit Logs', icon: ScrollText },
  { to: '/mock', label: 'Mock Controller', icon: SlidersHorizontal },
]

export default function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-64 shrink-0 flex-col bg-navy-950 text-navy-100">
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-navy-700">
        <span className="text-healthy-700">
          <CloverMark className="h-8 w-8" />
        </span>
        <div className="leading-tight">
          <div className="text-[15px] font-bold tracking-tight">Clover</div>
          <div className="text-[10px] text-navy-300">keeping your cloud green</div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
          >
            <Icon size={17} strokeWidth={2} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="px-5 py-4 border-t border-navy-700 text-[11px] text-navy-300">
        HILTI Track 2 · MVP
        <div className="mt-1 text-navy-400">Secure &amp; Energy-Aware Cloud Ops</div>
      </div>
    </aside>
  )
}
