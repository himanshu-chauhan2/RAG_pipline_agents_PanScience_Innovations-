import { useEffect, useState } from 'react'
import { HealthCheckError, requestHealth } from '../api/health'
import type { HealthResponse } from '../api/health'

type HealthState =
  | { status: 'loading' }
  | { status: 'success'; data: HealthResponse; checkedAt: Date }
  | { status: 'error'; error: HealthCheckError }

export default function SystemStatus() {
  const [attempt, setAttempt] = useState(0)
  const [health, setHealth] = useState<HealthState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()

    void requestHealth(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) {
          setHealth({ status: 'success', data, checkedAt: new Date() })
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setHealth({
            status: 'error',
            error:
              error instanceof HealthCheckError
                ? error
                : new HealthCheckError(
                    'network',
                    'The health check could not be completed. Check the backend, then retry.',
                  ),
          })
        }
      },
    )

    return () => controller.abort()
  }, [attempt])

  const isLoading = health.status === 'loading'
  const isHealthy = health.status === 'success'
  const backendLabel = isHealthy
    ? 'Healthy'
    : isLoading
      ? 'Checking…'
      : health.error.kind === 'invalid-response'
        ? 'Unexpected response'
        : health.error.kind === 'timeout'
          ? 'Timed out'
          : 'Unavailable'
  const gatewayLabel = isHealthy
    ? health.data.gateway_configured
      ? 'Configured, not verified'
      : 'Setup needed'
    : isLoading
      ? 'Waiting for API'
      : 'Not checked'
  const announcement =
    health.status === 'error'
      ? `Health check failed. ${health.error.message} Gateway configuration has not been checked.`
      : isHealthy
        ? `Backend is healthy. Gateway configuration: ${gatewayLabel}. This does not verify gateway connectivity.`
        : 'Checking local backend health and gateway configuration.'

  function retryHealthCheck() {
    setHealth({ status: 'loading' })
    setAttempt((current) => current + 1)
  }

  return (
    <section
      id="system-status"
      aria-labelledby="status-heading"
      className="scroll-mt-8 overflow-hidden rounded-2xl border border-line bg-white shadow-[0_8px_40px_-20px_rgba(23,47,43,0.18)]"
    >
      <div role="status" aria-atomic="true" className="sr-only">
        {announcement}
      </div>

      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line px-6 py-6 sm:px-8">
        <div>
          <p className="eyebrow mb-2">Local connection</p>
          <h2 id="status-heading" className="text-xl font-semibold tracking-tight">
            System status
          </h2>
        </div>
        <span
          className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${
            isHealthy
              ? 'bg-sage text-accent'
              : isLoading
                ? 'bg-canvas text-muted'
                : 'bg-warning-soft text-warning'
          }`}
        >
          <span
            aria-hidden="true"
            className={`size-1.5 rounded-full bg-current ${isLoading ? 'motion-safe:animate-pulse' : ''}`}
          />
          {isHealthy ? 'Backend online' : isLoading ? 'Checking API' : 'Check needed'}
        </span>
      </div>

      <div className="px-6 sm:px-8">
        <dl aria-busy={isLoading} className="divide-y divide-line">
          <div className="status-row">
            <dt>
              <span className="block font-medium">Frontend</span>
              <span className="mt-1 block text-xs text-muted">Browser interface</span>
            </dt>
            <dd className="text-right font-medium text-accent">Ready</dd>
          </div>
          <div className="status-row">
            <dt>
              <span className="block font-medium">Backend API</span>
              <span className="mt-1 block text-xs text-muted">Live health check</span>
            </dt>
            <dd
              className={`text-right font-medium ${
                isHealthy ? 'text-accent' : isLoading ? 'text-muted' : 'text-warning'
              }`}
            >
              {backendLabel}
            </dd>
          </div>
          <div className="status-row">
            <dt>
              <span className="block font-medium">Gateway configuration</span>
              <span className="mt-1 block text-xs text-muted">Reported by the API</span>
            </dt>
            <dd
              className={`text-right font-medium ${
                isHealthy && !health.data.gateway_configured ? 'text-warning' : 'text-muted'
              }`}
            >
              {gatewayLabel}
            </dd>
          </div>
        </dl>

        {health.status === 'error' && (
          <div className="mb-5 rounded-lg border border-warning-line bg-warning-soft px-4 py-3 text-sm leading-relaxed text-warning">
            <p className="font-semibold">Health check incomplete</p>
            <p className="mt-1">{health.error.message}</p>
          </div>
        )}

        <p className="mb-6 rounded-lg bg-canvas px-4 py-3 text-xs leading-relaxed text-muted">
          Configuration presence does not verify gateway connectivity. This check
          does not contact the gateway.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 border-t border-line bg-canvas/60 px-6 py-5 sm:px-8">
        <div className="text-xs text-muted">
          <p className="font-mono">GET /api/health</p>
          <p className="mt-1.5">
            {isHealthy ? (
              <>
                v{health.data.version} · {health.data.phase} · Checked{' '}
                <time dateTime={health.checkedAt.toISOString()}>
                  {health.checkedAt.toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </time>
              </>
            ) : isLoading ? (
              'Waiting up to 8 seconds'
            ) : (
              'No verified health response'
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={retryHealthCheck}
          disabled={isLoading}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold transition-colors hover:border-accent/40 hover:bg-sage focus-visible:outline-offset-4 disabled:cursor-wait disabled:text-muted disabled:hover:border-line disabled:hover:bg-white"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={`size-4 ${isLoading ? 'motion-safe:animate-spin' : ''}`}
          >
            <path d="M16 8a6.2 6.2 0 0 0-10.5-2L3 8m0-4v4h4M4 12a6.2 6.2 0 0 0 10.5 2l2.5-2m0 4v-4h-4" />
          </svg>
          {isLoading ? 'Checking…' : isHealthy ? 'Check again' : 'Retry health check'}
        </button>
      </div>
    </section>
  )
}
