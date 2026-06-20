// Segmented control that switches the dashboard heatmap between the composite
// Priority-Score grid and the per-dimension matrix view. Controlled component:
// the parent owns the selected value and handles changes.
//
// Requirements: 16.2 (toggle between composite grid and dimension matrix).

import { Grid2x2, LayoutGrid } from 'lucide-react'

/** The two heatmap views the dashboard can render. */
export type HeatmapView = 'composite' | 'matrix'

interface HeatmapToggleProps {
  value: HeatmapView
  onChange: (view: HeatmapView) => void
}

interface ViewOption {
  view: HeatmapView
  label: string
  icon: typeof LayoutGrid
}

const OPTIONS: ViewOption[] = [
  { view: 'composite', label: 'Composite', icon: LayoutGrid },
  { view: 'matrix', label: 'Matrix', icon: Grid2x2 },
]

export default function HeatmapToggle({ value, onChange }: HeatmapToggleProps) {
  return (
    <div
      role="tablist"
      aria-label="Heatmap view"
      className="inline-flex items-center gap-1 rounded-lg border border-navy-700 bg-navy-900 p-1"
    >
      {OPTIONS.map(({ view, label, icon: Icon }) => {
        const active = value === view
        return (
          <button
            key={view}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(view)}
            className={[
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium',
              'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-healthy-400',
              active
                ? 'bg-navy-600 text-navy-50 shadow-card'
                : 'text-navy-300 hover:bg-navy-800 hover:text-navy-100',
            ].join(' ')}
          >
            <Icon size={15} aria-hidden />
            {label}
          </button>
        )
      })}
    </div>
  )
}
