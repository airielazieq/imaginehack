import { useMemo, useState, type ReactNode } from 'react'

/** A sortable/renderable column definition for {@link DataTable}. */
export interface Column<T> {
  /** Stable key for the column (also used as the React key). */
  key: string
  /** Header label. */
  header: ReactNode
  /**
   * Returns the raw, sortable/filterable value for a row. Required for the
   * column to be sortable or to participate in the global search filter.
   */
  accessor?: (row: T) => string | number | boolean | null | undefined
  /** Custom cell renderer. Falls back to the accessor value when omitted. */
  render?: (row: T) => ReactNode
  /** Allow clicking the header to sort by this column. Requires `accessor`. */
  sortable?: boolean
  /** Extra classes applied to the column's cells and header. */
  className?: string
}

type SortDirection = 'asc' | 'desc'

interface DataTableProps<T> {
  /** Column definitions in display order. */
  columns: Column<T>[]
  /** Row data. */
  rows: T[]
  /** Invoked when a row is clicked (makes rows interactive). */
  onRowClick?: (row: T) => void
  /** Stable id per row; defaults to the array index. */
  getRowId?: (row: T, index: number) => string
  /** Enable a client-side search box that filters across accessor values. */
  enableSearch?: boolean
  /** Placeholder for the search box. */
  searchPlaceholder?: string
  /** Message shown when there are no rows. */
  emptyMessage?: string
}

function compareValues(
  a: string | number | boolean | null | undefined,
  b: string | number | boolean | null | undefined,
): number {
  // Push nullish values to the end regardless of direction handling.
  if (a == null && b == null) return 0
  if (a == null) return 1
  if (b == null) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true })
}

/**
 * A reusable, generic table with header-click sorting and an optional
 * client-side search filter. Cells render via `column.render` or the column's
 * `accessor`. Sorting and filtering operate on `accessor` values.
 */
export default function DataTable<T>({
  columns,
  rows,
  onRowClick,
  getRowId,
  enableSearch = false,
  searchPlaceholder = 'Search…',
  emptyMessage = 'No results.',
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDirection>('asc')
  const [query, setQuery] = useState('')

  const handleSort = (column: Column<T>) => {
    if (!column.sortable || !column.accessor) return
    if (sortKey === column.key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(column.key)
      setSortDir('asc')
    }
  }

  const filteredRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!enableSearch || q === '') return rows
    const searchable = columns.filter((c) => c.accessor)
    return rows.filter((row) =>
      searchable.some((c) => {
        const value = c.accessor!(row)
        return value != null && String(value).toLowerCase().includes(q)
      }),
    )
  }, [rows, columns, query, enableSearch])

  const sortedRows = useMemo(() => {
    if (!sortKey) return filteredRows
    const column = columns.find((c) => c.key === sortKey)
    if (!column?.accessor) return filteredRows
    const accessor = column.accessor
    const copy = [...filteredRows]
    copy.sort((a, b) => {
      const result = compareValues(accessor(a), accessor(b))
      return sortDir === 'asc' ? result : -result
    })
    return copy
  }, [filteredRows, columns, sortKey, sortDir])

  const sortIndicator = (column: Column<T>) => {
    if (!column.sortable || !column.accessor) return null
    if (sortKey !== column.key) return <span className="text-navy-500">↕</span>
    return <span className="text-healthy-700">{sortDir === 'asc' ? '↑' : '↓'}</span>
  }

  return (
    <div className="flex flex-col gap-3">
      {enableSearch && (
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={searchPlaceholder}
          className="w-full max-w-xs rounded-lg border border-navy-700 bg-navy-900 px-3 py-2 text-sm text-navy-100 placeholder:text-navy-400 focus:border-healthy-500 focus:outline-none"
        />
      )}

      <div className="card overflow-hidden">
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-navy-700 text-navy-300">
              {columns.map((column) => {
                const interactive = column.sortable && column.accessor
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={
                      sortKey === column.key
                        ? sortDir === 'asc'
                          ? 'ascending'
                          : 'descending'
                        : undefined
                    }
                    className={[
                      'px-4 py-3 text-xs font-semibold uppercase tracking-wider',
                      interactive ? 'cursor-pointer select-none hover:text-navy-50' : '',
                      column.className ?? '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onClick={interactive ? () => handleSort(column) : undefined}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      {column.header}
                      {sortIndicator(column)}
                    </span>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {sortedRows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-10 text-center text-navy-300"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              sortedRows.map((row, index) => (
                <tr
                  key={getRowId ? getRowId(row, index) : index}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={[
                    'border-b border-navy-800 last:border-0 transition-colors',
                    onRowClick ? 'cursor-pointer hover:bg-navy-900' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={['px-4 py-3 text-navy-100', column.className ?? '']
                        .filter(Boolean)
                        .join(' ')}
                    >
                      {column.render
                        ? column.render(row)
                        : column.accessor
                          ? String(column.accessor(row) ?? '—')
                          : null}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
