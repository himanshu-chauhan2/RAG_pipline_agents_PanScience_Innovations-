import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { getCurrentSession, logout } from '../api/auth'
import type { Session } from '../api/auth'
import { isUnauthenticatedError, toApiError } from '../api/client'
import type { ApiError } from '../api/client'

type SessionState =
  | { status: 'loading' }
  | { status: 'authenticated'; session: Session }
  | { status: 'anonymous' }
  | { status: 'error'; error: ApiError }

type LogoutState =
  | { status: 'idle' }
  | { status: 'pending' }
  | { status: 'error'; error: ApiError }

interface AuthContextValue {
  state: SessionState
  logoutState: LogoutState
  retrySession: () => void
  completeAuthentication: (session: Session) => void
  handleUnauthenticated: (error: unknown) => boolean
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' })
  const [logoutState, setLogoutState] = useState<LogoutState>({ status: 'idle' })
  const checkController = useRef<AbortController | null>(null)
  const logoutController = useRef<AbortController | null>(null)

  const clearConfirmedSession = useCallback(() => {
    checkController.current?.abort()
    logoutController.current?.abort()
    checkController.current = null
    logoutController.current = null
    setLogoutState({ status: 'idle' })
    setState({ status: 'anonymous' })
  }, [])

  const handleUnauthenticated = useCallback(
    (error: unknown) => {
      if (!isUnauthenticatedError(error)) return false
      clearConfirmedSession()
      return true
    },
    [clearConfirmedSession],
  )

  const retrySession = useCallback(() => {
    if (logoutController.current) return
    checkController.current?.abort()
    const controller = new AbortController()
    checkController.current = controller
    setState({ status: 'loading' })
    setLogoutState({ status: 'idle' })

    void getCurrentSession(controller.signal)
      .then(
        (session) => {
          if (!controller.signal.aborted) {
            setState({ status: 'authenticated', session })
          }
        },
        (error: unknown) => {
          if (!controller.signal.aborted && !handleUnauthenticated(error)) {
            setState({ status: 'error', error: toApiError(error) })
          }
        },
      )
      .finally(() => {
        if (checkController.current === controller) checkController.current = null
      })
  }, [handleUnauthenticated])

  const completeAuthentication = useCallback((session: Session) => {
    checkController.current?.abort()
    checkController.current = null
    setLogoutState({ status: 'idle' })
    setState({ status: 'authenticated', session })
  }, [])

  const signOut = useCallback(async () => {
    if (state.status !== 'authenticated' || logoutController.current) return
    const controller = new AbortController()
    logoutController.current = controller
    setLogoutState({ status: 'pending' })

    try {
      await logout(controller.signal)
      if (!controller.signal.aborted) clearConfirmedSession()
    } catch (error: unknown) {
      if (!controller.signal.aborted) {
        setLogoutState({ status: 'error', error: toApiError(error) })
      }
    } finally {
      if (logoutController.current === controller) logoutController.current = null
    }
  }, [state, clearConfirmedSession])

  useEffect(() => {
    retrySession()
    return () => {
      checkController.current?.abort()
      logoutController.current?.abort()
      checkController.current = null
      logoutController.current = null
    }
  }, [retrySession])

  useEffect(() => {
    if (state.status !== 'authenticated' || logoutState.status === 'pending') return

    const remaining = Date.parse(state.session.expires_at) - Date.now()
    const timeout = window.setTimeout(retrySession, Math.min(Math.max(remaining, 0), 2_147_483_647))
    const recheckOnFocus = () => {
      if (document.visibilityState === 'visible') retrySession()
    }
    window.addEventListener('focus', recheckOnFocus)
    return () => {
      clearTimeout(timeout)
      window.removeEventListener('focus', recheckOnFocus)
    }
  }, [state, logoutState.status, retrySession])

  return (
    <AuthContext.Provider
      value={{
        state,
        logoutState,
        retrySession,
        completeAuthentication,
        handleUnauthenticated,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('Authentication must be used within AuthProvider.')
  return context
}
