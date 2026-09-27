import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  getCurrentSession,
  getOrganization,
  isOrganization,
  isSession,
  login,
  logout,
  register,
} from '../src/api/auth.ts'
import type { Session } from '../src/api/auth.ts'
import { isApiErrorResponse, isUnauthenticatedError } from '../src/api/client.ts'

const session: Session = {
  user: { id: 'user-1', full_name: 'Alex Morgan', email: 'alex@example.com' },
  organization: { id: 'org-1', name: 'Example Organisation' },
  expires_at: new Date(Date.now() + 8 * 60 * 60 * 1_000).toISOString(),
}
const errorResponse = (code: string, fields?: Record<string, string>) => ({
  error: { code, message: 'The request could not be completed.', request_id: 'request-1', fields },
})
const signal = () => new AbortController().signal

test('validates session identity and an ISO expiry with a timezone', () => {
  assert.equal(isSession(session), true)
  assert.equal(isSession({ ...session, expires_at: '2030-06-01T10:30:00.123456+00:00' }), true)
  assert.equal(isSession({ ...session, expires_at: '2028-02-29T10:30:00Z' }), true)
  const invalidPayloads: unknown[] = [
    null,
    [],
    {},
    { ...session, user: null },
    { ...session, user: { ...session.user, id: '' } },
    { ...session, user: { ...session.user, full_name: 123 } },
    { ...session, user: { ...session.user, email: false } },
    { ...session, organization: { id: 'org-1' } },
    { ...session, organization: { id: 'org-1', name: ' ' } },
    { ...session, expires_at: 123 },
    { ...session, expires_at: '2030-06-01' },
    { ...session, expires_at: '2030-06-01T10:30:00' },
    { ...session, expires_at: '2030-99-01T10:30:00Z' },
    { ...session, expires_at: '2030-02-29T10:30:00Z' },
    { ...session, expires_at: '2030-04-31T10:30:00Z' },
    { ...session, expires_at: 'not-a-date' },
  ]
  for (const value of invalidPayloads) assert.equal(isSession(value), false)
  for (const field of Object.keys(session)) {
    assert.equal(
      isSession(Object.fromEntries(Object.entries(session).filter(([key]) => key !== field))),
      false,
    )
  }
})

test('validates organisation and structured error responses', () => {
  assert.equal(isOrganization(session.organization), true)
  for (const value of [null, [], { id: 1, name: 'Example' }, { id: 'org-1', name: '' }]) {
    assert.equal(isOrganization(value), false)
  }
  assert.equal(isApiErrorResponse(errorResponse('invalid_input')), true)
  assert.equal(isApiErrorResponse(errorResponse('invalid_input', { email: 'Invalid email.' })), true)
  for (const value of [
    null,
    {},
    { error: null },
    { error: { code: 'invalid_input', message: 'Invalid input.' } },
    { error: { ...errorResponse('invalid_input').error, request_id: '' } },
    { error: { ...errorResponse('invalid_input').error, fields: null } },
    { error: { ...errorResponse('invalid_input').error, fields: [] } },
    { error: { ...errorResponse('invalid_input').error, fields: { email: 42 } } },
  ]) {
    assert.equal(isApiErrorResponse(value), false)
  }
})

test('registers with cookies and only the four documented fields', async (t) => {
  const input = {
    organization_name: 'Example Organisation',
    full_name: 'Alex Morgan',
    email: 'alex@example.com',
    password: '  password preserved  ',
    confirmation: 'not part of the API',
  }
  t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, '/api/auth/register')
    assert.equal(init?.method, 'POST')
    assert.equal(init?.credentials, 'same-origin')
    assert.equal(init?.cache, 'no-store')
    assert.equal(init?.redirect, 'error')
    assert.deepEqual(init?.headers, {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    })
    assert.ok(typeof init?.body === 'string')
    const body: unknown = JSON.parse(init.body)
    assert.deepEqual(body, {
      organization_name: input.organization_name,
      full_name: input.full_name,
      email: input.email,
      password: input.password,
    })
    return Response.json(session, { status: 201 })
  })
  assert.deepEqual(await register(input, signal()), session)
})

test('login preserves the password and never fabricates Origin or Authorization', async (t) => {
  const input = { email: 'alex@example.com', password: '  unchanged password  ' }
  t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, '/api/auth/login')
    assert.equal(init?.method, 'POST')
    assert.equal(init?.credentials, 'same-origin')
    assert.ok(typeof init?.body === 'string')
    assert.deepEqual(JSON.parse(init.body), input)
    const headers = new Headers(init.headers)
    assert.equal(headers.has('Origin'), false)
    assert.equal(headers.has('Authorization'), false)
    return Response.json(session)
  })
  assert.deepEqual(await login(input, signal()), session)
})

