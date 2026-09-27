import { ApiError, isNonemptyString, isRecord, requestJson } from './client.ts'

export interface AssistantLink {
  organization_id: string
  token: string
  ask_endpoint: '/api/ask'
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface Citation {
  id: string
  document_id: string
  document_name: string
  page: number
  quote: string
}

export interface DecisionCheck {
  id: string
  label: string
  result: boolean | null
  observed: string | null
  requirement: string
  reference_ids: string[]
}

export interface DecisionTrace {
  rule_set: string
  verdict: string
  checks: DecisionCheck[]
  missing_fields: string[]
  score: number
}

export interface AskResult {
  status: 'answered' | 'needs_info' | 'insufficient_evidence'
  answer: string
  follow_up_question: string | null
  references: Citation[]
  classification: { category: string; method: string }
  verdict: string | null
  decision_trace: DecisionTrace | null
  confidence: number
  trace: { step: string; status: string; detail: string }[]
}

function isCitation(value: unknown): value is Citation {
  return isRecord(value) &&
    isNonemptyString(value.id) &&
    isNonemptyString(value.document_id) &&
    isNonemptyString(value.document_name) &&
    typeof value.page === 'number' && Number.isSafeInteger(value.page) &&
    value.page > 0 &&
    typeof value.quote === 'string'
}

function isDecisionCheck(value: unknown): value is DecisionCheck {
  return isRecord(value) &&
    isNonemptyString(value.id) &&
    isNonemptyString(value.label) &&
    (typeof value.result === 'boolean' || value.result === null) &&
    (typeof value.observed === 'string' || value.observed === null) &&
    isNonemptyString(value.requirement) &&
    Array.isArray(value.reference_ids) &&
    value.reference_ids.every(isNonemptyString)
}

export function isAskResult(value: unknown): value is AskResult {
  return isRecord(value) &&
    (value.status === 'answered' || value.status === 'needs_info' || value.status === 'insufficient_evidence') &&
    isNonemptyString(value.answer) &&
    (value.follow_up_question === null || typeof value.follow_up_question === 'string') &&
    Array.isArray(value.references) && value.references.every(isCitation) &&
    isRecord(value.classification) &&
    isNonemptyString(value.classification.category) &&
    isNonemptyString(value.classification.method) &&
    (value.verdict === null || typeof value.verdict === 'string') &&
    (value.decision_trace === null || (
      isRecord(value.decision_trace) &&
      isNonemptyString(value.decision_trace.rule_set) &&
      isNonemptyString(value.decision_trace.verdict) &&
      Array.isArray(value.decision_trace.checks) &&
      value.decision_trace.checks.every(isDecisionCheck) &&
      Array.isArray(value.decision_trace.missing_fields) &&
      value.decision_trace.missing_fields.every(isNonemptyString) &&
      typeof value.decision_trace.score === 'number' &&
      Number.isFinite(value.decision_trace.score)
    )) &&
    typeof value.confidence === 'number' && Number.isFinite(value.confidence) &&
    Array.isArray(value.trace) && value.trace.every((step) =>
      isRecord(step) && isNonemptyString(step.step) &&
      isNonemptyString(step.status) && typeof step.detail === 'string')
}

export function isAssistantLink(value: unknown): value is AssistantLink {
  return isRecord(value) &&
    isNonemptyString(value.organization_id) &&
    isNonemptyString(value.token) &&
    value.ask_endpoint === '/api/ask'
}

export async function getAssistant(signal: AbortSignal, organizationId: string): Promise<AssistantLink> {
  const assistant = await requestJson('/api/assistant', isAssistantLink, {
    signal,
    expectedOrganizationId: organizationId,
  })
  if (assistant.organization_id !== organizationId) {
    throw new ApiError('http', 'The active organisation changed. Review the workspace before sharing.', {
      status: 409,
      code: 'workspace_changed',
    })
  }
  return assistant
}

export function askAssistant(
  token: string,
  question: string,
  history: ChatTurn[],
  signal: AbortSignal,
): Promise<AskResult> {
  return requestJson('/api/ask', isAskResult, {
    method: 'POST',
    body: { token, question, history },
    signal,
    timeoutMs: 90_000,
  })
}
