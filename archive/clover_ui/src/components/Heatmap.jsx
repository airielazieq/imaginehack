import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LayoutGrid, Table2 } from 'lucide-react'
import { WORKLOADS, DIMENSIONS } from '../data/workloads.js'
import { priorityColor, healthColor } from '../lib/scale.js'
import { SectionTitle } from './ui.jsx'

function CompositeGrid() {
  const navigate = useNavigate()
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
      {WORKLOADS.map((w) => (
        <button
          key={w.id}
          onClick={() => navigate(`/workloads/${w.id}`)}
          className="group relative text-left rounded-xl p-3.5 text-white overflow-hidden
                     transition-transform duration-150 hover:-translate-y-0.5 hover:shadow-lift focus:outline-none focus:ring-2 focus:ring-clover-400"
          style={{ backgroundColor: priorityColor(w.priority) }}
        >
          <div className="font-mono text-[12px] font-medium drop-shadow-sm">{w.id}</div>
          <div className="text-[11px] text-white/80 mt-0.5">{w.role}</div>
          <div className="text-2xl font-bold mt-2 drop-shadow-sm">{w.priority}</div>

          {/* hover tooltip */}
          <div className="pointer-events-none absolute inset-x-2 bottom-full mb-2 z-30 opacity-0 translate-y-1
                          group-hover:opacity-100 group-hover:translate-y-0 transition-all duration-150">
            <div className="rounded-lg bg-stone-900 text-white text-left p-3 shadow-lift">
              <div className="font-mono text-xs font-medium">{w.id}</div>
              <div className="text-[11px] text-stone-300 mt-1">
                Priority <b style={{ color: priorityColor(w.priority) }}>{w.priority}</b> · {w.status}
              </div>
              <div className={`text-[11px] mt-1 ${w.alert ? 'text-red-300' : 'text-stone-400'}`}>
                {w.alert ? `⚠ ${w.alert}` : 'No active alerts'}
              </div>
              <div className="text-[11px] text-violet-300 mt-1">
                {w.downtimePct}% downtime risk{w.downtimeWindow !== '—' ? ` in ${w.downtimeWindow}` : ''}
              </div>
            </div>
          </div>
        </button>
      ))}
    </div>
  )
}

function MatrixView() {
  const navigate = useNavigate()
  return (
    <div className="card overflow-x-auto">
      <table className="w-full border-separate" style={{ borderSpacing: 0 }}>
        <thead>
          <tr className="text-left">
            <th className="sticky left-0 bg-white px-4 py-3 text-xs font-semibold text-stone-500">Workload</th>
            {DIMENSIONS.map((d) => (
              <th key={d} className="px-3 py-3 text-xs font-semibold text-stone-500 text-center">{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {WORKLOADS.map((w) => (
            <tr key={w.id} className="hover:bg-sand-50">
              <td className="sticky left-0 bg-white px-4 py-2 border-t border-sand-200">
                <button onClick={() => navigate(`/workloads/${w.id}`)} className="text-left">
                  <div className="font-mono text-xs font-medium text-stone-800 hover:text-clover-700">{w.id}</div>
                  <div className="text-[11px] text-stone-400">{w.role}</div>
                </button>
              </td>
              {DIMENSIONS.map((d) => {
                const v = w.dims[d]
                return (
                  <td key={d} className="px-2 py-2 border-t border-sand-200">
                    <button
                      onClick={() => navigate(`/workloads/${w.id}`)}
                      title={`${w.id} — ${d}: ${v === null ? 'not monitored' : v + '/100'}`}
                      className="w-full h-9 rounded-md text-xs font-semibold text-white grid place-items-center
                                 transition-transform hover:scale-[1.04]"
                      style={{ backgroundColor: healthColor(v) }}
                    >
                      {v === null ? '—' : v}
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Heatmap() {
  const [view, setView] = useState('composite')
  const toggle = (id, Icon, label) => (
    <button
      onClick={() => setView(id)}
      className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition
        ${view === id ? 'bg-white text-clover-700 shadow-card' : 'text-stone-500 hover:text-stone-700'}`}
    >
      <Icon size={15} /> {label}
    </button>
  )

  return (
    <section>
      <SectionTitle
        title="Workload severity heatmap"
        hint={view === 'composite'
          ? 'Continuous green → red by priority score. Hover for detail, click to drill in.'
          : 'Workloads × dimensions. Click any cell to open the workload.'}
        action={
          <div className="inline-flex bg-sand-100 border border-sand-200 rounded-lg p-0.5">
            {toggle('composite', LayoutGrid, 'Composite')}
            {toggle('matrix', Table2, 'Matrix')}
          </div>
        }
      />
      {view === 'composite' ? <CompositeGrid /> : <MatrixView />}

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-stone-400">
        {view === 'composite' ? (
          <div className="flex items-center gap-2">
            <span>Low</span>
            <div className="h-2.5 w-44 rounded-full"
              style={{ background: 'linear-gradient(90deg, hsl(140,62%,40%), hsl(70,62%,42%), hsl(35,62%,42%), hsl(0,62%,42%))' }} />
            <span>Critical</span>
          </div>
        ) : (
          <>
            <Legend color={healthColor(85)} label="Healthy (70+)" />
            <Legend color={healthColor(55)} label="Warning (40–69)" />
            <Legend color={healthColor(20)} label="Critical (<40)" />
            <Legend color="#d4d4c8" label="Not monitored" />
          </>
        )}
      </div>
    </section>
  )
}

function Legend({ color, label }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="h-3 w-3 rounded" style={{ backgroundColor: color }} /> {label}
    </span>
  )
}
