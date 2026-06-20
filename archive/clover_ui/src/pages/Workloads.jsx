import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, SeverityBadge, Tag } from '../components/ui.jsx'
import { WORKLOADS } from '../data/workloads.js'
import { severityFromPriority, healthColor, usd } from '../lib/scale.js'

const ENVS = ['all', 'prod', 'staging', 'dev']

export default function Workloads() {
  const navigate = useNavigate()
  const [env, setEnv] = useState('all')
  const rows = WORKLOADS.filter((w) => env === 'all' || w.env === env)
    .sort((a, b) => b.priority - a.priority)

  return (
    <>
      <PageHeader title="Workloads" subtitle={`${rows.length} workloads`}>
        <div className="inline-flex bg-sand-100 border border-sand-200 rounded-lg p-0.5">
          {ENVS.map((e) => (
            <button key={e} onClick={() => setEnv(e)}
              className={`px-3 py-1.5 text-sm font-medium rounded-md capitalize transition
                ${env === e ? 'bg-white text-clover-700 shadow-card' : 'text-stone-500 hover:text-stone-700'}`}>
              {e}
            </button>
          ))}
        </div>
      </PageHeader>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs font-semibold text-stone-500 border-b border-sand-200">
              <th className="px-4 py-3">Workload</th>
              <th className="px-4 py-3">Env</th>
              <th className="px-4 py-3">Priority</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-center">Sec</th>
              <th className="px-4 py-3 text-center">Energy</th>
              <th className="px-4 py-3 text-right">Cost/mo</th>
              <th className="px-4 py-3">Top alert</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((w) => (
              <tr key={w.id} onClick={() => navigate(`/workloads/${w.id}`)}
                className="border-b border-sand-200 last:border-0 hover:bg-sand-50 cursor-pointer">
                <td className="px-4 py-3">
                  <div className="font-mono text-[13px] font-medium text-stone-800">{w.id}</div>
                  <div className="text-[11px] text-stone-400">{w.role}</div>
                </td>
                <td className="px-4 py-3"><Tag>{w.env}</Tag></td>
                <td className="px-4 py-3 font-semibold text-stone-700">{w.priority}</td>
                <td className="px-4 py-3"><SeverityBadge level={severityFromPriority(w.priority)} /></td>
                <td className="px-4 py-3 text-center"><Pill v={w.dims.Security} /></td>
                <td className="px-4 py-3 text-center"><Pill v={w.dims.Energy} /></td>
                <td className="px-4 py-3 text-right tabular-nums text-stone-600">{usd(w.cost)}</td>
                <td className="px-4 py-3 text-stone-500 max-w-[220px] truncate">{w.alert ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Pill({ v }) {
  return (
    <span className="inline-grid place-items-center h-6 w-9 rounded-md text-xs font-semibold text-white"
      style={{ backgroundColor: healthColor(v) }}>
      {v ?? '—'}
    </span>
  )
}
