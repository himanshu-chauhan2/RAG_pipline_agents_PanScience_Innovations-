import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import Icon from './Icon'

export function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="page-width flex min-h-24 flex-wrap items-center justify-between gap-5 border-b border-line py-5">
      <Link
        to="/"
        aria-label="Knowledge & Decision Assistant home"
        className="flex items-center gap-3 rounded-md"
      >
        <svg aria-hidden="true" viewBox="0 0 40 40" fill="none" className="size-10 shrink-0">
          <rect width="40" height="40" rx="11" fill="currentColor" className="text-accent" />
          <path
            d="m9 15 11-6 11 6-11 6-11-6Zm0 6 11 6 11-6M9 27l11 6 11-6"
            stroke="#f6f7f3"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span>
          <span className="block text-base font-semibold tracking-tight">Knowledge</span>
          <span className="block text-xs text-muted">&amp; Decision Assistant</span>
        </span>
      </Link>
      <div className="flex flex-wrap items-center gap-4 sm:gap-6">
        <span className="hidden rounded-full border border-line px-3 py-1.5 text-xs font-medium text-muted md:inline-flex">
          Hackathon demo
        </span>
        <a
          href="http://127.0.0.1:8000/docs"
          target="_blank"
          rel="noreferrer"
          className="inline-flex min-h-11 items-center gap-2 rounded-md text-sm font-medium text-muted hover:text-accent"
        >
          API docs
          <Icon name="external" className="size-4" />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
        {children}
      </div>
    </header>
  )
}

export function Footer() {
  return (
    <footer className="page-width mt-auto flex flex-wrap items-start justify-between gap-3 border-t border-line py-6 text-xs leading-5 text-muted">
      <p>
        Independent PanScience hackathon submission.
        <br />
        Not an official PanScience service.
      </p>
      <p>Knowledge &amp; Decision Assistant <span aria-hidden="true">/</span> demo</p>
    </footer>
  )
}
