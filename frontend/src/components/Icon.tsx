import type { ReactNode } from 'react'

const paths = {
  external: <path d="M5 15 15 5M5 5h10v10" />,
  arrow: <path d="M4 10h12m-5-5 5 5-5 5" />,
  upload: <path d="M10 13V3M6 7l4-4 4 4M4 12v5h12v-5" />,
  documents: (
    <>
      <path d="M7 3h6l3 3v11H7V3Zm6 0v4h3M4 6v11" />
      <path d="M10 10h3m-3 3h3" />
    </>
  ),
  assistant: (
    <>
      <path d="M16 11v4a1 1 0 0 1-1 1H7l-4 2V6a1 1 0 0 1 1-1h5" />
      <path d="m14 2 1.1 3.9L19 7l-3.9 1.1L14 12l-1.1-3.9L9 7l3.9-1.1L14 2Z" />
    </>
  ),
  usage: <path d="M4 3v14h13M8 13V9m4 4V5m4 8v-3" />,
  lock: (
    <>
      <rect x="5" y="8" width="10" height="9" rx="2" />
      <path d="M7 8V6a3 3 0 0 1 6 0v2m-3 4v2" />
    </>
  ),
  logout: <path d="M8 3H4v14h4m3-11 4 4-4 4m-4-4h9" />,
  check: <path d="m4 10 4 4 8-8" />,
  refresh: <path d="M16 8a6.2 6.2 0 0 0-10.5-2L3 8m0-4v4h4M4 12a6.2 6.2 0 0 0 10.5 2l2.5-2m0 4v-4h-4" />,
} satisfies Record<string, ReactNode>

export type IconName = keyof typeof paths

export default function Icon({ name, className = 'size-5' }: { name: IconName; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
    >
      {paths[name]}
    </svg>
  )
}
