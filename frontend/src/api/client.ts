export interface ApiErrorResponse {
  error: {
    code: string
    message: string
    request_id: string
    fields?: Record<string, string>
  }
}

type ApiErrorKind = 'http' | 'invalid-response' | 'network' | 'timeout'

interface ErrorDetails {
  status?: number
  code?: string
  requestId?: string
  fields?: Record<string, string>
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number | undefined
  readonly code: string | undefined
  readonly requestId: string | undefined
  readonly fields: Record<string, string> | undefined

  constructor(kind: ApiErrorKind, message: string, details: ErrorDetails = {}) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = details.status
    this.code = details.code
    this.requestId = details.requestId
    this.fields = details.fields
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isNonemptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

export function isIsoDateTime(value: unknown): value is string {
  if (
    typeof value !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) ||
    !Number.isFinite(Date.parse(value))
  ) {
    return false
  }
  const calendarDate = value.slice(0, 10)
  const midnight = new Date(`${calendarDate}T00:00:00Z`)
  return Number.isFinite(midnight.getTime()) && midnight.toISOString().slice(0, 10) === calendarDate
}

export function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  if (!isRecord(value) || !isRecord(value.error)) {
    return false
  }
  const error = value.error
  return (
    isNonemptyString(error.code) &&
    isNonemptyString(error.message) &&
    isNonemptyString(error.request_id) &&
    (error.fields === undefined ||
      (isRecord(error.fields) &&
        Object.values(error.fields).every((message) => typeof message === 'string')))
  )
}

export function isUnauthenticatedError(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.kind === 'http' &&
    error.status === 401 &&
    error.code === 'unauthenticated'
  )
}

export function isWorkspaceChangedError(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.kind === 'http' &&
    error.status === 409 &&
    error.code === 'workspace_changed'
  )
}

export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError('network', 'The request could not be completed. Please retry.')
}

interface RequestOptions {
  signal: AbortSignal
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  successStatus?: number
  timeoutMs?: number
  expectedOrganizationId?: string
}

async function request<T>(
  path: `/api/${string}`,
  options: RequestOptions,
  readResponse: (response: Response) => Promise<T>,
): Promise<T> {
  if (options.signal.aborted) {
    throw new DOMException('The request was cancelled.', 'AbortError')
  }

  const controller = new AbortController()
  const cancel = () => controller.abort()
  let timedOut = false
  options.signal.addEventListener('abort', cancel, { once: true })
  const timeout = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, options.timeoutMs ?? 8_000)

  try {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (options.expectedOrganizationId !== undefined) {
      headers['X-Organization-ID'] = options.expectedOrganizationId
    }
    let body: BodyInit | undefined
    if (options.body instanceof FormData) {
      body = options.body
    } else if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify(options.body)
    }

    const response = await fetch(path, {
      method: options.method ?? 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      headers,
      body,
      signal: controller.signal,
    })
    controller.signal.throwIfAborted()

    if (!response.ok) {
      const payload: unknown = await response.json()
      controller.signal.throwIfAborted()
      if (!isApiErrorResponse(payload)) {
        throw new ApiError(
          'invalid-response',
          'The API returned an unexpected error response. Please retry.',
          { status: response.status },
        )
      }
      throw new ApiError('http', payload.error.message, {
        status: response.status,
        code: payload.error.code,
        requestId: payload.error.request_id,
        fields: payload.error.fields,
      })
    }

    if (response.status !== (options.successStatus ?? 200)) {
      throw new ApiError(
        'invalid-response',
        'The API returned an unexpected response status. Please retry.',
        { status: response.status },
      )
    }

    const result = await readResponse(response)
    controller.signal.throwIfAborted()
    return result
  } catch (error: unknown) {
    if (options.signal.aborted) {
      throw new DOMException('The request was cancelled.', 'AbortError')
    }
    if (timedOut) {
      throw new ApiError(
        'timeout',
        'The request timed out. Its result could not be confirmed. Please retry.',
      )
    }
    if (error instanceof ApiError) {
      throw error
    }
    if (error instanceof SyntaxError) {
      throw new ApiError(
        'invalid-response',
        'The API did not return valid JSON. Check the backend and retry.',
      )
    }
    throw new ApiError(
      'network',
      'The API could not be reached. Check your connection and the local backend, then retry.',
    )
  } finally {
    clearTimeout(timeout)
    options.signal.removeEventListener('abort', cancel)
  }
}

export function requestJson<T>(
  path: `/api/${string}`,
  guard: (value: unknown) => value is T,
  options: RequestOptions,
): Promise<T> {
  return request(path, options, async (response) => {
    const payload: unknown = await response.json()
    if (!guard(payload)) {
      throw new ApiError(
        'invalid-response',
        'The API response does not match the expected contract. Please retry.',
      )
    }
    return payload
  })
}

export function requestNoContent(
  path: `/api/${string}`,
  options: RequestOptions,
): Promise<void> {
  return request(path, { ...options, successStatus: 204 }, async () => undefined)
}
