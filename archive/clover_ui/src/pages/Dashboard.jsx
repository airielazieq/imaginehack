import {
  Boxes, TriangleAlert, Flame, ShieldCheck, Leaf, DollarSign, Wand2, Activity,
} from 'lucide-react'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from 'recharts'
import { PageHeader, StatCard, SectionTitle } from '../components/ui.jsx'
import Heatmap from '../components/Heatmap.jsx'
import { SUMMARY, WORKLOADS } from '../data/workloads.js'
import { priorityColor, usd } from '../lib/scale.js'

// Top-10 worst workloads, for a quick "what needs attention" bar chart.
const worst = [...WORKLOADS].sort((a, b) => b.priority - a.priority).slice(0, 8)
  .map((w) => ({ id: w.id, priority: w.priority }))

export default function Dashboard() {
  return (
    <>
      <PageHeader
        title="Fleet overview"
        subtitle="20 workloads across production, staging and dev — secure & energy-aware."
      />

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-8">
        <StatCard label="Workloads" value={SUMMARY.totalWorkloads} icon={Boxes} />
        <StatCard label="Active issues" value={SUMMARY.activeIssues} sub={`${SUMMARY.criticalIssues} critical`} icon={TriangleAlert} />
        <StatCard label="Critical" value={SUMMARY.criticalIssues} icon={Flame} />
        <StatCard label="Avg security" value={SUMMARY.avgSecurity} sub="fleet score" icon={ShieldCheck} />
        <StatCard label="Avg energy" value={SUMMARY.avgEnergy} sub="fleet score" icon={Activity} />
        <StatCard label="Monthly cost" value={usd(SUMMARY.monthlyCost)} icon={DollarSign} />
        <StatCard label="Projected savings" value={`${usd(SUMMARY.projectedSavings)}/mo`} accent icon={Wand2} />
        <StatCard label="CO₂ cut" value={`${SUMMARY.projectedCarbonCut} kg/mo`} accent icon={Leaf} />
        <StatCard label="Self-heal actions" value={SUMMARY.selfHealActions} sub="last 24h" icon={ShieldCheck} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-8">
        <div className="xl:col-span-2">
          <Heatmap />
        </div>
        <div className="card p-5">
          <SectionTitle title="Needs attention" hint="Highest priority scores" />
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={worst} layout="vertical" margin={{ left: 8, right: 16, top: 4 }}>
              <CartesianGrid horizontal={false} stroke="#e7e7df" />
              <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11, fill: '#a8a29e' }} />
              <YAxis type="category" dataKey="id" width={92}
                tick={{ fontSize: 11, fill: '#57534e', fontFamily: 'JetBrains Mono, monospace' }} />
              <Tooltip cursor={{ fill: '#f3f3ee' }} formatter={(v) => [v, 'Priority']} />
              <Bar dataKey="priority" radius={[0, 5, 5, 0]} barSize={16}>
                {worst.map((w) => <Cell key={w.id} fill={priorityColor(w.priority)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </>
  )
}
