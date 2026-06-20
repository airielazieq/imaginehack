// Data-fetching hooks for issues (list with filters + single).

import { useCallback, useEffect, useMemo, useState } from 'react'
import { getIssue, getIssues, type IssueFilters } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { Issue } from '../types'

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
 * Fetch issues, optionally filtered. Re-fetches when filters change.
 * Returns data, loading, error, and a manual refetch.
 */
export function useIssues(filters?: IssueFilters) {
  const [state, setState] = useState<FetchState<Issue[]>>({
    data: null,
    loading: true,
    error: null,
  })

  // Stabilize the filters object so effect deps compare by value.
  const filterKey = useMemo(() => JSON.stringify(filters ?? {}), [filters])

  const fetchData = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await getIssues(filters)
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
        const data = await getIssues(filters ? JSON.parse(filterKey) : undefined)
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

/** Fetch a single issue by id. Skips fetching when id is falsy. */
export function useIssue(id: string | undefined) {
  const [state, setState] = useState<FetchState<Issue>>({
    data: null,
    loading: Boolean(id),
    error: null,
  })

  const fetchData = useCallback(async () => {
    if (!id) return
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await getIssue(id)
      setState({ data, loading: false, error: null })
    } catch (err) {
      setState({ data: null, loading: false, error: errorMessage(err) })
    }
  }, [id])

  useEffect(() => {
    if (!id) {
      setState({ data: null, loading: false, error: null })
      return
    }
    let active = true
    ;(async () => {
      try {
        const data = await getIssue(id)
        if (active) setState({ data, loading: false, error: null })
      } catch (err) {
        if (active) setState({ data: null, loading: false, error: errorMessage(err) })
      }
    })()
    return () => {
      active = false
    }
  }, [id])

  return { ...state, refetch: fetchData }
}
