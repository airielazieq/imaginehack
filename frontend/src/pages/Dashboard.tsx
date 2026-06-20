// Dashboard — the heatmap landing page (Requirements 16.1, 16.2).
//
// Composes the summary stat cards with a dual-view heatmap: a composite
// Priority-Score grid and a per-dimension matrix, switched via HeatmapToggle.

import { useState } from 'react'
import SummaryCards from '../components/cards/SummaryCards'
import CompositeGrid from '../components/heatmap/CompositeGrid'
import HeatmapToggle, { type HeatmapView } from '../components/heatmap/HeatmapToggle'
import MatrixView from '../components/heatmap/MatrixView'

export default function Dashboard() {
  const [view, setView] = useState<HeatmapView>('composite')

  return (
    <div className="space-y-6">
      <header>
        <p className="eyebrow">Clover · Overview</p>
        <h1 className="mt-1 text-2xl font-semibold text-navy-50">Dashboard</h1>
        <p className="mt-1 text-sm text-navy-300">
          Workload health at a glance — priority heatmap and dimension matrix.
        </p>
      </header>

      <SummaryCards />

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold text-navy-50">
            {view === 'composite' ? 'Composite heatmap' : 'Dimension matrix'}
          </h2>
          <HeatmapToggle value={view} onChange={setView} />
        </div>

        {view === 'composite' ? <CompositeGrid /> : <MatrixView />}
      </section>
    </div>
  )
}
