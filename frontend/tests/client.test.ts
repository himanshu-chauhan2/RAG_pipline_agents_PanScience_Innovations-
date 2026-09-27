import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isRecord, requestJson } from '../src/api/client.ts'

function rejectOnAbort(signal: AbortSignal | null | undefined): Promise<never> {
  assert.ok(signal)
  return new Promise((_resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason)
    } else {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true })
    }
  })
}

test('client distinguishes malformed JSON from network errors', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => new Response('<html>Fallback</html>'))
  await assert.rejects(
    requestJson('/api/auth/me', isRecord, { signal: new AbortController().signal }),
    { kind: 'invalid-response' },
  )
  fetchMock.mock.mockImplementation(async () => {
    throw new TypeError('Offline')
  })
  await assert.rejects(
    requestJson('/api/auth/me', isRecord, { signal: new AbortController().signal }),
    { kind: 'network' },
  )
})

test('client timeout aborts a stalled request', async (t) => {
  t.mock.method(globalThis, 'fetch', (_path: unknown, init?: RequestInit) =>
    rejectOnAbort(init?.signal),
  )
  await assert.rejects(
    requestJson('/api/auth/me', isRecord, {
      signal: new AbortController().signal,
      timeoutMs: 5,
    }),
    { kind: 'timeout' },
  )
})

for (const status of [200, 401]) {
  test(`client timeout covers the body of a ${status} response`, async (t) => {
    t.mock.method(globalThis, 'fetch', async (_path: unknown, init?: RequestInit) => {
      const response = new Response(null, { status })
      t.mock.method(response, 'json', () => rejectOnAbort(init?.signal))
      return response
    })
    await assert.rejects(
      requestJson('/api/auth/me', isRecord, {
        signal: new AbortController().signal,
        timeoutMs: 5,
      }),
      { kind: 'timeout' },
    )
  })
}

test('client cancels an in-flight request without misreporting a network failure', async (t) => {
  t.mock.method(globalThis, 'fetch', (_path: unknown, init?: RequestInit) =>
    rejectOnAbort(init?.signal),
  )
  const controller = new AbortController()
  const request = requestJson('/api/auth/me', isRecord, { signal: controller.signal })
  controller.abort()
  await assert.rejects(request, { name: 'AbortError' })
})

test('client does not fetch with an already-aborted signal', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch')
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(
    requestJson('/api/auth/me', isRecord, { signal: controller.signal }),
    { name: 'AbortError' },
  )
  assert.equal(fetchMock.mock.callCount(), 0)
})

test('client can retry successfully after a transient failure', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => {
    throw new TypeError('Offline')
  })
  await assert.rejects(
    requestJson('/api/auth/me', isRecord, { signal: new AbortController().signal }),
    { kind: 'network' },
  )
  fetchMock.mock.mockImplementation(async () => Response.json({ valid: true }))
  assert.deepEqual(
    await requestJson('/api/auth/me', isRecord, { signal: new AbortController().signal }),
    { valid: true },
  )
})
