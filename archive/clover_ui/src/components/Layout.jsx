import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Boxes, TriangleAlert, Lightbulb, ShieldCheck,
  FileText, ScrollText, SlidersHorizontal, Search, Clock3,
} from 'lucide-react'
import CloverMark from './CloverMark.jsx'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/workloads', label: 'Workloads', icon: Boxes },
  { to: '/issues', label: 'Issues', icon: TriangleAlert },
  { to: '/recommendations', label: 'Recommendations', icon: Lightbulb },
  { to: '/self-healing', label: 'Self-Healing', icon: ShieldCheck },
  { to: '/reports', label: 'Reports', icon: FileText },
  { to: '/audit', label: 'Audit Logs', icon: ScrollText },
  { to: '/mock', label: 'Mock Controller', icon: SlidersHorizontal },
]

function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-64 shrink-0 flex-col bg-clover-950 text-white">
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-white/10">
        <span className="text-clover-400"><CloverMark className="h-8 w-8" /></span>
        <div className="leading-tight">
          <div className="text-[15px] font-bold tracking-tight">Clover</div>
          <div className="text-[10px] text-clover-300/80">keeping your cloud green</div>
        </div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end}
            className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <Icon size={17} strokeWidth={2} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

function Topbar() {
  return (
    <header className="sticky top-0 z-20 bg-white/85 backdrop-blur border-b border-sand-200">
      <div className="h-16 px-6 flex items-center gap-4">
        <div className="relative hidden sm:block w-72">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" />
          <input
            placeholder="Search workloads, issues…"
            className="w-full bg-sand-100 border border-sand-200 rounded-lg pl-9 pr-3 py-2 text-sm
                       placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-clover-300"
          />
        </div>
        <div className="ml-auto flex items-center gap-3">
          <a href="/self-healing"
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium
                       bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 transition">
            <Clock3 size={15} /> 3 pending approvals
          </a>
          <span className="flex items-center gap-1.5 text-xs text-stone-500">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-clover-400 opacity-60 animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-clover-500" />
            </span>
            Live · 12s ago
          </span>
        </div>
      </div>
    </header>
  )
}

export default function Layout() {
  const { pathname } = useLocation()
  return (
    <div className="min-h-screen flex">
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Simulation banner */}
        <div className="bg-clover-900 text-clover-50 text-center text-xs py-1.5 font-medium tracking-wide">
          Simulation mode — all data is simulated, no live cloud connections
        </div>
        <Topbar />
        <main key={pathname} className="flex-1 px-6 py-7 max-w-[1400px] w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
