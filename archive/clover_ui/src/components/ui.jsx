import { SEVERITY } from '../lib/scale.js'

export function SeverityBadge({ level, children }) {
  const s = SEVERITY[level] ?? SEVERITY.Low
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium
      ring-1 ring-inset ${s.bg} ${s.text} ${s.ring}`}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: s.color }} />
      {children ?? level}
    </span>
  )
}

export function Tag({ children, tone = 'neutral' }) {
  const tones = {
    neutral: 'bg-sand-100 text-stone-600 ring-sand-200',
    green: 'bg-clover-50 text-clover-700 ring-clover-200',
    purple: 'bg-violet-50 text-violet-700 ring-violet-200',
    blue: 'bg-sky-50 text-sky-700 ring-sky-200',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium ring-1 ring-inset ${tones[tone]}`}>
      {children}
    </span>
  )
}

export function StatCard({ label, value, sub, accent = false, icon: Icon }) {
  return (
    <div className={`card p-4 ${accent ? 'ring-1 ring-clover-200' : ''}`}>
      <div className="flex items-start justify-between">
        <div className="eyebrow">{label}</div>
        {Icon && <Icon size={15} className={accent ? 'text-clover-500' : 'text-stone-300'} />}
      </div>
      <div className={`mt-2 text-2xl font-bold tracking-tight ${accent ? 'text-clover-700' : 'text-stone-800'}`}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-stone-400">{sub}</div>}
    </div>
  )
}

export function SectionTitle({ title, hint, action }) {
  return (
    <div className="flex items-end justify-between mb-3">
      <div>
        <h2 className="text-base font-semibold text-stone-800">{title}</h2>
        {hint && <p className="text-xs text-stone-400 mt-0.5">{hint}</p>}
      </div>
      {action}
    </div>
  )
}

export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-stone-900">{title}</h1>
        {subtitle && <p className="text-sm text-stone-500 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </div>
  )
}
