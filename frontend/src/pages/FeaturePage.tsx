import Icon from '../components/Icon'
import type { IconName } from '../components/Icon'

interface Feature {
  label: string
  title: string
  description: string
  phase: string
  icon: IconName
  emptyTitle: string
  emptyDescription: string
  nextStep: string
}

const features = {
  assistant: {
    label: 'Assistant',
    title: 'Better answers start with evidence.',
    description: 'Your indexed PDFs are the foundation. Grounded answers and decision validation come next.',
    phase: 'P3–P5',
    icon: 'assistant',
    emptyTitle: 'Assistant publishing is not implemented yet.',
    emptyDescription:
      'There is no public assistant link, embed code or chat experience in P2. Publishing will become available only after grounded answers and decision validation are implemented.',
    nextStep: 'Next: grounded answers, explicit decision models and a verified chat experience.',
  },
  usage: {
    label: 'Usage',
    title: 'Real activity. Meaningful reporting.',
    description: 'Usage reporting will reflect actual requests, not demonstration numbers.',
    phase: 'P5',
    icon: 'usage',
    emptyTitle: 'Usage reporting is not implemented yet.',
    emptyDescription:
      'Request counts, history and analytics are reserved for a later phase. This workspace does not display sample metrics or assume that missing measurements mean zero usage.',
    nextStep: 'Next: usage instrumentation for the implemented assistant.',
  },
} satisfies Record<string, Feature>

export type FeatureSection = keyof typeof features

export default function FeaturePage({ section }: { section: FeatureSection }) {
  const feature = features[section]
  return (
    <section aria-labelledby="feature-heading">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="eyebrow">{feature.label}</p>
        <span className="rounded-full border border-line bg-white px-3 py-1.5 text-xs font-medium text-muted">
          Planned for {feature.phase}
        </span>
      </div>
      <h1 id="feature-heading" className="max-w-2xl text-3xl leading-tight font-semibold tracking-[-0.035em] sm:text-4xl">
        {feature.title}
      </h1>
      <p className="mt-4 max-w-2xl text-base leading-7 text-muted">{feature.description}</p>

      <div className="mt-8 overflow-hidden rounded-2xl border border-line bg-white">
        <div className="px-6 py-10 text-center sm:px-10 sm:py-14">
          <div className="mx-auto mb-6 flex size-16 items-center justify-center rounded-2xl border border-accent/10 bg-sage text-accent">
            <Icon name={feature.icon} className="size-8" />
          </div>
          <h2 className="text-xl font-semibold tracking-tight">{feature.emptyTitle}</h2>
          <p className="mx-auto mt-4 max-w-xl text-sm leading-7 text-muted">{feature.emptyDescription}</p>
          <span className="mt-6 inline-flex items-center gap-2 rounded-full bg-canvas px-3 py-1.5 text-xs font-medium text-muted">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
            Not available in this demo
          </span>
        </div>
        <p className="border-t border-line bg-canvas/60 px-6 py-4 text-xs leading-6 text-muted sm:px-8">
          {feature.nextStep}
        </p>
      </div>

      <div className="mt-6 flex items-start gap-3 rounded-xl border border-accent/15 bg-sage/60 px-5 py-4 text-sm leading-6">
        <Icon name="check" className="mt-0.5 size-5 text-accent" />
        <p>
          <strong className="font-semibold">Available now:</strong>{' '}
          <span className="text-muted">
            organisation accounts, private PDF uploads, replacement, deletion and local index management.
          </span>
        </p>
      </div>
    </section>
  )
}
