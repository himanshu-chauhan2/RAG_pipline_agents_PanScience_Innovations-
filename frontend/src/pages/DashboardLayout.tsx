import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { getOrganization } from '../api/auth'
import type { Organization, Session } from '../api/auth'
import { toApiError } from '../api/client'
import type { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import Icon from '../components/Icon'
import type { IconName } from '../components/Icon'
import RequestError from '../components/RequestError'
import SystemStatus from '../components/SystemStatus'

const navigation: { path: string; label: string; icon: IconName }[] = [
  { path: '/dashboard/knowledge-base', label: 'Knowledge Base', icon: 'documents' },
  { path: '/dashboard/assistant', label: 'Assistant', icon: 'assistant' },
  { path: '/dashboard/usage', label: 'Usage', icon: 'usage' },
]

type OrganizationState =
  | { status: 'loading' }
  | { status: 'success'; organization: Organization }
  | { status: 'error'; error: ApiError }

export default function DashboardLayout({ session }: { session: Session }) {
  const { handleUnauthenticated } = useAuth()
  const [attempt, setAttempt] = useState(0)
  const [organization, setOrganization] = useState<OrganizationState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    setOrganization({ status: 'loading' })
    void getOrganization(session.organization.id, controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setOrganization({ status: 'success', organization: data })
      },
      (error: unknown) => {
        if (!controller.signal.aborted && !handleUnauthenticated(error)) {
          setOrganization({ status: 'error', error: toApiError(error) })
        }
      },
    )
    return () => controller.abort()
  }, [session.organization.id, attempt, handleUnauthenticated])

  function retryOrganization() {
    setOrganization({ status: 'loading' })
    setAttempt((current) => current + 1)
  }

  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="page-width grid items-start gap-8 py-8 sm:py-10 lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-12"
    >
      <aside aria-label="Your workspace" className="min-w-0">
        <div className="rounded-xl border border-line bg-white p-5">
          <p className="eyebrow mb-3">Your organisation</p>
          <p className="font-semibold leading-6 [overflow-wrap:anywhere]">
            {organization.status === 'success' ? organization.organization.name : session.organization.name}
          </p>
          <p className="mt-2 text-xs leading-5 text-muted">A dedicated organisation workspace.</p>
        </div>

        <nav aria-label="Dashboard" className="mt-5 flex flex-wrap gap-2 lg:flex-col">
          {navigation.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex min-h-12 items-center gap-3 rounded-lg px-4 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-accent text-white'
                    : 'text-muted hover:bg-sage hover:text-accent'
                }`
              }
            >
              <Icon name={item.icon} className="size-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <details className="mt-6 rounded-lg border border-line p-4 text-xs leading-5 text-muted">
          <summary className="cursor-pointer rounded-sm font-semibold text-ink">Account details</summary>
          <dl className="mt-4 space-y-3">
            <div>
              <dt className="font-medium">Signed in as</dt>
              <dd className="mt-1 [overflow-wrap:anywhere]">{session.user.full_name}</dd>
            </div>
            <div>
              <dt className="font-medium">Email</dt>
              <dd className="mt-1 [overflow-wrap:anywhere]">{session.user.email}</dd>
            </div>
            <div>
              <dt className="font-medium">Organisation ID</dt>
              <dd className="mt-1 break-all font-mono">{session.organization.id}</dd>
            </div>
            <div>
              <dt className="font-medium">Session expires</dt>
              <dd className="mt-1">
                <time dateTime={session.expires_at}>
                  {new Date(session.expires_at).toLocaleString()}
                </time>
              </dd>
            </div>
          </dl>
        </details>

        <div className="mt-6 hidden border-l-2 border-accent/25 pl-4 text-xs leading-5 text-muted lg:block">
          <p className="mb-1 font-semibold text-ink">Knowledge &amp; public assistant</p>
          Upload searchable PDFs, then share the public assistant link. Usage reporting is not yet available.
        </div>
      </aside>

      <div className="min-w-0">
        {organization.status === 'loading' ? (
          <section role="status" aria-live="polite" className="rounded-2xl border border-line bg-white p-8 sm:p-12">
            <Icon name="refresh" className="mb-5 size-6 text-accent motion-safe:animate-spin" />
            <h1 className="text-2xl font-semibold tracking-tight">Loading your workspace.</h1>
            <p className="mt-3 text-sm leading-6 text-muted">Verifying your organisation with the backend.</p>
          </section>
        ) : organization.status === 'error' ? (
          <section>
            <h1 className="mb-5 text-2xl font-semibold tracking-tight">Your workspace needs a check.</h1>
            <RequestError
              title="The organisation could not be loaded."
              error={organization.error}
              onRetry={retryOrganization}
              retryLabel="Retry organisation check"
            />
          </section>
        ) : (
          <Outlet />
        )}

        <details className="mt-8 rounded-xl border border-line bg-white/50">
          <summary className="cursor-pointer rounded-xl px-5 py-4 text-sm font-medium">
            Local system diagnostics
            <span className="ml-2 text-xs font-normal text-muted">API health &amp; gateway configuration</span>
          </summary>
          <div className="border-t border-line p-4 sm:p-6">
            <p className="mb-4 text-xs leading-5 text-muted">
              This is a local health check, not a gateway connectivity test. No model calls are made.
            </p>
            <SystemStatus />
          </div>
        </details>
      </div>
    </main>
  )
}
