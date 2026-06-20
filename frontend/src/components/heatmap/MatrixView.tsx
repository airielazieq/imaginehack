// MatrixView — the dimension matrix heatmap (Requirement 16.2).
//
// Renders workloads as rows and the six scoring dimensions as columns
// (Security · Energy · Carbon · Cost · Performance · Monitoring). Each cell is
// colored green/yellow/red/gray by its DimensionScore state. Clicking a cell
// navigates to that workload's detail page.
//
// Data comes from `GET /api/dashboard/heatmap/matrix` via `getMatrixHeatmap`,
// which unwraps the `{ rows, count }` envelope and returns the `rows` array.

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { getMatrixHeatmap, type MatrixHeatmapRow } from '../../api/endpoints'
import { dimensionStateColor } from '../../lib/colorScale'
import type { DimensionScore, DimensionScores, DimensionState } from '../../types'

/** The six dimensions, in matrix-display order, with their column labels. */
const DIMENSIONS: ReadonlyArray<{
  key: keyof Omit<DimensionScores, 'workload_id'>
  label: string
}> = [
  { key: 'security', label: 'Security' },
  { key: 'energy', label: 'Energy' },
  { key: 'carbon', label: 'Carbon' },
  { key: 'cost', label: 'Cost' },
  { key: 'performance', label: 'Performance' },
  { key: 'monitoring', label: 'Monitoring' },
]

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Unexpected error'
}

interface FetchState {
  data: MatrixHeatmapRow[] | null
  loading: boolean
  error: string | null
}

export default function MatrixView() {
  const navigate = useNavigate()
  const [state, setState] = useState<FetchState>({
    data: null,
    loading: true,
    error: null,
  })

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const data = await getMatrixHeatmap()
        if (active) setState({ data, loading: false, error: null })
      } catch (err) {
        if (active)
          setState({ data: null, loading: false, error: errorMessage(err) })
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const { data, loading, error } = state

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-navy-400">
        Loading matrix…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-12 text-critical-700">
        Failed to load matrix: {error}
      </div>
    )
  }

  const rows = data ?? []

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-navy-400">
        No workloads to display.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-navy-700">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="bg-navy-900 text-left text-navy-300">
            <th className="sticky left-0 z-10 bg-navy-900 px-4 py-3 font-medium">
              Workload
            </th>
            {DIMENSIONS.map((dim) => (
              <th
                key={dim.key}
                className="px-3 py-3 text-center font-medium"
                scope="col"
              >
                {dim.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.workload_id}
              className="border-t border-navy-700 hover:bg-navy-900"
            >
              <th
                scope="row"
                className="sticky left-0 z-10 max-w-[16rem] truncate bg-navy-800 px-4 py-2 text-left font-normal text-navy-200"
                title={row.workload_name ?? row.workload_id}
              >
                {row.workload_name ?? row.workload_id}
              </th>
              {DIMENSIONS.map((dim) => {
                const cell: DimensionScore = row.dimension_scores[dim.key]
                const cellState: DimensionState = cell.state
                return (
                  <td key={dim.key} className="px-1.5 py-1.5 text-center">
                    <button
                      type="button"
                      onClick={() => navigate(`/workloads/${row.workload_id}`)}
                      title={`${row.workload_name ?? row.workload_id} — ${dim.label}: ${cellState} (${cell.score})`}
                      aria-label={`${row.workload_name ?? row.workload_id} ${dim.label} ${cellState}, score ${cell.score}. Open workload detail.`}
                      className="h-9 w-full min-w-[3rem] rounded transition-transform hover:scale-105 focus:outline-none focus:ring-2 focus:ring-healthy-500"
                      style={{ backgroundColor: dimensionStateColor(cellState) }}
                    />
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
