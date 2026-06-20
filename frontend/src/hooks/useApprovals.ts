// Data-fetching hook for the global approval queue.
//
// Polls on POLLING_INTERVALS.approvals because escalation countdowns are
// time-sensitive (design.md §Approval Queue). Exposes a manual refetch so the
// page can refresh immediately after an approve/deny/snooze action.

import { useCallback, useEffect, useRef, useState } from 'react'
import { getApprovals } from '../api/endpoints'
import { ApiError } from '../api/client'
import { POLLING_INTERVALS } from '../lib/constants'
import type { ApprovalItem } from '../types'

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
 * Fetch the severity-sorted approval queue and keep it fresh by polling.
 * `includeResolved` adds approved/denied items to the result.
 */
export function useApprovals(includeResolved = false) {
  const [state, setState] = useState<FetchState<ApprovalItem[]>>({
    data: null,
    loading: true,
    error: null,
  })
  const activeRef = useRef(true)

  const load = useCallback(
    async (showSpinner: boolean) => {
      if (showSpinner) setState((s) => ({ ...s, loading: true, error: null }))
      try {
        const data = await getApprovals(includeResolved)
        if (activeRef.current) setState({ data, loading: false, error: null })
      } catch (err) {
        if (activeRef.current)
          setState((s) => ({ ...s, loading: false, error: errorMessage(err) }))
      }
    },
    [includeResolved],
  )

  const refetch = useCallback(() => load(false), [load])

  useEffect(() => {
    activeRef.current = true
    load(true)
    const id = window.setInterval(() => load(false), POLLING_INTERVALS.approvals)
    return () => {
      activeRef.current = false
      window.clearInterval(id)
    }
  }, [load])

  return { ...state, refetch }
}
