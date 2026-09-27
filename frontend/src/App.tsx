import { useEffect, useRef } from 'react'
import { BrowserRouter, Link, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import { Footer, Header } from './components/Chrome'
import Icon from './components/Icon'
import RequestError from './components/RequestError'
import AuthPage from './pages/AuthPage'
import DashboardLayout from './pages/DashboardLayout'
import FeaturePage from './pages/FeaturePage'

const titles: Record<string, string> = {
  '/': 'Workspace',
  '/login': 'Sign in',
  '/register': 'Create an account',
  '/dashboard': 'Dashboard',
  '/dashboard/knowledge-base': 'Knowledge Base',
  '/dashboard/assistant': 'Assistant',
  '/dashboard/usage': 'Usage',
}

function GuestRoute() {
  const { state } = useAuth()
  return state.status === 'authenticated' ? <Navigate to="/dashboard" replace /> : <Outlet />
}

function ProtectedDashboard() {
  const { state } = useAuth()
  return state.status === 'authenticated' ? (
    <DashboardLayout key={`${state.session.user.id}:${state.session.organization.id}`} session={state.session} />
  ) : (
    <Navigate to="/login" replace />
  )
}

function HomeRoute() {
  const { state } = useAuth()
  return <Navigate to={state.status === 'authenticated' ? '/dashboard' : '/login'} replace />
}

function NotFound() {
  return (
    <main id="main-content" tabIndex={-1} className="page-width py-16 sm:py-24">
      <p className="eyebrow mb-4">Page not found</p>
      <h1 className="text-3xl font-semibold tracking-tight">That page isn’t part of this workspace.</h1>
      <p className="mt-4 text-muted">Return to the workspace to continue.</p>
      <Link to="/" className="button-primary mt-7">Back to workspace <Icon name="arrow" className="size-4" /></Link>
    </main>
  )
}

function Workspace() {
  const { state, logoutState, retrySession, signOut } = useAuth()
  const { pathname } = useLocation()
  const previous = useRef({ pathname, status: state.status })

  useEffect(() => {
    document.title = `${titles[pathname] ?? 'Page not found'} · Knowledge & Decision Assistant`
    if (
      previous.current.pathname !== pathname ||
      (previous.current.status === 'loading' && state.status !== 'loading')
    ) {
      document.getElementById('main-content')?.focus()
    }
    previous.current = { pathname, status: state.status }
  }, [pathname, state.status])

  const isSigningOut = logoutState.status === 'pending'

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <Header>
        {state.status === 'authenticated' && (
          <div className="flex flex-wrap items-center gap-4">
            <div className="max-w-48">
              <p className="truncate text-sm font-semibold" title={state.session.user.full_name}>
                {state.session.user.full_name}
              </p>
              <p className="truncate text-xs text-muted" title={state.session.user.email}>
                {state.session.user.email}
              </p>
            </div>
            <button
              type="button"
              onClick={() => void signOut()}
              disabled={isSigningOut}
              className="button-secondary"
            >
              <Icon name={isSigningOut ? 'refresh' : 'logout'} className={`size-4 ${isSigningOut ? 'motion-safe:animate-spin' : ''}`} />
              {isSigningOut ? 'Signing out…' : 'Sign out'}
            </button>
          </div>
        )}
      </Header>

      {logoutState.status === 'error' && (
        <div className="page-width mt-6">
          <RequestError title="Sign-out could not be confirmed." error={logoutState.error}>
            <p className="mt-2">
              Your local session has not been cleared. Use <strong>Sign out</strong> to try again.
            </p>
          </RequestError>
        </div>
      )}
      <p role="status" aria-live="polite" className="sr-only">
        {isSigningOut ? 'Signing out of your current session.' : ''}
      </p>

      {state.status === 'loading' ? (
        <main id="main-content" tabIndex={-1} className="page-width py-16 sm:py-24">
          <div role="status" aria-live="polite" className="mx-auto max-w-lg rounded-2xl border border-line bg-white p-8 sm:p-10">
            <Icon name="refresh" className="mb-5 size-6 text-accent motion-safe:animate-spin" />
            <h1 className="text-2xl font-semibold tracking-tight">Checking your session.</h1>
            <p className="mt-3 text-sm leading-7 text-muted">
              We’re asking the backend before opening an account page or workspace.
            </p>
          </div>
        </main>
      ) : state.status === 'error' ? (
        <main id="main-content" tabIndex={-1} className="page-width py-16 sm:py-24">
          <div className="mx-auto max-w-xl">
            <p className="eyebrow mb-4">Session verification</p>
            <h1 className="mb-4 text-3xl font-semibold tracking-tight">Your session needs a check.</h1>
            <p className="mb-6 text-sm leading-7 text-muted">
              We couldn’t verify your session and have not assumed that you’re signed
              out. Retry the check to continue.
            </p>
            <RequestError
              title="Session check incomplete."
              error={state.error}
              onRetry={retrySession}
              retryLabel="Retry session check"
            />
          </div>
        </main>
      ) : (
        <Routes>
          <Route path="/" element={<HomeRoute />} />
          <Route element={<GuestRoute />}>
            <Route path="/login" element={<AuthPage key="login" mode="login" />} />
            <Route path="/register" element={<AuthPage key="register" mode="register" />} />
          </Route>
          <Route path="/dashboard" element={<ProtectedDashboard />}>
            <Route index element={<Navigate to="knowledge-base" replace />} />
            <Route path="knowledge-base" element={<FeaturePage section="knowledge-base" />} />
            <Route path="assistant" element={<FeaturePage section="assistant" />} />
            <Route path="usage" element={<FeaturePage section="usage" />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      )}
      <Footer />
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Workspace />
      </AuthProvider>
    </BrowserRouter>
  )
}
