// Data-fetching hook for the append-only audit trail (list with filters).

import { useCallback, useEffect, useMemo, useState } from 'react'
import { getAuditLogs, type AuditLogFilters } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { AuditLog } from '../types'

interface FetchState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Unexpected error'
}

/**
 * Fetch audit logs, optionally filtered by workload, event type, and date
 * range. Re-fetches when filters change. Returns data, loading, error, and a
 * manual refetch. Entries are immutable and arrive most-recent-first.
 */
export function useAuditLogs(filters?: AuditLogFilters) {
  const [state, setState] = useState<FetchState<AuditLog[]>>({
    data: null,
    loading: true,
    error: null,
  })

  // Stabilize the filters object so effect deps compare by value.
  const filterKey = useMemo(() => JSON.stringify(filters ?? {}), [filters])

  const fetchData = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await getAuditLogs(filters)
      setState({ data, loading: false, error: null })
    } catch (err) {
      setState({ data: null, loading: false, error: errorMessage(err) })
    }
    // fetchData only depends on the serialized filters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  useEffect(() => {
    let active = true
    ;(async () => {
      setState((s) => ({ ...s, loading: true, error: null }))
      try {
        const data = await getAuditLogs(filters ? JSON.parse(filterKey) : undefined)
        if (active) setState({ data, loading: false, error: null })
      } catch (err) {
        if (active) setState({ data: null, loading: false, error: errorMessage(err) })
      }
    })()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  return { ...state, refetch: fetchData }
}
