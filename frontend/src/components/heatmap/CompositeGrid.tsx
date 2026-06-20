// The composite heatmap: a responsive grid with one cell per Workload, each
// colored on a continuous green→red gradient by its Priority Score. Fetches
// the composite heatmap from the dashboard API and renders a HeatmapCell per
// workload.
//
// Requirements: 16.1 (one cell per workload, gradient by Priority Score),
// 16.3/16.4 (per-cell tooltip + click-through handled by HeatmapCell).

import { useEffect, useState } from 'react'
import { getCompositeHeatmap, type CompositeHeatmapCell } from '../../api/endpoints'
import { ApiError } from '../../api/client'
import HeatmapCell from './HeatmapCell'

interface FetchState {
  data: CompositeHeatmapCell[] | null
  loading: boolean
  error: string | null
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Unexpected error'
}

export default function CompositeGrid() {
  const [state, setState] = useState<FetchState>({
    data: null,
    loading: true,
    error: null,
  })

  useEffect(() => {
    let active = true
    ;(async () => {
      setState((s) => ({ ...s, loading: true, error: null }))
      try {
        const data = await getCompositeHeatmap()
        if (active) setState({ data, loading: false, error: null })
      } catch (err) {
        if (active) setState({ data: null, loading: false, error: errorMessage(err) })
      }
    })()
    return () => {
      active = false
    }
  }, [])

  if (state.loading) {
    return (
      <div
        className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3"
        aria-busy="true"
      >
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="min-h-[84px] animate-pulse rounded-lg bg-navy-800 ring-1 ring-navy-700"
          />
        ))}
      </div>
    )
  }

  if (state.error) {
    return (
      <div className="rounded-lg border border-critical-700 bg-critical-900/30 p-4 text-sm text-critical-700">
        Failed to load the composite heatmap: {state.error}
      </div>
    )
  }

  if (!state.data || state.data.length === 0) {
    return (
      <div className="rounded-lg border border-navy-700 bg-navy-900 p-6 text-center text-sm text-navy-300">
        No workloads to display yet.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
      {state.data.map((cell) => (
        <HeatmapCell key={cell.workload_id} cell={cell} />
      ))}
    </div>
  )
}
