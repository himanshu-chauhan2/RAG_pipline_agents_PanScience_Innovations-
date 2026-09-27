import type { DocumentList, KnowledgeDocument } from '../api/documents.ts'

export const POLL_INTERVAL_MS = 3_000
export const MAX_POLL_CHECKS = 40
export const MAX_POLL_DURATION_MS = 120_000

export interface PollRound {
  startedAt: number
  checks: number
}

export type PollDecision =
  | { kind: 'idle' }
  | { kind: 'paused' }
  | { kind: 'schedule'; delayMs: number }

export function hasPendingDocuments(documents: readonly KnowledgeDocument[]): boolean {
  return documents.some(
    (document) => document.status === 'processing' || document.replacement?.status === 'processing',
  )
}

export function canReplaceDocument(document: KnowledgeDocument): boolean {
  return document.status !== 'processing' && document.replacement?.status !== 'processing'
}

export function canUploadDocument(list: DocumentList): boolean {
  return list.used < list.max_documents
}

export function nextDocumentPoll(
  documents: readonly KnowledgeDocument[],
  round: PollRound,
  now: number,
): PollDecision {
  if (!hasPendingDocuments(documents)) return { kind: 'idle' }
  const remaining = MAX_POLL_DURATION_MS - Math.max(0, now - round.startedAt)
  if (round.checks >= MAX_POLL_CHECKS || remaining <= 0) return { kind: 'paused' }
  return { kind: 'schedule', delayMs: Math.min(POLL_INTERVAL_MS, remaining) }
}
