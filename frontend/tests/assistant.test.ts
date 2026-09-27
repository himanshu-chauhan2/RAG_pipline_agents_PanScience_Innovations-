import assert from 'node:assert/strict'
import { test } from 'node:test'
import { askAssistant, getAssistant, isAskResult } from '../src/api/assistant.ts'
import { ApiError } from '../src/api/client.ts'

const answer = {
  status: 'answered',
  answer: 'The deadline is August 31.',
  follow_up_question: null,
  references: [{
    id: 'c1', document_id: 'd1', document_name: 'Rules.pdf', page: 3,
    quote: 'Applications close on August 31.',
  }],
  classification: { category: 'direct', method: 'rules' },
  verdict: null,
  decision_trace: null,
  confidence: 0.9,
  trace: [{ step: 'retrieve', status: 'ok', detail: 'Found source.' }],
}

test('Ask response validates page citations and structured checks', () => {
  assert.ok(isAskResult(answer))
  assert.equal(isAskResult({ ...answer, references: [{ ...answer.references[0], page: 0 }] }), false)
  assert.equal(isAskResult({ ...answer, decision_trace: { rule_set: 'x', verdict: 'eligible', checks: [{}], missing_fields: [], score: 1 } }), false)
})

test('public Ask sends only its token, question and bounded history to API', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    assert.equal(input, '/api/ask')
    assert.equal(init?.method, 'POST')
    assert.equal(init?.credentials, 'same-origin')
    assert.deepEqual(JSON.parse(String(init?.body)), {
      token: 'public-token', question: '3.6', history: [{ role: 'user', content: 'My GPA?' }],
    })
    return Response.json(answer)
  }
  try {
    const result = await askAssistant('public-token', '3.6', [{ role: 'user', content: 'My GPA?' }], new AbortController().signal)
    const citation = result.references[0]
    assert.ok(citation)
    assert.equal(citation.page, 3)
  } finally {
    globalThis.fetch = original
  }
})

test('owner link rejects malformed responses instead of showing a fabricated token', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => Response.json({ token: '' })
  try {
    await assert.rejects(getAssistant(new AbortController().signal, 'org-1'), (error: unknown) =>
      error instanceof ApiError && error.kind === 'invalid-response')
  } finally {
    globalThis.fetch = original
  }
})

test('owner link asserts the displayed organisation and rejects a switched cookie', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async (_path, init) => {
    assert.equal((init?.headers as Record<string, string>)['X-Organization-ID'], 'org-1')
    return Response.json({
      organization_id: 'org-2', organization_name: 'Other organisation',
      token: 'other-tenant-token', ask_endpoint: '/api/ask',
    })
  }
  try {
    await assert.rejects(getAssistant(new AbortController().signal, 'org-1'), (error: unknown) =>
      error instanceof ApiError && error.code === 'workspace_changed')
  } finally {
    globalThis.fetch = original
  }
})
