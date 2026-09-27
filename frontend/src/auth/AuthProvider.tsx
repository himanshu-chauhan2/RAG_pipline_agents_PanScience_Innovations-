import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { logout } from '../api/auth'
import type { Session } from '../api/auth'
import { isUnauthenticatedError, isWorkspaceChangedError, toApiError } from '../api/client'
import type { ApiError } from '../api/client'
import { verifySession } from './verification'

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
  workspaceReviewRequired: boolean
  workspaceRevision: number
  retrySession: () => void
  completeAuthentication: (session: Session) => void
  handleUnauthenticated: (error: unknown) => boolean
  handleWorkspaceChanged: (error: unknown) => boolean
  acknowledgeWorkspace: () => void
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' })
  const [logoutState, setLogoutState] = useState<LogoutState>({ status: 'idle' })
  const [workspaceReviewRequired, setWorkspaceReviewRequired] = useState(false)
  const [workspaceRevision, setWorkspaceRevision] = useState(0)
  const verifiedSession = useRef<Session | null>(null)
  const recheckAfterLogout = useRef(false)
  const checkController = useRef<AbortController | null>(null)
  const logoutController = useRef<AbortController | null>(null)

  const clearConfirmedSession = useCallback(() => {
    checkController.current?.abort()
    logoutController.current?.abort()
    checkController.current = null
    logoutController.current = null
    verifiedSession.current = null
    recheckAfterLogout.current = false
    setWorkspaceReviewRequired(false)
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

  const checkSession = useCallback((background = false) => {
    if (logoutController.current) return
    checkController.current?.abort()
    const controller = new AbortController()
    checkController.current = controller
    void verifySession({
      current: verifiedSession.current,
      signal: controller.signal,
      background,
      onBlocking: () => setState({ status: 'loading' }),
    })
      .then((result) => {
        if (controller.signal.aborted || result.status === 'cancelled') return
        if (result.status === 'anonymous') {
          clearConfirmedSession()
        } else if (result.status === 'error') {
          setState({ status: 'error', error: result.error })
        } else {
          if (result.identityChanged) setWorkspaceReviewRequired(true)
          verifiedSession.current = result.session
          setState({ status: 'authenticated', session: result.session })
        }
      })
      .finally(() => {
        if (checkController.current === controller) checkController.current = null
      })
  }, [clearConfirmedSession])

  const retrySession = useCallback(() => checkSession(), [checkSession])

  const handleWorkspaceChanged = useCallback((error: unknown) => {
    if (!isWorkspaceChangedError(error)) return false
    checkController.current?.abort()
    setWorkspaceReviewRequired(true)
    // Reset selections even if loading and a same-identity result are batched into one render.
    setWorkspaceRevision((revision) => revision + 1)
    setState({ status: 'loading' })
    if (logoutController.current) recheckAfterLogout.current = true
    else checkSession()
    return true
  }, [checkSession])

  const acknowledgeWorkspace = useCallback(() => setWorkspaceReviewRequired(false), [])

  const completeAuthentication = useCallback((session: Session) => {
    checkController.current?.abort()
    checkController.current = null
    verifiedSession.current = session
    setWorkspaceReviewRequired(false)
    setLogoutState({ status: 'idle' })
    setState({ status: 'authenticated', session })
  }, [])

  const signOut = useCallback(async () => {
    if (state.status !== 'authenticated' || logoutController.current) return
    checkController.current?.abort()
    checkController.current = null
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
      if (logoutController.current === controller) {
        logoutController.current = null
        if (recheckAfterLogout.current) {
          recheckAfterLogout.current = false
          checkSession()
        }
      }
    }
  }, [state, clearConfirmedSession, checkSession])

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
      if (document.visibilityState === 'visible') {
        // Closing a native file picker must not discard an unexpired workspace.
        checkSession(true)
      }
    }
    window.addEventListener('focus', recheckOnFocus)
    return () => {
      clearTimeout(timeout)
      window.removeEventListener('focus', recheckOnFocus)
    }
  }, [state, logoutState.status, retrySession, checkSession])

  return (
    <AuthContext.Provider
      value={{
        state,
        logoutState,
        workspaceReviewRequired,
        workspaceRevision,
        retrySession,
        completeAuthentication,
        handleUnauthenticated,
        handleWorkspaceChanged,
        acknowledgeWorkspace,
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
