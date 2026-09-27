export interface HealthResponse {
  status: 'ok'
  service: 'knowledge-decision-assistant'
  version: '0.1.0'
  phase: 'P1'
  gateway_configured: boolean
}

export type HealthErrorKind = 'http' | 'invalid-response' | 'network' | 'timeout'

export class HealthCheckError extends Error {
  readonly kind: HealthErrorKind

  constructor(kind: HealthErrorKind, message: string) {
    super(message)
    this.name = 'HealthCheckError'
    this.kind = kind
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isHealthResponse(value: unknown): value is HealthResponse {
  return (
    isRecord(value) &&
    value.status === 'ok' &&
    value.service === 'knowledge-decision-assistant' &&
    value.version === '0.1.0' &&
    value.phase === 'P1' &&
    typeof value.gateway_configured === 'boolean'
  )
}

export async function requestHealth(
  signal: AbortSignal,
  timeoutMs = 8_000,
): Promise<HealthResponse> {
  if (signal.aborted) {
    throw new DOMException('The health check was cancelled.', 'AbortError')
  }

  const controller = new AbortController()
  const cancel = () => controller.abort()
  let timedOut = false

  signal.addEventListener('abort', cancel, { once: true })
  const timeout = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  try {
    const response = await fetch('/api/health', {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal: controller.signal,
    })

    controller.signal.throwIfAborted()

    if (!response.ok) {
      throw new HealthCheckError(
        'http',
        `The local API returned HTTP ${response.status}. Check the backend logs, then retry.`,
      )
    }

    const payload: unknown = await response.json()
    controller.signal.throwIfAborted()

    if (!isHealthResponse(payload)) {
      throw new HealthCheckError(
        'invalid-response',
        'The response does not match the P1 health contract. Check the backend version, then retry.',
      )
    }

    return payload
  } catch (error: unknown) {
    if (signal.aborted) {
      throw new DOMException('The health check was cancelled.', 'AbortError')
    }
    if (timedOut) {
      throw new HealthCheckError(
        'timeout',
        `The local API did not respond within ${timeoutMs / 1_000} seconds. Check that the backend is running, then retry.`,
      )
    }
    if (error instanceof HealthCheckError) {
      throw error
    }
    if (error instanceof SyntaxError) {
      throw new HealthCheckError(
        'invalid-response',
        'The local API did not return valid JSON. Check the backend and API proxy, then retry.',
      )
    }
    throw new HealthCheckError(
      'network',
      'The local API could not be reached. Check that the backend is running, then retry.',
    )
  } finally {
    clearTimeout(timeout)
    signal.removeEventListener('abort', cancel)
  }
}
