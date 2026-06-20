import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  ArrowLeft, BrainCircuit, Zap, Cpu, MemoryStick, ShieldAlert, Wand2, CheckCircle2,
} from 'lucide-react'
import {
  ResponsiveContainer, AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceArea,
} from 'recharts'
import { WORKLOADS, WORKLOAD_DETAIL } from '../data/workloads.js'
import { SeverityBadge, Tag, SectionTitle } from '../components/ui.jsx'
import { severityFromPriority, usd } from '../lib/scale.js'

const TONE = { critical: 'text-red-600', high: 'text-orange-600', medium: 'text-amber-600', info: 'text-clover-600' }

// 90-day uptime bars (deterministic mock).
const uptime = Array.from({ length: 90 }, (_, i) => {
  if ([3, 4, 88, 89].includes(i)) return 'bad'
  if ([10, 22, 23, 70].includes(i)) return 'warn'
  return 'ok'
})
const upColor = { ok: '#2f9e44', warn: '#ca8a04', bad: '#dc2626' }

function fallbackDetail(w) {
  return {
    type: 'Container', workflow: w.role, uptime: 99.0, model: 'Clover Predictive v2.1', trainedAgo: '2h ago',
    timeToFailure: w.downtimeWindow, cpuExhaustionPct: Math.round(w.cpu * 0.7),
    riskTimeline: [0, 1, 2, 3, 4, 6, 9, 12].map((h, i) => ({ t: h === 0 ? 'Now' : `+${h}h`, risk: Math.min(100, Math.round(w.downtimePct * (0.6 + i * 0.08))) })),
    signals: [{ label: 'Top signal', text: w.alert ?? 'Nominal — no dominant risk signal', tone: w.alert ? 'high' : 'info' }],
    degradation: [{ stage: 'Base', score: 100 }, { stage: 'Current', score: w.dims.Energy }],
    forecast: [{ metric: 'Cost ($/mo)', current: Math.round(w.cost * 0.3), projected: Math.round(w.cost * 0.15) }],
    findings: [],
  }
}

export default function WorkloadDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState('overview')
  const w = WORKLOADS.find((x) => x.id === id)

  if (!w) {
    return (
      <div className="card p-8 text-center">
        <p className="text-stone-600">Workload <span className="font-mono">{id}</span> not found.</p>
        <Link to="/" className="text-clover-700 text-sm mt-2 inline-block">← Back to dashboard</Link>
      </div>
    )
  }
  const d = WORKLOAD_DETAIL[id] ?? fallbackDetail(w)
  const sev = severityFromPriority(w.priority)

  return (
    <>
      <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-sm text-stone-500 hover:text-stone-800 mb-4">
        <ArrowLeft size={15} /> Back
      </button>

      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold font-mono tracking-tight text-stone-900">{w.id}</h1>
          <SeverityBadge level={sev} />
          <Tag tone="purple">{w.env}</Tag>
        </div>
        <div className="text-sm text-stone-500">{d.workflow}</div>
      </div>

      <Tabs tab={tab} setTab={setTab} />

      {tab === 'overview' && <Overview w={w} d={d} />}
      {tab === 'greenops' && <GreenOps d={d} />}
    </>
  )
}

function Tabs({ tab, setTab }) {
  const tabs = [
    ['overview', 'Overview'], ['greenops', 'GreenOps'],
    ['security', 'Security'], ['ai', 'AI Recommendations'], ['mcp', 'MCP Activity'],
  ]
  return (
    <div className="flex gap-1 border-b border-sand-200 mb-6 overflow-x-auto">
      {tabs.map(([id, label]) => {
        const enabled = id === 'overview' || id === 'greenops'
        return (
          <button key={id} disabled={!enabled} onClick={() => enabled && setTab(id)}
            className={`px-3.5 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition
              ${tab === id ? 'border-clover-500 text-clover-700'
                : enabled ? 'border-transparent text-stone-500 hover:text-stone-800'
                : 'border-transparent text-stone-300 cursor-not-allowed'}`}>
            {label}{!enabled && <span className="ml-1 text-[10px]">soon</span>}
          </button>
        )
      })}
    </div>
  )
}

