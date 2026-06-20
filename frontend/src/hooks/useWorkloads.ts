// Data-fetching hooks for workloads (list + single).

import { useCallback, useEffect, useState } from 'react'
import { getWorkload, getWorkloads } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { Workload } from '../types'

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

/** Fetch the full list of workloads. Returns data, loading, error, and refetch. */
export function useWorkloads() {
  const [state, setState] = useState<FetchState<Workload[]>>({
    data: null,
    loading: true,
    error: null,
  })

  const fetchData = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await getWorkloads()
      setState({ data, loading: false, error: null })
    } catch (err) {
      setState({ data: null, loading: false, error: errorMessage(err) })
    }
  }, [])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const data = await getWorkloads()
        if (active) setState({ data, loading: false, error: null })
      } catch (err) {
        if (active) setState({ data: null, loading: false, error: errorMessage(err) })
      }
    })()
    return () => {
      active = false
    }
  }, [])

  return { ...state, refetch: fetchData }
}

/** Fetch a single workload by id. Skips fetching when id is falsy. */
export function useWorkload(id: string | undefined) {
  const [state, setState] = useState<FetchState<Workload>>({
    data: null,
    loading: Boolean(id),
    error: null,
  })

  const fetchData = useCallback(async () => {
    if (!id) return
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await getWorkload(id)
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
        const data = await getWorkload(id)
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