test('bootstraps via the cookie and keeps only documented identity fields', async (t) => {
  t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, '/api/auth/me')
    assert.equal(init?.method, 'GET')
    assert.equal(init?.credentials, 'same-origin')
    assert.equal(init?.body, undefined)
    return Response.json({
      ...session,
      private_metadata: 'not retained',
      user: { ...session.user, private_metadata: 'not retained' },
      organization: { ...session.organization, private_metadata: 'not retained' },
    })
  })
  assert.deepEqual(await getCurrentSession(signal()), session)
})

test('rejects an already-expired successful session instead of authenticating', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ ...session, expires_at: new Date(Date.now() - 1_000).toISOString() }),
  )
  await assert.rejects(getCurrentSession(signal()), { kind: 'invalid-response' })
})

test('a valid unauthenticated error can transition the session to anonymous', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json(errorResponse('unauthenticated'), { status: 401 }),
  )
  await assert.rejects(getCurrentSession(signal()), (error: unknown) =>
    isUnauthenticatedError(error),
  )
})

test('a malformed 401 is not treated as a confirmed anonymous session', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ message: 'Unauthorized' }, { status: 401 }),
  )
  await assert.rejects(getCurrentSession(signal()), (error: unknown) => {
    assert.equal(isUnauthenticatedError(error), false)
    return true
  })
})

test('invalid successful session payloads remain retryable errors', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ user: session.user }))
  await assert.rejects(getCurrentSession(signal()), { kind: 'invalid-response' })
})

test('registration requires HTTP 201 rather than assuming any 2xx succeeded', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json(session))
  await assert.rejects(
    register(
      {
        organization_name: session.organization.name,
        full_name: session.user.full_name,
        email: session.user.email,
        password: 'example password',
      },
      signal(),
    ),
    { kind: 'invalid-response' },
  )
})

for (const [status, code] of [
  [400, 'invalid_input'],
  [401, 'invalid_credentials'],
  [409, 'duplicate_email'],
  [403, 'disallowed_origin'],
  [503, 'database_unavailable'],
] as const) {
  test(`preserves ${status} ${code} errors without clearing a session`, async (t) => {
    const fields = { email: 'Check this email address.' }
    t.mock.method(globalThis, 'fetch', async () => Response.json(errorResponse(code, fields), { status }))
    await assert.rejects(login({ email: session.user.email, password: 'password' }, signal()), {
      name: 'ApiError',
      kind: 'http',
      status,
      code,
      requestId: 'request-1',
      fields,
    })
  })
}

test('logout accepts 204 without attempting to read a JSON body', async (t) => {
  const response = new Response(null, { status: 204 })
  const jsonMock = t.mock.method(response, 'json', async () => {
    throw new Error('A 204 response has no JSON body')
  })
  t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, '/api/auth/logout')
    assert.equal(init?.method, 'POST')
    assert.equal(init?.credentials, 'same-origin')
    assert.equal(init?.body, undefined)
    assert.deepEqual(init?.headers, { Accept: 'application/json' })
    return response
  })
  assert.equal(await logout(signal()), undefined)
  assert.equal(jsonMock.mock.callCount(), 0)
})

test('logout accepts a session that is already unauthenticated', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json(errorResponse('unauthenticated'), { status: 401 }),
  )
  assert.equal(await logout(signal()), undefined)
})

test('logout does not hide network failures', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => {
    throw new TypeError('Failed to fetch')
  })
  await assert.rejects(logout(signal()), { kind: 'network' })
})

test('logout does not accept a malformed 401 or unexpected 200', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () =>
    Response.json({}, { status: 401 }),
  )
  await assert.rejects(logout(signal()), { kind: 'invalid-response' })
  fetchMock.mock.mockImplementation(async () => Response.json({ status: 'ok' }))
  await assert.rejects(logout(signal()), { kind: 'invalid-response' })
})

test('logout does not mistake wrong credentials or server failures for revocation', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () =>
    Response.json(errorResponse('invalid_credentials'), { status: 401 }),
  )
  await assert.rejects(logout(signal()), { kind: 'http', code: 'invalid_credentials' })
  fetchMock.mock.mockImplementation(async () =>
    Response.json(errorResponse('database_unavailable'), { status: 503 }),
  )
  await assert.rejects(logout(signal()), { kind: 'http', status: 503 })
})

test('organisation requests encode the identifier and discard extra fields', async (t) => {
  const organization = { id: 'org/with?reserved#characters', name: 'Example' }
  t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, `/api/organizations/${encodeURIComponent(organization.id)}`)
    assert.equal(init?.credentials, 'same-origin')
    return Response.json({ ...organization, private_metadata: 'not retained' })
  })
  assert.deepEqual(await getOrganization(organization.id, signal()), organization)
})

test('rejects an organisation response for a different tenant', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ id: 'other-org', name: 'Other' }))
  await assert.rejects(getOrganization('org-1', signal()), { kind: 'invalid-response' })
})

test('keeps own-organisation 404 errors distinct from anonymous sessions', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json(errorResponse('not_found'), { status: 404 }),
  )
  await assert.rejects(getOrganization('org-1', signal()), { kind: 'http', status: 404 })
})
