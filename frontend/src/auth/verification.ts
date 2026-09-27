import { getCurrentSession } from '../api/auth.ts'
import type { Session } from '../api/auth.ts'
import { isUnauthenticatedError, toApiError } from '../api/client.ts'
import type { ApiError } from '../api/client.ts'

export type SessionVerification =
  | { status: 'authenticated'; session: Session; identityChanged: boolean }
  | { status: 'anonymous' }
  | { status: 'error'; error: ApiError }
  | { status: 'cancelled' }

export function sessionIdentityKey(session: Session): string {
  return JSON.stringify([session.user.id, session.organization.id])
}

export function workspaceViewKey(session: Session, revision: number): string {
  return `${sessionIdentityKey(session)}:${revision}`
}

export async function verifySession({
  current,
  signal,
  background,
  onBlocking,
}: {
  current: Session | null
  signal: AbortSignal
  background: boolean
  onBlocking: () => void
}): Promise<SessionVerification> {
  if (signal.aborted) return { status: 'cancelled' }
  if (!background || !current || Date.parse(current.expires_at) <= Date.now()) onBlocking()

  try {
    const session = await getCurrentSession(signal)
    if (signal.aborted) return { status: 'cancelled' }
    return {
      status: 'authenticated',
      session,
      identityChanged: current !== null && sessionIdentityKey(current) !== sessionIdentityKey(session),
    }
  } catch (error: unknown) {
    if (signal.aborted) return { status: 'cancelled' }
    if (isUnauthenticatedError(error)) return { status: 'anonymous' }
    return { status: 'error', error: toApiError(error) }
  }
}
