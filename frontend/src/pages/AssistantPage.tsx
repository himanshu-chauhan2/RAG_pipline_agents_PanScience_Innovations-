import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getAssistant } from '../api/assistant.ts'
import { toApiError } from '../api/client.ts'
import type { ApiError } from '../api/client.ts'
import { useAuth } from '../auth/AuthProvider.tsx'
import RequestError from '../components/RequestError.tsx'

type AssistantState =
  | { status: 'loading' }
  | { status: 'ready'; token: string }
  | { status: 'error'; error: ApiError }

export default function AssistantPage() {
  const { state: auth, handleUnauthenticated, handleWorkspaceChanged } = useAuth()
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<AssistantState>({ status: 'loading' })
  const [copyError, setCopyError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    if (auth.status !== 'authenticated') return () => controller.abort()
    void getAssistant(controller.signal, auth.session.organization.id).then(
      ({ token }) => {
        if (!controller.signal.aborted) setState({ status: 'ready', token })
      },
      (error: unknown) => {
        if (!controller.signal.aborted && !handleUnauthenticated(error) && !handleWorkspaceChanged(error)) {
          setState({ status: 'error', error: toApiError(error) })
        }
      },
    )
    return () => controller.abort()
  }, [attempt, auth, handleUnauthenticated, handleWorkspaceChanged])

  if (auth.status !== 'authenticated') return null

  const token = state.status === 'ready' ? state.token : ''
  const link = token ? `${window.location.origin}/a/${encodeURIComponent(token)}` : ''
  const embed = `<iframe src="${link}" title="Policy assistant" width="100%" height="620" style="border:1px solid #dce2db;border-radius:12px" loading="lazy" referrerpolicy="no-referrer"></iframe>`

  async function copy(text: string) {
    setCopyError('')
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      setCopyError('Clipboard access is unavailable. Select and copy the text manually.')
    }
  }

  return (
    <section aria-labelledby="assistant-heading">
      <p className="eyebrow mb-4">Public assistant</p>
      <h1 id="assistant-heading" className="text-3xl font-semibold tracking-tight">Share your knowledge assistant.</h1>
      <p className="mt-3 text-sm leading-7 text-muted">
        Visitors can ask questions without signing in. Answers use only Ready PDFs in this organisation.
        Treat this link as public; do not upload confidential policies to a publicly shared assistant.
      </p>
      {state.status === 'loading' ? (
        <p role="status" className="mt-8">Loading your assistant link…</p>
      ) : state.status === 'error' ? (
        <div className="mt-8">
          <RequestError title="The assistant link could not be loaded." error={state.error}
            onRetry={() => { setState({ status: 'loading' }); setAttempt((value) => value + 1) }} />
        </div>
      ) : (
        <div className="mt-8 space-y-6 rounded-2xl border border-line bg-white p-5 sm:p-8">
          <div>
            <label htmlFor="assistant-url" className="block text-sm font-semibold">Public link</label>
            <input id="assistant-url" className="field-input mt-2" readOnly value={link} onFocus={(event) => event.currentTarget.select()} />
            <div className="mt-3 flex flex-wrap gap-3">
              <button type="button" className="button-secondary" onClick={() => void copy(link)}>Copy link</button>
              <Link className="button-primary" to={`/a/${encodeURIComponent(token)}`} target="_blank" rel="noreferrer">Open assistant</Link>
            </div>
          </div>
          <div>
            <label htmlFor="assistant-embed" className="block text-sm font-semibold">Iframe embed code</label>
            <textarea id="assistant-embed" className="field-input mt-2 min-h-32 font-mono text-xs" readOnly
              value={embed} onFocus={(event) => event.currentTarget.select()} />
            <button type="button" className="button-secondary mt-3" onClick={() => void copy(embed)}>Copy embed code</button>
          </div>
          {copyError && <p role="alert" className="text-sm text-warning">{copyError}</p>}
          <p className="text-xs leading-6 text-muted">
            Embed code works on another website once the frontend is hosted on a reachable origin.
            The local example is in demo/external-site.html.
          </p>
        </div>
      )}
    </section>
  )
}
