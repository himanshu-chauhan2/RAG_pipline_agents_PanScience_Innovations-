import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { askAssistant } from '../api/assistant.ts'
import type { AskResult, ChatTurn } from '../api/assistant.ts'
import { toApiError } from '../api/client.ts'
import type { ApiError } from '../api/client.ts'
import { Footer, Header } from '../components/Chrome.tsx'
import RequestError from '../components/RequestError.tsx'

interface Exchange {
  question: string
  result: AskResult
}

const HISTORY_LIMIT = 10

export default function PublicChatPage() {
  const { token } = useParams<{ token: string }>()
  const [question, setQuestion] = useState('')
  const [exchanges, setExchanges] = useState<Exchange[]>([])
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const request = useRef<AbortController | null>(null)

  useEffect(() => {
    document.title = 'Public assistant · Knowledge & Decision Assistant'
    return () => request.current?.abort()
  }, [])

  function newChat() {
    request.current?.abort()
    request.current = null
    setQuestion('')
    setExchanges([])
    setError(null)
    setPending(false)
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = question.trim()
    if (!text || !token || pending || exchanges.length * 2 >= HISTORY_LIMIT) return
    const history: ChatTurn[] = exchanges.flatMap(({ question: prior, result }) => [
      { role: 'user', content: prior },
      { role: 'assistant', content: result.follow_up_question ?? result.answer },
    ])
    const controller = new AbortController()
    request.current = controller
    setPending(true)
    setError(null)
    try {
      const result = await askAssistant(token, text, history, controller.signal)
      if (controller.signal.aborted) return
      setExchanges((current) => [...current, { question: text, result }])
      setQuestion('')
    } catch (cause: unknown) {
      if (!controller.signal.aborted) setError(toApiError(cause))
    } finally {
      if (request.current === controller) {
        request.current = null
        setPending(false)
      }
    }
  }

  const full = exchanges.length * 2 >= HISTORY_LIMIT

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <Header />
      <main id="main-content" tabIndex={-1} className="page-width w-full py-8 sm:py-12">
        <div className="mx-auto max-w-3xl">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow mb-3">Public policy assistant</p>
              <h1 className="text-3xl font-semibold tracking-tight">Ask the knowledge base.</h1>
              <p className="mt-3 text-sm leading-6 text-muted">
                Answers come from this organisation’s indexed PDFs. Check citations before relying on a decision.
              </p>
            </div>
            <button type="button" className="button-secondary" onClick={newChat}>New chat</button>
          </div>

          <div aria-live="polite" className="mt-8 space-y-6">
            {exchanges.length === 0 && (
              <p className="rounded-xl border border-line bg-white p-6 text-sm leading-7 text-muted">
                Ask about a deadline, compare policies, or provide details for an eligibility check.
                If the uploaded documents cannot support an answer, the assistant will say so.
              </p>
            )}
            {exchanges.map(({ question: asked, result }, index) => (
              <article key={index} className="space-y-3">
                <div className="ml-auto max-w-[90%] rounded-xl bg-accent px-5 py-4 text-sm leading-6 text-white">
                  <span className="sr-only">You asked: </span>{asked}
                </div>
                <div className="rounded-xl border border-line bg-white p-5 sm:p-6">
                  <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">
                    {result.status === 'needs_info' ? 'More information needed' :
                      result.status === 'insufficient_evidence' ? 'Not enough evidence' : 'Answer'}
                    {result.verdict && ` · ${result.verdict.replaceAll('_', ' ')}`}
                  </p>
                  <p className="whitespace-pre-wrap text-sm leading-7">{result.answer}</p>
                  {result.follow_up_question && result.follow_up_question !== result.answer && (
                    <p className="mt-3 font-medium">{result.follow_up_question}</p>
                  )}
                  {result.references.length > 0 && (
                    <div className="mt-5 border-t border-line pt-4">
                      <h2 className="text-sm font-semibold">Source pages</h2>
                      <ul className="mt-2 space-y-2 text-xs leading-5">
                        {result.references.map((source) => (
                          <li key={source.id} className="rounded-lg bg-sage/60 px-3 py-2">
                            <strong>{source.document_name} — Page {source.page}</strong>
                            {source.quote && <span className="mt-1 block text-muted">“{source.quote}”</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {result.decision_trace && (
                    <details className="mt-4 rounded-lg border border-line p-4">
                      <summary className="cursor-pointer text-sm font-semibold">How I decided</summary>
                      <p className="mt-3 text-xs text-muted">{result.decision_trace.rule_set} · {result.decision_trace.verdict}</p>
                      <ul className="mt-3 space-y-2 text-sm">
                        {result.decision_trace.checks.map((check) => (
                          <li key={check.id} className="rounded-md bg-canvas p-3">
                            <strong>{check.result === null ? 'Unknown' : check.result ? 'Pass' : 'Fail'}: {check.label}</strong>
                            <span className="block text-xs text-muted">Observed: {check.observed ?? 'not provided'} · Rule: {check.requirement}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              </article>
            ))}
          </div>

          {error && <div className="mt-5"><RequestError title="Your question could not be processed." error={error} /></div>}
          {full && <p role="status" className="mt-5 text-sm text-warning">This chat has reached its context limit. Start a new chat and include the relevant facts.</p>}
          <form className="mt-7 rounded-xl border border-line bg-white p-4 sm:p-6" onSubmit={(event) => void submit(event)}>
            <label htmlFor="question" className="block text-sm font-semibold">Your question</label>
            <textarea id="question" className="field-input mt-2 min-h-28" value={question}
              onChange={(event) => setQuestion(event.target.value)} maxLength={1000}
              disabled={pending || full} placeholder="What would you like to know?" required />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-muted">{question.length}/1000 characters · Questions may be sent to the configured LLM service.</p>
              <button type="submit" className="button-primary" disabled={pending || full || !question.trim()}>
                {pending ? 'Checking the documents…' : 'Ask'}
              </button>
            </div>
          </form>
        </div>
      </main>
      <Footer />
    </div>
  )
}
