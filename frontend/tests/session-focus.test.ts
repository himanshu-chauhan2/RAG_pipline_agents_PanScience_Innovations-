import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { Session } from '../src/api/auth.ts'
import { sessionIdentityKey, verifySession, workspaceViewKey } from '../src/auth/verification.ts'

const current: Session = {
  user: { id: 'user-1', full_name: 'Alex Morgan', email: 'alex@example.com' },
  organization: { id: 'org-1', name: 'Original Organisation' },
  expires_at: new Date(Date.now() + 8 * 60 * 60 * 1_000).toISOString(),
}
const serverError = (code: string) => ({
  error: { code, message: 'Session verification failed.', request_id: 'focus-request-1' },
})

test('unexpired focus checks still call me and preserve the same-identity view key', async (t) => {
  const next: Session = {
    ...current,
    user: { ...current.user, full_name: 'Alex Updated' },
    expires_at: new Date(Date.parse(current.expires_at) + 1_000).toISOString(),
  }
  let blocks = 0
  const fetchMock = t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, '/api/auth/me')
    assert.equal(init?.credentials, 'same-origin')
    assert.equal(new Headers(init?.headers).has('X-Organization-ID'), false)
    return Response.json(next)
  })
  const result = await verifySession({
    current,
    signal: new AbortController().signal,
    background: true,
    onBlocking: () => { blocks += 1 },
  })
  assert.equal(fetchMock.mock.callCount(), 1)
  assert.equal(blocks, 0)
  assert.equal(result.status, 'authenticated')
  if (result.status === 'authenticated') {
    assert.equal(result.identityChanged, false)
    assert.deepEqual(result.session, next)
    assert.equal(sessionIdentityKey(result.session), sessionIdentityKey(current))
  }
})

for (const changed of ['organization', 'user'] as const) {
  test(`focus detects a shared-cookie ${changed} change before local expiry`, async (t) => {
    const next: Session = changed === 'organization'
      ? { ...current, organization: { id: 'org-2', name: 'Different Organisation' } }
      : { ...current, user: { id: 'user-2', full_name: 'Another User', email: 'another@example.com' } }
    t.mock.method(globalThis, 'fetch', async () => Response.json(next))
    const result = await verifySession({
      current,
      signal: new AbortController().signal,
      background: true,
      onBlocking: () => assert.fail('An unexpired focus check should begin quietly'),
    })
    assert.equal(result.status, 'authenticated')
    if (result.status === 'authenticated') {
      assert.equal(result.identityChanged, true)
      assert.notEqual(sessionIdentityKey(result.session), sessionIdentityKey(current))
    }
  })
}

test('expired focus checks block the view before asking the server', async (t) => {
  const events: string[] = []
  t.mock.method(globalThis, 'fetch', async () => {
    events.push('fetch')
    return Response.json(current)
  })
  await verifySession({
    current: { ...current, expires_at: new Date(Date.now() - 1_000).toISOString() },
    signal: new AbortController().signal,
    background: true,
    onBlocking: () => { events.push('block') },
  })
  assert.deepEqual(events, ['block', 'fetch'])
})

test('forced workspace revalidation blocks even an unexpired same identity', async (t) => {
  const events: string[] = []
  t.mock.method(globalThis, 'fetch', async () => {
    events.push('fetch')
    return Response.json(current)
  })
  await verifySession({
    current,
    signal: new AbortController().signal,
    background: false,
    onBlocking: () => { events.push('block') },
  })
  assert.deepEqual(events, ['block', 'fetch'])
})

test('focus 401 returns anonymous rather than preserving cached authentication', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json(serverError('unauthenticated'), { status: 401 }),
  )
  assert.deepEqual(await verifySession({
    current,
    signal: new AbortController().signal,
    background: true,
    onBlocking: () => undefined,
  }), { status: 'anonymous' })
})

for (const failure of ['network', 'server', 'malformed-json', 'invalid-session', 'malformed-401'] as const) {
  test(`focus ${failure} failure never returns the cached protected session`, async (t) => {
    t.mock.method(globalThis, 'fetch', async () => {
      if (failure === 'network') throw new TypeError('Offline')
      if (failure === 'server') return Response.json(serverError('unavailable'), { status: 503 })
      if (failure === 'malformed-json') return new Response('<html>Fallback</html>')
      if (failure === 'malformed-401') return Response.json({}, { status: 401 })
      return Response.json({ user: current.user })
    })
    const result = await verifySession({
      current,
      signal: new AbortController().signal,
      background: true,
      onBlocking: () => undefined,
    })
    assert.equal(result.status, 'error')
    assert.equal('session' in result, false)
  })
}

test('a cancelled late focus response cannot restore or switch the session', async (t) => {
  let finish: ((response: Response) => void) | undefined
  t.mock.method(globalThis, 'fetch', () => new Promise<Response>((resolve) => { finish = resolve }))
  const controller = new AbortController()
  const verification = verifySession({
    current,
    signal: controller.signal,
    background: true,
    onBlocking: () => undefined,
  })
  controller.abort()
  assert.ok(finish)
  finish(Response.json({ ...current, organization: { id: 'stale-org', name: 'Stale' } }))
  assert.deepEqual(await verification, { status: 'cancelled' })
})

test('an already-cancelled focus check neither fetches nor changes the view', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch')
  const controller = new AbortController()
  controller.abort()
  assert.deepEqual(await verifySession({
    current,
    signal: controller.signal,
    background: true,
    onBlocking: () => assert.fail('Cancelled verification must not change the view'),
  }), { status: 'cancelled' })
  assert.equal(fetchMock.mock.callCount(), 0)
})

test('workspace identity keys do not conflate different user and organisation pairs', () => {
  const first = { ...current, user: { ...current.user, id: 'a:b' }, organization: { id: 'c', name: 'One' } }
  const second = { ...current, user: { ...current.user, id: 'a' }, organization: { id: 'b:c', name: 'Two' } }
  assert.notEqual(sessionIdentityKey(first), sessionIdentityKey(second))
})

test('a context mismatch forces a fresh view even when verification returns the same identity', () => {
  const updated = { ...current, expires_at: new Date(Date.parse(current.expires_at) + 1_000).toISOString() }
  assert.equal(workspaceViewKey(current, 0), workspaceViewKey(updated, 0))
  assert.notEqual(workspaceViewKey(current, 0), workspaceViewKey(updated, 1))
})