function Overview({ w, d }) {
  return (
    <div className="space-y-6">
      {/* AI downtime prediction */}
      <div className="card p-5 border-l-4 border-l-violet-400">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <BrainCircuit size={18} className="text-violet-500" />
            <h3 className="font-semibold text-stone-800">AI downtime prediction</h3>
          </div>
          <span className="text-xs text-stone-400">{d.model} · trained {d.trainedAgo}</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
          <RiskStat value={`${w.downtimePct}%`} label="Downtime probability" note={`Failure within ${d.timeToFailure}`} tone="critical" />
          <RiskStat value={d.timeToFailure} label="Est. time to failure" note="From memory-growth trend" tone="high" />
          <RiskStat value={`${d.cpuExhaustionPct}%`} label="CPU exhaustion risk" note="If batch runs in peak" tone="medium" />
        </div>

        <SectionTitle title="Risk timeline" hint="Failure probability over the next 12 hours" />
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={d.riskTimeline} margin={{ left: -16, right: 8, top: 4 }}>
            <defs>
              <linearGradient id="risk" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#dc2626" stopOpacity={0.4} />
                <stop offset="100%" stopColor="#a855f7" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#e7e7df" vertical={false} />
            <XAxis dataKey="t" tick={{ fontSize: 11, fill: '#a8a29e' }} />
            <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11, fill: '#a8a29e' }} />
            <Tooltip formatter={(v) => [`${v}%`, 'Risk']} />
            <Area type="monotone" dataKey="risk" stroke="#a855f7" strokeWidth={2.5} fill="url(#risk)" />
          </AreaChart>
        </ResponsiveContainer>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 mt-5">
          {d.signals.map((s) => (
            <div key={s.label} className="bg-sand-50 border border-sand-200 rounded-lg px-3 py-2 text-sm">
              <span className="text-stone-400">{s.label}: </span>
              <span className={TONE[s.tone]}>{s.text}</span>
            </div>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 bg-clover-50 border border-clover-200 rounded-lg px-4 py-3">
          <div className="text-sm">
            <span className="font-medium text-clover-800">Recommended preemptive action:</span>{' '}
            <span className="text-stone-600">Restart now to clear the leak — ~15s vs 5–10 min unplanned outage.</span>
          </div>
          <button className="px-3.5 py-1.5 rounded-lg bg-clover-600 hover:bg-clover-700 text-white text-sm font-medium transition whitespace-nowrap">
            Review in Self-Healing →
          </button>
        </div>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card p-5">
          <SectionTitle title="Key metrics" />
          <div className="grid grid-cols-2 gap-4">
            <Metric icon={Cpu} value={`${w.cpu}%`} label="CPU" danger={w.cpu > 85} />
            <Metric icon={MemoryStick} value={`${w.memory}%`} label="Memory" danger={w.memory > 80} />
            <Metric icon={ShieldAlert} value={w.dims.Security} label="Security score" danger={w.dims.Security < 40} />
            <Metric icon={Zap} value={w.dims.Energy} label="Energy score" danger={w.dims.Energy < 40} />
            <Metric value={usd(w.cost)} label="Monthly cost" />
            <Metric value={w.alert ? '1+' : '0'} label="Active alerts" danger={!!w.alert} />
          </div>
        </div>
        <div className="card p-5">
          <SectionTitle title="Priority score" />
          <div className="text-center py-2">
            <div className="text-5xl font-bold text-stone-900">{w.priority}</div>
            <div className="text-xs text-stone-400 mt-1">of 100 · weighted</div>
            <div className="mt-4 h-2.5 w-full bg-sand-200 rounded-full overflow-hidden">
              <div className="h-full rounded-full" style={{ width: `${w.priority}%`, backgroundColor: 'hsl(' + (140 - w.priority * 1.4) + ',62%,42%)' }} />
            </div>
          </div>
        </div>
        <div className="card p-5">
          <SectionTitle title="90-day uptime" action={<span className="text-sm font-medium text-clover-700">{d.uptime}%</span>} />
          <div className="flex gap-px h-10 rounded overflow-hidden mt-2">
            {uptime.map((s, i) => <div key={i} className="flex-1" style={{ backgroundColor: upColor[s] }} title={`Day ${i + 1}: ${s}`} />)}
          </div>
          <div className="flex justify-between text-[11px] text-stone-400 mt-1.5">
            <span>90 days ago</span><span>Today</span>
          </div>
        </div>
      </div>

      {/* Alerts */}
      <div className="card p-5">
        <SectionTitle title="Active alerts" />
        {w.alert ? (
          <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5">
            <span className="h-2 w-2 rounded-full bg-red-500" />
            <div className="flex-1 text-sm">
              <div className="font-medium text-stone-800">{w.alert}</div>
              <div className="text-xs text-stone-400">12 min ago · requires human approval</div>
            </div>
            <SeverityBadge level={severityFromPriority(w.priority)} />
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-stone-400">
            <CheckCircle2 size={16} className="text-clover-500" /> No active alerts.
          </div>
        )}
      </div>
    </div>
  )
}

function GreenOps({ d }) {
  const totalSaved = d.forecast.reduce((a, f) => a + (f.current - f.projected), 0)
  return (
    <div className="space-y-6">
      <div className="card p-5">
        <SectionTitle title="Energy score degradation" hint="Cumulative impact of each detected inefficiency" />
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={d.degradation} margin={{ left: -16, right: 8, top: 8 }}>
            <CartesianGrid stroke="#e7e7df" vertical={false} />
            <ReferenceArea y1={0} y2={50} fill="#dc2626" fillOpacity={0.05} />
            <XAxis dataKey="stage" tick={{ fontSize: 11, fill: '#a8a29e' }} interval={0} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#a8a29e' }} />
            <Tooltip formatter={(v, n, p) => [`${v}${p.payload.penalty ? ` (−${p.payload.penalty})` : ''}`, 'Score']} />
            <Line type="monotone" dataKey="score" stroke="#ea580c" strokeWidth={3}
              dot={{ r: 4, strokeWidth: 2, stroke: '#fff' }} activeDot={{ r: 6 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card p-5">
        <SectionTitle
          title="Optimization impact forecast"
          hint="Current vs. projected after applying all recommended fixes"
          action={<span className="px-2.5 py-1 rounded-md bg-clover-50 text-clover-700 text-xs font-semibold ring-1 ring-clover-200">
            ▼ saves {totalSaved.toLocaleString()} units/mo
          </span>}
        />
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={d.forecast} margin={{ left: -8, right: 8, top: 8 }}>
            <CartesianGrid stroke="#e7e7df" vertical={false} />
            <XAxis dataKey="metric" tick={{ fontSize: 11, fill: '#a8a29e' }} />
            <YAxis tick={{ fontSize: 11, fill: '#a8a29e' }} />
            <Tooltip cursor={{ fill: '#f3f3ee' }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="current" name="Current" fill="#ea580c" radius={[4, 4, 0, 0]} barSize={26} />
            <Bar dataKey="projected" name="Projected" fill="#2f9e44" radius={[4, 4, 0, 0]} barSize={26} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {d.findings.length > 0 && (
        <div className="card divide-y divide-sand-200">
          <div className="px-5 py-3.5"><h3 className="font-semibold text-stone-800">Inefficiency patterns ({d.findings.length})</h3></div>
          {d.findings.map((f) => (
            <div key={f.title} className="px-5 py-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <h4 className="font-medium text-stone-800">{f.title}</h4>
                  {f.resolved && <Tag tone="green"><CheckCircle2 size={11} className="mr-1" /> auto-resolved</Tag>}
                </div>
                <SeverityBadge level={f.severity[0].toUpperCase() + f.severity.slice(1)}>−{f.penalty} pts</SeverityBadge>
              </div>
              <p className="text-sm text-stone-500 mt-1">{f.detail}</p>
              <div className="mt-2 flex items-center gap-2 text-sm bg-clover-50 border border-clover-200 rounded-lg px-3 py-2 text-clover-800">
                <Wand2 size={14} className="text-clover-500 shrink-0" /> {f.fix}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function RiskStat({ value, label, note, tone }) {
  const ring = { critical: 'ring-red-200', high: 'ring-orange-200', medium: 'ring-amber-200' }[tone]
  const col = { critical: 'text-red-600', high: 'text-orange-600', medium: 'text-amber-600' }[tone]
  return (
    <div className={`rounded-xl bg-sand-50 ring-1 ring-inset ${ring} p-4 text-center`}>
      <div className={`text-3xl font-bold ${col}`}>{value}</div>
      <div className="text-sm text-stone-600 mt-1">{label}</div>
      <div className="text-[11px] text-stone-400 mt-1">{note}</div>
    </div>
  )
}

function Metric({ icon: Icon, value, label, danger }) {
  return (
    <div>
      <div className={`text-xl font-bold ${danger ? 'text-red-600' : 'text-stone-800'}`}>{value}</div>
      <div className="flex items-center gap-1 text-xs text-stone-400 mt-0.5">
        {Icon && <Icon size={12} />} {label}
      </div>
    </div>
  )
}
