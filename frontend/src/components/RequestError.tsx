import type { ReactNode } from 'react'
import type { ApiError } from '../api/client'
import Icon from './Icon'

export default function RequestError({
  title,
  error,
  onRetry,
  retryLabel = 'Retry',
  children,
}: {
  title: string
  error: ApiError
  onRetry?: () => void
  retryLabel?: string
  children?: ReactNode
}) {
  return (
    <div role="alert" className="rounded-xl border border-warning-line bg-warning-soft p-5 text-sm leading-6 text-warning">
      <p className="font-semibold">{title}</p>
      <p className="mt-1">{error.message}</p>
      {children}
      {error.requestId && (
        <p className="mt-2 break-all font-mono text-xs">Request reference: {error.requestId}</p>
      )}
      {onRetry && (
        <button type="button" className="button-secondary mt-4" onClick={onRetry}>
          <Icon name="refresh" className="size-4" />
          {retryLabel}
        </button>
      )}
    </div>
  )
}
