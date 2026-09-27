import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isHealthResponse, requestHealth } from '../src/api/health.ts'
import type { HealthResponse } from '../src/api/health.ts'

const validHealth: HealthResponse = {
  status: 'ok',
  service: 'knowledge-decision-assistant',
  version: '0.1.0',
  phase: 'P5',
  gateway_configured: false,
}

function rejectOnAbort(signal: AbortSignal | null | undefined): Promise<never> {
  assert.ok(signal)
  return new Promise((_resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason)
      return
    }
    signal.addEventListener('abort', () => reject(signal.reason), { once: true })
  })
}

test('accepts both boolean gateway configuration states', () => {
  assert.equal(isHealthResponse(validHealth), true)
  assert.equal(isHealthResponse({ ...validHealth, gateway_configured: true }), true)
})

test('rejects malformed payloads and incorrect contract fields', () => {
  const invalidPayloads: unknown[] = [
    null,
    undefined,
    false,
    1,
    'ok',
    [],
    {},
    { ...validHealth, status: 'error' },
    { ...validHealth, service: 'another-service' },
    { ...validHealth, version: '0.2.0' },
    { ...validHealth, phase: 'P0' },
    { ...validHealth, phase: 'P1' },
    { ...validHealth, phase: 'P2' },
    { ...validHealth, phase: 'P3' },
    { ...validHealth, gateway_configured: 'false' },
    { ...validHealth, gateway_configured: 0 },
    { ...validHealth, gateway_configured: null },
  ]

  for (const payload of invalidPayloads) {
    assert.equal(isHealthResponse(payload), false)
  }

  for (const field of Object.keys(validHealth)) {
    const missingField = Object.fromEntries(
      Object.entries(validHealth).filter(([key]) => key !== field),
    )
    assert.equal(isHealthResponse(missingField), false, `Missing field: ${field}`)
  }
})

test('accepts additional fields without using them', () => {
  assert.equal(isHealthResponse({ ...validHealth, additional_metadata: 'ignored' }), true)
})

test('requests the real same-origin health route without caching', async (t) => {
  const fetchMock = t.mock.method(
    globalThis,
    'fetch',
    async (input: unknown, init?: RequestInit) => {
      assert.equal(input, '/api/health')
      assert.equal(init?.method, 'GET')
      assert.deepEqual(init?.headers, { Accept: 'application/json' })
      assert.equal(init?.cache, 'no-store')
      assert.ok(init?.signal instanceof AbortSignal)
      return Response.json(validHealth)
    },
  )

  assert.deepEqual(await requestHealth(new AbortController().signal), validHealth)
  assert.equal(fetchMock.mock.callCount(), 1)
})

test('preserves a true configuration flag without inferring connectivity', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ ...validHealth, gateway_configured: true }),
  )
  const health = await requestHealth(new AbortController().signal)
  assert.equal(health.gateway_configured, true)
  assert.equal('gateway_connected' in health, false)
})

test('reports non-success HTTP responses explicitly', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('Unavailable', { status: 503 }))
  await assert.rejects(requestHealth(new AbortController().signal), {
    name: 'HealthCheckError',
    kind: 'http',
    message: 'The local API returned HTTP 503. Check the backend logs, then retry.',
  })
})

test('reports non-JSON responses as malformed', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<!doctype html><h1>Fallback</h1>'))
  await assert.rejects(requestHealth(new AbortController().signal), {
    name: 'HealthCheckError',
    kind: 'invalid-response',
  })
})

test('validates successful JSON responses before accepting them', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ ...validHealth, gateway_configured: 'true' }),
  )
  await assert.rejects(requestHealth(new AbortController().signal), {
    name: 'HealthCheckError',
    kind: 'invalid-response',
  })
})

test('reports fetch failures as network errors', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => {
    throw new TypeError('Failed to fetch')
  })
  await assert.rejects(requestHealth(new AbortController().signal), {
    name: 'HealthCheckError',
    kind: 'network',
  })
})

test('reports network failures while reading the response body', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => {
    const response = new Response()
    t.mock.method(response, 'json', async () => {
      throw new TypeError('Response stream interrupted')
    })
    return response
  })
  await assert.rejects(requestHealth(new AbortController().signal), {
    name: 'HealthCheckError',
    kind: 'network',
  })
})

test('times out and aborts a stalled request', async (t) => {
  t.mock.method(globalThis, 'fetch', (_input: unknown, init?: RequestInit) =>
    rejectOnAbort(init?.signal),
  )
  await assert.rejects(requestHealth(new AbortController().signal, 5), {
    name: 'HealthCheckError',
    kind: 'timeout',
  })
})

test('keeps the timeout active while reading the response body', async (t) => {
  t.mock.method(globalThis, 'fetch', async (_input: unknown, init?: RequestInit) => {
    const response = new Response()
    t.mock.method(response, 'json', () => rejectOnAbort(init?.signal))
    return response
  })
  await assert.rejects(requestHealth(new AbortController().signal, 5), {
    name: 'HealthCheckError',
    kind: 'timeout',
  })
})

test('does not start a request when its caller has already cancelled', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch')
  const controller = new AbortController()
  controller.abort()

  await assert.rejects(requestHealth(controller.signal), { name: 'AbortError' })
  assert.equal(fetchMock.mock.callCount(), 0)
})

test('cancels an in-flight request without reporting a health failure', async (t) => {
  t.mock.method(globalThis, 'fetch', (_input: unknown, init?: RequestInit) =>
    rejectOnAbort(init?.signal),
  )
  const controller = new AbortController()
  const request = requestHealth(controller.signal)
  controller.abort()

  await assert.rejects(request, { name: 'AbortError' })
})

test('a fresh request can succeed after an earlier failure', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => {
    throw new TypeError('Failed to fetch')
  })
  await assert.rejects(requestHealth(new AbortController().signal), {
    kind: 'network',
  })

  fetchMock.mock.mockImplementation(async () => Response.json(validHealth))
  assert.deepEqual(await requestHealth(new AbortController().signal), validHealth)
})
