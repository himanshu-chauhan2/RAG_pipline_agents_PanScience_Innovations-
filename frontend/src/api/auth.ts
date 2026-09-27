import {
  ApiError,
  isNonemptyString,
  isRecord,
  isUnauthenticatedError,
  requestJson,
  requestNoContent,
} from './client.ts'

export interface User {
  id: string
  full_name: string
  email: string
}

export interface Organization {
  id: string
  name: string
}

export interface Session {
  user: User
  organization: Organization
  expires_at: string
}

export interface LoginInput {
  email: string
  password: string
}

export interface RegisterInput extends LoginInput {
  organization_name: string
  full_name: string
}

export function isOrganization(value: unknown): value is Organization {
  return isRecord(value) && isNonemptyString(value.id) && isNonemptyString(value.name)
}

function isIsoDateTime(value: unknown): value is string {
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

export function isSession(value: unknown): value is Session {
  if (!isRecord(value) || !isRecord(value.user)) {
    return false
  }
  return (
    isNonemptyString(value.user.id) &&
    isNonemptyString(value.user.full_name) &&
    isNonemptyString(value.user.email) &&
    isOrganization(value.organization) &&
    isIsoDateTime(value.expires_at)
  )
}

function readSession(session: Session): Session {
  if (Date.parse(session.expires_at) <= Date.now()) {
    throw new ApiError(
      'invalid-response',
      'The API returned an already-expired session. Check the server clock and retry.',
    )
  }
  return {
    user: {
      id: session.user.id,
      full_name: session.user.full_name,
      email: session.user.email,
    },
    organization: {
      id: session.organization.id,
      name: session.organization.name,
    },
    expires_at: session.expires_at,
  }
}

export async function getCurrentSession(signal: AbortSignal): Promise<Session> {
  return readSession(await requestJson('/api/auth/me', isSession, { signal }))
}

export async function register(input: RegisterInput, signal: AbortSignal): Promise<Session> {
  const session = await requestJson('/api/auth/register', isSession, {
    signal,
    method: 'POST',
    successStatus: 201,
    body: {
      organization_name: input.organization_name,
      full_name: input.full_name,
      email: input.email,
      password: input.password,
    },
  })
  return readSession(session)
}

export async function login(input: LoginInput, signal: AbortSignal): Promise<Session> {
  const session = await requestJson('/api/auth/login', isSession, {
    signal,
    method: 'POST',
    body: { email: input.email, password: input.password },
  })
  return readSession(session)
}

export async function logout(signal: AbortSignal): Promise<void> {
  try {
    await requestNoContent('/api/auth/logout', { signal, method: 'POST' })
  } catch (error: unknown) {
    if (!isUnauthenticatedError(error)) {
      throw error
    }
  }
}

export async function getOrganization(
  id: string,
  signal: AbortSignal,
): Promise<Organization> {
  const organization = await requestJson(
    `/api/organizations/${encodeURIComponent(id)}`,
    isOrganization,
    { signal },
  )
  if (organization.id !== id) {
    throw new ApiError(
      'invalid-response',
      'The API returned a different organisation. This workspace could not be verified.',
    )
  }
  return { id: organization.id, name: organization.name }
}
