import { useCallback, useEffect, useRef, useState } from 'react'
import { listDocuments } from '../api/documents'
import type { DocumentList } from '../api/documents'
import { ApiError, toApiError } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { nextDocumentPoll } from './polling'
import type { PollRound } from './polling'

interface Snapshot {
  data: DocumentList
  checkedAt: Date
}

interface LibraryState {
  snapshot: Snapshot | null
  refreshing: boolean
  stale: boolean
  error: ApiError | null
}

type MutationOutcome = 'accepted' | 'rejected' | 'uncertain' | 'cancelled'

export function useDocumentLibrary(organizationId: string) {
  const { handleUnauthenticated, handleWorkspaceChanged } = useAuth()
  const [state, setState] = useState<LibraryState>({
    snapshot: null,
    refreshing: true,
    stale: false,
    error: null,
  })
  const [mutationPending, setMutationPending] = useState(false)
  const [mutationError, setMutationError] = useState<ApiError | null>(null)
  const [notice, setNotice] = useState('')
  const [pollingPaused, setPollingPaused] = useState(false)
  const mounted = useRef(false)
  const busy = useRef(false)
  const listController = useRef<AbortController | null>(null)
  const mutationController = useRef<AbortController | null>(null)
  const pollTimer = useRef<number | null>(null)
  const round = useRef<PollRound>({ startedAt: performance.now(), checks: 0 })

  const cancelScheduledPoll = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }, [])

  const fetchSnapshot = useCallback(
    async (resetPolling: boolean): Promise<boolean> => {
      if (!mounted.current) return false
      cancelScheduledPoll()
      listController.current?.abort()
      const controller = new AbortController()
      listController.current = controller
      if (resetPolling) {
        round.current = { startedAt: performance.now(), checks: 0 }
        setPollingPaused(false)
      }
      setState((current) => ({ ...current, refreshing: true, error: null }))

      try {
        const data = await listDocuments({ organizationId, signal: controller.signal })
        if (controller.signal.aborted || !mounted.current) return false
        setState({
          snapshot: { data, checkedAt: new Date() },
          refreshing: false,
          stale: false,
          error: null,
        })
        return true
      } catch (error: unknown) {
        if (
          !controller.signal.aborted &&
          mounted.current &&
          !handleWorkspaceChanged(error) &&
          !handleUnauthenticated(error)
        ) {
          setState((current) => ({
            ...current,
            refreshing: false,
            stale: current.snapshot !== null,
            error: toApiError(error),
          }))
        }
        return false
      } finally {
        if (listController.current === controller) listController.current = null
      }
    },
    [cancelScheduledPoll, handleUnauthenticated, handleWorkspaceChanged, organizationId],
  )

  const refresh = useCallback(() => {
    if (!busy.current) void fetchSnapshot(true)
  }, [fetchSnapshot])

  const performMutation = useCallback(
    async <T>(
      operation: (signal: AbortSignal) => Promise<T>,
      successMessage: (result: T) => string,
    ): Promise<MutationOutcome> => {
      if (busy.current || !mounted.current) return 'cancelled'
      busy.current = true
      cancelScheduledPoll()
      listController.current?.abort()
      listController.current = null
      const controller = new AbortController()
      mutationController.current = controller
      setMutationPending(true)
      setMutationError(null)
      setNotice('')
      setState((current) => ({ ...current, refreshing: false }))

      try {
        const result = await operation(controller.signal)
        if (controller.signal.aborted || !mounted.current) return 'cancelled'
        setNotice(successMessage(result))
        setState((current) => ({ ...current, stale: current.snapshot !== null }))
        await fetchSnapshot(true)
        return mounted.current && !controller.signal.aborted ? 'accepted' : 'cancelled'
      } catch (error: unknown) {
        if (
          controller.signal.aborted ||
          !mounted.current ||
          handleWorkspaceChanged(error) ||
          handleUnauthenticated(error)
        ) return 'cancelled'
        const apiError = toApiError(error)
        const uncertain = apiError.kind !== 'http'
        const uncertaintyReason = apiError.kind === 'timeout'
          ? 'The document request timed out.'
          : apiError.kind === 'network'
            ? 'The API connection failed.'
            : 'The API returned an unexpected response.'
        setMutationError(uncertain
          ? new ApiError(
              apiError.kind,
              `${uncertaintyReason} The result is unconfirmed and the server may still complete it; review the refreshed list before submitting again.`,
              {
                status: apiError.status,
                code: apiError.code,
                requestId: apiError.requestId,
                fields: apiError.fields,
              },
            )
          : apiError)
        setState((current) => ({ ...current, stale: current.snapshot !== null }))
        await fetchSnapshot(true)
        if (controller.signal.aborted || !mounted.current) return 'cancelled'
        return uncertain ? 'uncertain' : 'rejected'
      } finally {
        if (mutationController.current === controller) {
          mutationController.current = null
          busy.current = false
          if (mounted.current) setMutationPending(false)
        }
      }
    },
    [cancelScheduledPoll, fetchSnapshot, handleUnauthenticated, handleWorkspaceChanged],
  )

  useEffect(() => {
    mounted.current = true
    void fetchSnapshot(true)
    return () => {
      mounted.current = false
      cancelScheduledPoll()
      listController.current?.abort()
      mutationController.current?.abort()
      listController.current = null
      mutationController.current = null
      busy.current = false
    }
  }, [fetchSnapshot, cancelScheduledPoll])

  useEffect(() => {
    if (!state.snapshot || state.refreshing || state.error || state.stale || mutationPending) return
    const documents = state.snapshot.data.documents
    const decision = nextDocumentPoll(documents, round.current, performance.now())
    if (decision.kind === 'idle') {
      setPollingPaused(false)
      return
    }
    if (decision.kind === 'paused') {
      setPollingPaused(true)
      return
    }
    pollTimer.current = window.setTimeout(() => {
      pollTimer.current = null
      if (!mounted.current || busy.current) return
      const next = nextDocumentPoll(documents, round.current, performance.now())
      if (next.kind !== 'schedule') {
        setPollingPaused(next.kind === 'paused')
        return
      }
      round.current.checks += 1
      void fetchSnapshot(false)
    }, decision.delayMs)
    return cancelScheduledPoll
  }, [state.snapshot, state.refreshing, state.error, state.stale, mutationPending, fetchSnapshot, cancelScheduledPoll])

  return {
    ...state,
    mutationPending,
    mutationError,
    notice,
    pollingPaused,
    refresh,
    performMutation,
    clearMutationError: () => setMutationError(null),
  }
}
