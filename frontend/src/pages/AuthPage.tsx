import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { login, register } from '../api/auth'
import type { RegisterInput, Session } from '../api/auth'
import { toApiError } from '../api/client'
import type { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import Icon from '../components/Icon'
import { serverFieldErrors, validateLogin, validateRegistration } from '../validation/auth'
import type { AuthField, FieldErrors } from '../validation/auth'

const fieldLabels: Record<AuthField, string> = {
  organization_name: 'Organisation name',
  full_name: 'Full name',
  email: 'Email address',
  password: 'Password',
}

export default function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const isRegistration = mode === 'register'
  const { completeAuthentication } = useAuth()
  const [values, setValues] = useState<RegisterInput>({
    organization_name: '',
    full_name: '',
    email: '',
    password: '',
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [requestError, setRequestError] = useState<ApiError | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [failureCount, setFailureCount] = useState(0)
  const controllerRef = useRef<AbortController | null>(null)
  const errorRef = useRef<HTMLDivElement>(null)

  useEffect(() => () => controllerRef.current?.abort(), [])
  useEffect(() => {
    if (failureCount > 0) errorRef.current?.focus()
  }, [failureCount])

  function updateField(field: AuthField, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
    setRequestError(null)
  }

  function showValidationErrors(fieldErrors: FieldErrors) {
    setErrors(fieldErrors)
    setRequestError(null)
    setFailureCount((count) => count + 1)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (controllerRef.current) return
    let sendRequest: (signal: AbortSignal) => Promise<Session>
    if (isRegistration) {
      const validation = validateRegistration(values)
      if (!validation.valid) {
        showValidationErrors(validation.errors)
        return
      }
      sendRequest = (signal) => register(validation.data, signal)
    } else {
      const validation = validateLogin(values)
      if (!validation.valid) {
        showValidationErrors(validation.errors)
        return
      }
      sendRequest = (signal) => login(validation.data, signal)
    }

    const controller = new AbortController()
    controllerRef.current = controller
    setErrors({})
    setRequestError(null)
    setIsSubmitting(true)
    try {
      const session = await sendRequest(controller.signal)
      if (!controller.signal.aborted) completeAuthentication(session)
    } catch (error: unknown) {
      if (!controller.signal.aborted) {
        const apiError = toApiError(error)
        setRequestError(apiError)
        setErrors(serverFieldErrors(apiError.fields))
        setFailureCount((count) => count + 1)
      }
    } finally {
      if (!controller.signal.aborted) setIsSubmitting(false)
      if (controllerRef.current === controller) controllerRef.current = null
    }
  }

  const visibleFields: AuthField[] = isRegistration
    ? ['organization_name', 'full_name', 'email', 'password']
    : ['email', 'password']
  const hasErrors = requestError !== null || visibleFields.some((field) => Boolean(errors[field]))

  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="page-width grid items-start gap-10 py-10 sm:py-16 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-20"
    >
      <section aria-labelledby="project-heading" className="lg:pt-8">
        <p className="eyebrow mb-5">PanScience hackathon submission</p>
        <h2
          id="project-heading"
          className="max-w-xl text-[clamp(2rem,4vw,3.5rem)] leading-[1.12] font-semibold tracking-[-0.045em]"
        >
          Your knowledge.
          <br />
          <span className="text-accent">A clearer starting point.</span>
        </h2>
        <p className="mt-5 max-w-lg text-base leading-7 text-muted sm:text-lg sm:leading-8">
          A dedicated workspace for your organisation, built one verified phase
          at a time. Manage private PDFs today; grounded answers come next.
        </p>
        <div className="mt-8 hidden max-w-lg rounded-xl border border-line bg-white/60 p-6 sm:block">
          <p className="mb-4 text-sm font-semibold">This checkpoint, honestly.</p>
          <ul className="space-y-3 text-sm leading-6 text-muted">
            <li className="flex items-start gap-3">
              <Icon name="check" className="mt-0.5 size-5 text-accent" />
              Organisation accounts and a protected dashboard.
            </li>
            <li className="flex items-start gap-3">
              <Icon name="lock" className="mt-0.5 size-5 text-accent" />
              A server-managed session, not a browser-stored token.
            </li>
            <li className="flex items-start gap-3">
              <Icon name="documents" className="mt-0.5 size-5 text-accent" />
              Private PDF uploads, replacement and local indexing.
            </li>
            <li className="border-t border-line pt-3">
              Assistant publishing, chat and usage reporting are not implemented in P2.
            </li>
          </ul>
        </div>
        <p className="mt-5 text-xs leading-5 text-muted">
          An independent project, not an official PanScience service.
        </p>
      </section>

      <section
        aria-labelledby="auth-heading"
        className="rounded-2xl border border-line bg-white p-6 shadow-[0_8px_40px_-20px_rgba(23,47,43,0.18)] sm:p-8"
      >
        <p className="eyebrow mb-3">{isRegistration ? 'Make space for your organisation' : 'Your workspace awaits'}</p>
        <h1 id="auth-heading" className="text-3xl font-semibold tracking-tight">
          {isRegistration ? 'Create an account.' : 'Welcome back.'}
        </h1>
        <p className="mt-3 text-sm leading-6 text-muted">
          {isRegistration
            ? 'Register your organisation and sign in automatically.'
            : 'Sign in to your organisation’s workspace.'}
        </p>

        <form onSubmit={submit} noValidate aria-labelledby="auth-heading" className="mt-7 space-y-5">
          {hasErrors && (
            <div
              ref={errorRef}
              tabIndex={-1}
              role="alert"
              className="rounded-lg border border-warning-line bg-warning-soft p-4 text-sm leading-6 text-warning"
            >
              <p className="font-semibold">{requestError ? 'Request not completed' : 'Check your details'}</p>
              <p>{requestError?.message ?? 'Review the highlighted fields, then try again.'}</p>
              {visibleFields.some((field) => Boolean(errors[field])) && (
                <ul className="mt-2 space-y-1">
                  {visibleFields.map((field) =>
                    errors[field] ? (
                      <li key={field}>
                        <a href={`#${mode}-${field}`} className="underline underline-offset-2">
                          {fieldLabels[field]}: {errors[field]}
                        </a>
                      </li>
                    ) : null,
                  )}
                </ul>
              )}
              {requestError?.requestId && (
                <p className="mt-2 break-all font-mono text-xs">Request reference: {requestError.requestId}</p>
              )}
              {isRegistration && (requestError?.kind === 'network' || requestError?.kind === 'timeout') && (
                <p className="mt-2">
                  Your account may already have been created. You can also{' '}
                  <Link to="/login" className="font-semibold underline underline-offset-2">try signing in</Link>.
                </p>
              )}
            </div>
          )}

          {visibleFields.map((field) => {
            const id = `${mode}-${field}`
            const isPassword = field === 'password'
            const hint = isPassword && isRegistration ? `${id}-hint` : undefined
            const errorId = errors[field] ? `${id}-error` : undefined
            const describedBy = [hint, errorId].filter(Boolean).join(' ') || undefined
            const autocomplete =
              field === 'organization_name'
                ? 'organization'
                : field === 'full_name'
                  ? 'name'
                  : field === 'email'
                    ? isRegistration ? 'email' : 'username'
                    : isRegistration ? 'new-password' : 'current-password'

            return (
              <div key={field}>
                <label htmlFor={id} className="mb-2 block text-sm font-medium">
                  {fieldLabels[field]}
                </label>
                <div className="relative">
                  <input
                    id={id}
                    name={field}
                    type={isPassword ? showPassword ? 'text' : 'password' : field === 'email' ? 'email' : 'text'}
                    value={values[field]}
                    onChange={(event) => updateField(field, event.target.value)}
                    autoComplete={autocomplete}
                    autoCapitalize={field === 'email' || isPassword ? 'none' : undefined}
                    spellCheck={field === 'email' || isPassword ? false : undefined}
                    aria-invalid={errors[field] ? true : undefined}
                    aria-describedby={describedBy}
                    disabled={isSubmitting}
                    required
                    className={`field-input ${isPassword ? 'pr-20' : ''}`}
                  />
                  {isPassword && (
                    <button
                      type="button"
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      aria-pressed={showPassword}
                      disabled={isSubmitting}
                      onClick={() => setShowPassword((current) => !current)}
                      className="absolute inset-y-1 right-2 min-w-14 rounded-md px-2 text-xs font-semibold text-accent hover:bg-sage disabled:opacity-60"
                    >
                      {showPassword ? 'Hide' : 'Show'}
                    </button>
                  )}
                </div>
                {hint && (
                  <p id={hint} className="mt-2 text-xs leading-5 text-muted">
                    At least 8 characters, up to 72 UTF-8 bytes. Spaces are
                    preserved, but the password cannot be only whitespace.
                  </p>
                )}
                {errors[field] && (
                  <p id={errorId} className="mt-2 text-xs leading-5 text-warning">{errors[field]}</p>
                )}
              </div>
            )
          })}

          <button type="submit" disabled={isSubmitting} className="button-primary w-full">
            {isSubmitting ? (
              <>
                <Icon name="refresh" className="size-4 motion-safe:animate-spin" />
                {isRegistration ? 'Creating account…' : 'Signing in…'}
              </>
            ) : (
              <>
                {isRegistration ? 'Create account' : 'Sign in'}
                <Icon name="arrow" className="size-4" />
              </>
            )}
          </button>
          <p role="status" aria-live="polite" className="sr-only">
            {isSubmitting ? isRegistration ? 'Creating your account.' : 'Signing you in.' : ''}
          </p>
        </form>

        <p className="mt-6 border-t border-line pt-5 text-center text-sm leading-6 text-muted">
          {isRegistration ? 'Already have an account?' : 'New to this workspace?'}{' '}
          <Link
            to={isRegistration ? '/login' : '/register'}
            className="rounded-sm font-semibold text-accent underline-offset-4 hover:underline"
          >
            {isRegistration ? 'Sign in' : 'Create an account'}
          </Link>
        </p>
      </section>
    </main>
  )
}
