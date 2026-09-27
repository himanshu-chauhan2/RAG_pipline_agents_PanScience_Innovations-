import SystemStatus from './components/SystemStatus'

const futurePhases = [
  {
    phase: 'P1',
    title: 'Organisation accounts',
    description: 'Account access and an organisation dashboard.',
  },
  {
    phase: 'P2',
    title: 'A PDF knowledge base',
    description: 'Document uploads and tenant-scoped indexing.',
  },
  {
    phase: 'P3–P5',
    title: 'Grounded assistance',
    description: 'Answers, decision models and the chat experience.',
  },
]

function ExternalLinkIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-4 shrink-0"
    >
      <path d="M5 15 15 5M5 5h10v10" />
    </svg>
  )
}

export default function App() {
  return (
    <div id="top" className="min-h-screen">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>

      <header className="page-width flex min-h-24 flex-wrap items-center justify-between gap-4 border-b border-line py-5">
        <a
          href="#top"
          aria-label="Knowledge & Decision Assistant home"
          className="flex items-center gap-3 rounded-md"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 40 40"
            fill="none"
            className="size-10 shrink-0"
          >
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
        </a>
        <nav aria-label="Workspace" className="flex items-center gap-6">
          <span className="hidden rounded-full border border-line px-3 py-1.5 text-xs font-medium text-muted sm:inline-flex">
            P0 · Foundation
          </span>
          <a
            href="http://127.0.0.1:8000/docs"
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 items-center gap-2 rounded-md text-sm font-medium text-muted transition-colors hover:text-accent"
          >
            API docs
            <ExternalLinkIcon />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </nav>
      </header>

      <main id="main-content" className="page-width pb-16 pt-12 sm:pb-20 sm:pt-16 lg:pt-20">
        <section
          aria-labelledby="workspace-heading"
          className="grid items-start gap-10 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-16"
        >
          <div className="lg:pt-4">
            <p className="eyebrow mb-6 inline-flex items-center gap-2.5">
              <span aria-hidden="true" className="size-2 rounded-full bg-accent" />
              Your setup workspace
            </p>
            <h1
              id="workspace-heading"
              className="max-w-xl text-[clamp(2.5rem,4.4vw,3.75rem)] leading-[1.1] font-semibold tracking-[-0.045em] text-ink"
            >
              The foundation for
              <br />
              <span className="text-accent">better answers.</span>
            </h1>
            <p className="mt-6 max-w-lg text-base leading-7 text-muted sm:text-lg sm:leading-8">
              A grounded assistant starts with a connected workspace. This setup
              phase brings the interface and local API together, one verified
              step at a time.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
              <a
                href="http://127.0.0.1:8000/docs"
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-12 items-center justify-center gap-3 rounded-lg bg-accent px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-dark"
              >
                Explore API docs
                <ExternalLinkIcon />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
              <a
                href="#phase-scope"
                className="inline-flex min-h-12 items-center gap-2 rounded-md text-sm font-semibold text-accent underline-offset-4 hover:underline"
              >
                What&apos;s in this phase
                <span aria-hidden="true">↓</span>
              </a>
            </div>
            <div className="mt-9 flex max-w-lg items-start gap-3 border-l-2 border-accent/25 pl-4">
              <p className="text-sm leading-6 text-muted">
                <strong className="font-semibold text-ink">Setup, not the finished product.</strong>{' '}
                Accounts, PDF uploads, chat and decision features are not
                implemented yet.
              </p>
            </div>
          </div>
          <SystemStatus />
        </section>

        <section
          id="phase-scope"
          aria-labelledby="scope-heading"
          className="mt-16 scroll-mt-8 border-t border-line pt-10 sm:mt-20 sm:pt-12"
        >
          <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="eyebrow mb-3">A deliberate first step</p>
              <h2 id="scope-heading" className="text-2xl font-semibold tracking-tight">
                Built one phase at a time.
              </h2>
            </div>
            <p className="max-w-sm text-sm leading-6 text-muted">
              Only the P0 foundation is included here.
              <br className="hidden sm:block" /> Later phases follow after review.
            </p>
          </div>

          <ol className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <li aria-current="step" className="rounded-xl border border-accent/25 bg-sage p-6">
              <div className="mb-5 flex items-center justify-between gap-3">
                <span className="font-mono text-xs font-semibold text-accent">P0</span>
                <span className="rounded-full bg-white/80 px-2.5 py-1 text-xs font-medium text-accent">
                  Current phase
                </span>
              </div>
              <h3 className="text-base font-semibold tracking-tight">Setup &amp; smoke test</h3>
              <p className="mt-2 text-sm leading-6 text-muted">
                The application shell and a real local API health check.
              </p>
            </li>
            {futurePhases.map((phase) => (
              <li key={phase.phase} className="rounded-xl border border-line bg-white/50 p-6">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <span className="font-mono text-xs font-medium text-muted">{phase.phase}</span>
                  <span className="text-xs text-muted">Not implemented</span>
                </div>
                <h3 className="text-base font-semibold tracking-tight">{phase.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted">{phase.description}</p>
              </li>
            ))}
          </ol>
        </section>
      </main>

      <footer className="page-width flex flex-wrap items-center justify-between gap-3 border-t border-line py-6 text-xs leading-5 text-muted">
        <p>Knowledge &amp; Decision Assistant</p>
        <p>Local development <span aria-hidden="true">/</span> P0 foundation</p>
      </footer>
    </div>
  )
}
