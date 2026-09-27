import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  DOCUMENT_LIMITS,
  DOCUMENT_VALIDATION_TIMEOUT_MS,
  deleteDocument,
  getDocument,
  isDocumentList,
  isKnowledgeDocument,
  listDocuments,
  replaceDocument,
  uploadDocument,
} from '../src/api/documents.ts'
import type { DocumentList, DocumentRequestContext, KnowledgeDocument } from '../src/api/documents.ts'
import { ApiError, isUnauthenticatedError, isWorkspaceChangedError } from '../src/api/client.ts'
import {
  MAX_POLL_CHECKS,
  MAX_POLL_DURATION_MS,
  POLL_INTERVAL_MS,
  canReplaceDocument,
  canUploadDocument,
  hasPendingDocuments,
  nextDocumentPoll,
} from '../src/documents/polling.ts'
import { validatePdfSelection } from '../src/validation/documents.ts'

const ready: KnowledgeDocument = {
  id: 'document-1',
  name: 'Existing policy.pdf',
  pages: 3,
  size_bytes: 42_000,
  status: 'ready',
  error: null,
  warnings: ['Page 2 has no extractable text and was not indexed.'],
  chunk_count: 8,
  created_at: '2026-09-27T08:00:00Z',
  updated_at: '2026-09-27T08:01:00Z',
  replacement: null,
}
const processing: KnowledgeDocument = { ...ready, status: 'processing', chunk_count: 0 }
const replacing: KnowledgeDocument = {
  ...ready,
  replacement: { name: 'New policy.pdf', status: 'processing', error: null },
}
const failedReplacement: KnowledgeDocument = {
  ...ready,
  replacement: {
    name: 'New policy.pdf',
    status: 'failed',
    error: { code: 'indexing_failed', message: 'The new file could not be indexed.' },
  },
}
const list = (documents: KnowledgeDocument[] = [ready]): DocumentList => ({
  ...DOCUMENT_LIMITS,
  documents,
  used: documents.length,
})
const context = (
  signal: AbortSignal = new AbortController().signal,
  organizationId = 'org-1',
): DocumentRequestContext => ({ organizationId, signal })
const pdf = () => new File(['%PDF-1.7\ntransport test fixture'], 'New policy.pdf', { type: 'application/pdf' })
const errorPayload = (code: string) => ({
  error: {
    code,
    message: 'The document request could not be completed.',
    request_id: 'document-request-1',
    fields: { file: 'Review the selected file.' },
  },
})

async function assertMultipart(init: RequestInit | undefined, file: File) {
  assert.equal(init?.credentials, 'same-origin')
  assert.equal(init?.cache, 'no-store')
  assert.deepEqual(init?.headers, { Accept: 'application/json', 'X-Organization-ID': 'org-1' })
  assert.ok(init?.body instanceof FormData)
  assert.deepEqual([...init.body.keys()], ['file'])
  const part = init.body.get('file')
  assert.ok(part instanceof File)
  assert.equal(part.name, file.name)
  assert.equal(await part.text(), await file.text())

  const request = new Request('http://127.0.0.1:8000/api/documents', {
    method: init.method,
    body: init.body,
    headers: init.headers,
  })
  assert.match(request.headers.get('Content-Type') ?? '', /^multipart\/form-data; boundary=.+/)
  assert.equal(request.headers.has('Origin'), false)
  assert.equal(request.headers.has('Authorization'), false)
  assert.equal(request.headers.get('X-Organization-ID'), 'org-1')
  assert.match(await request.text(), /name="file"; filename="New policy\.pdf"/)
}

test('document guards accept initial and replacement lifecycle states', () => {
  const failed: KnowledgeDocument = {
    ...processing,
    status: 'failed',
    error: { code: 'indexing_failed', message: 'Indexing failed.' },
  }
  for (const document of [ready, processing, failed, replacing, failedReplacement]) {
    assert.equal(isKnowledgeDocument(document), true)
  }
  assert.equal(isKnowledgeDocument({ ...ready, pages: 20, size_bytes: 10_000_000 }), true)
  assert.equal(isKnowledgeDocument({ ...ready, warnings: [] }), true)
})

test('document guards reject malformed fields, limits and timestamps', () => {
  const invalid: unknown[] = [
    null,
    [],
    {},
    { ...ready, id: '' },
    { ...ready, name: ' ' },
    { ...ready, pages: 0 },
    { ...ready, size_bytes: 0 },
    { ...ready, pages: -1 },
    { ...ready, pages: 1.5 },
    { ...ready, pages: 21 },
    { ...ready, size_bytes: 10_000_001 },
    { ...ready, size_bytes: NaN },
    { ...ready, chunk_count: -1 },
    { ...ready, chunk_count: '8' },
    { ...ready, status: 'queued' },
    { ...ready, error: { code: 'failed' } },
    { ...ready, warnings: null },
    { ...ready, warnings: 'Page 2 was skipped.' },
    { ...ready, warnings: [42] },
    { ...ready, created_at: '2026-09-27' },
    { ...ready, updated_at: '2026-02-30T00:00:00Z' },
    { ...ready, replacement: [] },
    { ...ready, replacement: { name: 'New.pdf', status: 'ready', error: null } },
    { ...ready, replacement: { name: 'New.pdf', status: 'failed', error: {} } },
  ]
  for (const value of invalid) assert.equal(isKnowledgeDocument(value), false)
  for (const field of Object.keys(ready)) {
    const missing = Object.fromEntries(Object.entries(ready).filter(([key]) => key !== field))
    assert.equal(isKnowledgeDocument(missing), false, `Missing ${field}`)
  }
})

test('list guards require consistent counts, unique ids and the exact published limits', () => {
  assert.equal(isDocumentList(list()), true)
  assert.equal(isDocumentList(list([])), true)
  for (const value of [
    null,
    [],
    { ...list(), documents: null },
    { ...list(), documents: [{}] },
    { ...list(), used: 0 },
    { ...list(), used: '1' },
    { ...list(), used: 1.5 },
    { ...list(), max_documents: 11 },
    { ...list(), max_pages: 21 },
    { ...list(), max_size_bytes: 10 * 1_024 * 1_024 },
    list([ready, ready]),
    list(Array.from({ length: 11 }, (_, index) => ({ ...ready, id: `document-${index}` }))),
  ]) {
    assert.equal(isDocumentList(value), false)
  }
})

test('list reads retain only the public metadata contract, not storage details', async (t) => {
  t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, '/api/documents')
    assert.equal(init?.method, 'GET')
    assert.equal(init?.credentials, 'same-origin')
    assert.deepEqual(init?.headers, { Accept: 'application/json', 'X-Organization-ID': 'org-1' })
    return Response.json({
      ...list(),
      private_metadata: 'ignored',
      documents: [{ ...ready, storage_path: 'not exposed', download_url: 'not exposed' }],
    })
  })
  assert.deepEqual(await listDocuments(context()), list())
})

test('detail reads encode identifiers and verify the returned document id', async (t) => {
  const id = 'document/with?reserved#characters'
  const fetchMock = t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, `/api/documents/${encodeURIComponent(id)}`)
    assert.deepEqual(init?.headers, { Accept: 'application/json', 'X-Organization-ID': 'org-1' })
    return Response.json({ ...ready, id })
  })
  assert.deepEqual(await getDocument(id, context()), { ...ready, id })
  fetchMock.mock.mockImplementation(async () => Response.json(ready))
  await assert.rejects(getDocument(id, context()), { kind: 'invalid-response' })
})

test('upload posts a single file and lets fetch generate the multipart boundary', async (t) => {
  const file = pdf()
  t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, '/api/documents')
    assert.equal(init?.method, 'POST')
    await assertMultipart(init, file)
    return Response.json(processing, { status: 202 })
  })
  assert.deepEqual(await uploadDocument(file, context()), processing)
})

test('replacement uses PUT multipart and retains the ready version during processing', async (t) => {
  const file = pdf()
  t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, '/api/documents/document-1')
    assert.equal(init?.method, 'PUT')
    await assertMultipart(init, file)
    return Response.json(replacing, { status: 202 })
  })
  const result = await replaceDocument(ready.id, file, context())
  assert.deepEqual(result, replacing)
  assert.equal(result.status, 'ready')
  assert.equal(result.name, ready.name)
  assert.equal(result.pages, ready.pages)
  assert.equal(result.chunk_count, ready.chunk_count)
  assert.deepEqual(result.warnings, ready.warnings)
  assert.equal(result.replacement?.status, 'processing')
})

test('failed replacement metadata preserves the original ready index', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json(failedReplacement))
  const result = await getDocument(ready.id, context())
  assert.equal(result.status, 'ready')
  assert.equal(result.name, ready.name)
  assert.equal(result.chunk_count, ready.chunk_count)
  assert.deepEqual(result.warnings, ready.warnings)
  assert.equal(result.replacement?.status, 'failed')
  assert.equal(result.replacement?.error?.code, 'indexing_failed')
})

test('a completed replacement updates active warnings and clears replacement state', async (t) => {
  const completed = { ...ready, name: 'New policy.pdf', pages: 5, chunk_count: 12, warnings: [] }
  t.mock.method(globalThis, 'fetch', async () => Response.json(completed))
  assert.deepEqual(await getDocument(ready.id, context()), completed)
})

test('list reads expose mixed-PDF warnings as part of the active document metadata', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json(list([ready, { ...replacing, id: 'document-2' }])))
  const result = await listDocuments(context())
  assert.deepEqual(result.documents.map((document) => document.warnings), [ready.warnings, ready.warnings])
})

test('replacement rejects a response for a different document', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ ...replacing, id: 'other-document' }, { status: 202 }),
  )
  await assert.rejects(replaceDocument(ready.id, pdf(), context()), { kind: 'invalid-response' })
})

test('mutating responses require the exact success statuses', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json(processing))
  await assert.rejects(uploadDocument(pdf(), context()), { kind: 'invalid-response' })
  await assert.rejects(replaceDocument(ready.id, pdf(), context()), { kind: 'invalid-response' })
  await assert.rejects(deleteDocument(ready.id, context()), { kind: 'invalid-response' })
})

test('delete accepts 204 without attempting JSON parsing', async (t) => {
  const response = new Response(null, { status: 204 })
  const jsonMock = t.mock.method(response, 'json', async () => {
    throw new Error('No JSON is present')
  })
  t.mock.method(globalThis, 'fetch', async (path: unknown, init?: RequestInit) => {
    assert.equal(path, '/api/documents/document-1')
    assert.equal(init?.method, 'DELETE')
    assert.equal(init?.credentials, 'same-origin')
    assert.equal(init?.body, undefined)
    assert.deepEqual(init?.headers, { Accept: 'application/json', 'X-Organization-ID': 'org-1' })
    return response
  })
  assert.equal(await deleteDocument(ready.id, context()), undefined)
  assert.equal(jsonMock.mock.callCount(), 0)
})

for (const [status, code] of [
  [400, 'invalid_pdf'],
  [400, 'encrypted_pdf'],
  [400, 'page_limit'],
  [400, 'no_readable_text'],
  [400, 'invalid_filename'],
  [413, 'file_too_large'],
  [409, 'document_limit'],
  [409, 'document_busy'],
  [503, 'processing_busy'],
  [503, 'storage_unavailable'],
  [404, 'document_not_found'],
] as const) {
  test(`document requests preserve ${status} ${code} errors and request references`, async (t) => {
    t.mock.method(globalThis, 'fetch', async () => Response.json(errorPayload(code), { status }))
    await assert.rejects(uploadDocument(pdf(), context()), {
      kind: 'http',
      status,
      code,
      requestId: 'document-request-1',
      fields: { file: 'Review the selected file.' },
    })
  })
}

test('document 401 responses reach the existing unauthenticated handler', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json(errorPayload('unauthenticated'), { status: 401 }),
  )
  await assert.rejects(listDocuments(context()), (error: unknown) => isUnauthenticatedError(error))
  await assert.rejects(deleteDocument(ready.id, context()), (error: unknown) => isUnauthenticatedError(error))
})

test('failed and malformed list requests never become a synthetic empty list', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => {
    throw new TypeError('Offline')
  })
  await assert.rejects(listDocuments(context()), { kind: 'network' })
  fetchMock.mock.mockImplementation(async () => Response.json({ documents: [] }))
  await assert.rejects(listDocuments(context()), { kind: 'invalid-response' })
  fetchMock.mock.mockImplementation(async () => new Response('<html>Fallback</html>'))
  await assert.rejects(listDocuments(context()), { kind: 'invalid-response' })
})

test('a document request can be cancelled when its owning view unmounts', async (t) => {
  const controller = new AbortController()
  t.mock.method(globalThis, 'fetch', (_path: unknown, init?: RequestInit) =>
    new Promise<Response>((_resolve, reject) => {
      const requestSignal = init?.signal
      assert.ok(requestSignal)
      requestSignal.addEventListener('abort', () => reject(requestSignal.reason), { once: true })
    }),
  )
  const request = uploadDocument(pdf(), context(controller.signal))
  controller.abort()
  await assert.rejects(request, { name: 'AbortError' })
})

for (const operation of ['upload', 'replace'] as const) {
  test(`${operation} allows PDF validation for 60 seconds, then aborts`, async (t) => {
    assert.equal(DOCUMENT_VALIDATION_TIMEOUT_MS, 60_000)
    t.mock.timers.enable({ apis: ['setTimeout'] })
    const signals: AbortSignal[] = []
    t.mock.method(globalThis, 'fetch', (_path: unknown, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        const requestSignal = init?.signal
        assert.ok(requestSignal)
        signals.push(requestSignal)
        requestSignal.addEventListener('abort', () => reject(requestSignal.reason), { once: true })
      }),
    )
    const request = operation === 'upload'
      ? uploadDocument(pdf(), context())
      : replaceDocument(ready.id, pdf(), context())
    const timedOut = assert.rejects(request, { name: 'ApiError', kind: 'timeout' })
    const requestSignal = signals[0]
    assert.ok(requestSignal)
    t.mock.timers.tick(59_999)
    assert.equal(requestSignal.aborted, false)
    t.mock.timers.tick(1)
    assert.equal(requestSignal.aborted, true)
    await timedOut
  })
}

test('a cancelled older list read cannot succeed after a deletion', async (t) => {
  let finishOldRead: ((response: Response) => void) | undefined
  t.mock.method(globalThis, 'fetch', (path: unknown, init?: RequestInit) => {
    if (path === '/api/documents' && init?.method === 'GET') {
      return new Promise<Response>((resolve) => { finishOldRead = resolve })
    }
    assert.equal(init?.method, 'DELETE')
    return Promise.resolve(new Response(null, { status: 204 }))
  })
  const oldController = new AbortController()
  const oldRead = listDocuments(context(oldController.signal))
  const cancelled = assert.rejects(oldRead, { name: 'AbortError' })
  oldController.abort()
  await deleteDocument(ready.id, context())
  assert.ok(finishOldRead)
  finishOldRead(Response.json(list()))
  await cancelled
})

test('every document operation refuses an empty expected organisation before fetching', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch')
  const missing = context(new AbortController().signal, '')
  for (const operation of [
    () => listDocuments(missing),
    () => getDocument(ready.id, missing),
    () => uploadDocument(pdf(), missing),
    () => replaceDocument(ready.id, pdf(), missing),
    () => deleteDocument(ready.id, missing),
  ]) {
    await assert.rejects(operation(), { kind: 'invalid-response' })
  }
  assert.equal(fetchMock.mock.callCount(), 0)
})

test('workspace_changed remains explicit and never causes a mutation replay', async (t) => {
  const displayedOrg = 'org-displayed-before-cookie-change'
  const fetchMock = t.mock.method(globalThis, 'fetch', async (_path: unknown, init?: RequestInit) => {
    assert.equal(new Headers(init?.headers).get('X-Organization-ID'), displayedOrg)
    return Response.json(errorPayload('workspace_changed'), { status: 409 })
  })
  await assert.rejects(
    uploadDocument(pdf(), context(new AbortController().signal, displayedOrg)),
    (error: unknown) => isWorkspaceChangedError(error),
  )
  assert.equal(fetchMock.mock.callCount(), 1)
})

test('workspace context errors are distinct from quota and processing conflicts', () => {
  assert.equal(isWorkspaceChangedError(new ApiError('http', 'Changed.', {
    status: 409, code: 'workspace_changed',
  })), true)
  for (const error of [
    new ApiError('http', 'Quota.', { status: 409, code: 'document_limit' }),
    new ApiError('http', 'Busy.', { status: 409, code: 'document_busy' }),
    new ApiError('invalid-response', 'Malformed.', { status: 409, code: 'workspace_changed' }),
    new ApiError('http', 'Wrong status.', { status: 400, code: 'workspace_changed' }),
  ]) {
    assert.equal(isWorkspaceChangedError(error), false)
  }
})

test('file validation uses the exact decimal byte limit, not 10 MiB', () => {
  assert.equal(validatePdfSelection({ size: 10_000_000 }), undefined)
  assert.ok(validatePdfSelection({ size: 10_000_001 }))
  assert.ok(validatePdfSelection({ size: 10 * 1_024 * 1_024 }))
  assert.equal(validatePdfSelection({ size: 1 }), undefined)
  for (const file of [null, { size: 0 }, { size: -1 }, { size: NaN }, { size: Infinity }]) {
    assert.ok(validatePdfSelection(file))
  }
})

test('PDF accept/MIME is only a hint; the server owns content validation', () => {
  const unusualMime = new File(['not checked by the browser'], 'sample.bin', { type: 'application/octet-stream' })
  assert.equal(validatePdfSelection(unusualMime), undefined)
})

test('ready and failed documents can be replaced at a full quota', () => {
  const full = list(Array.from({ length: 10 }, (_, index) => ({ ...ready, id: `document-${index}` })))
  assert.equal(isDocumentList(full), true)
  assert.equal(canUploadDocument(full), false)
  assert.equal(canReplaceDocument(ready), true)
  assert.equal(canReplaceDocument({ ...ready, status: 'failed', chunk_count: 0 }), true)
  assert.equal(canReplaceDocument(failedReplacement), true)
  assert.equal(canReplaceDocument(processing), false)
  assert.equal(canReplaceDocument(replacing), false)
  assert.equal(canUploadDocument(list([])), true)
})

test('failed initial documents occupy slots and remain replaceable', () => {
  const failed = Array.from({ length: 10 }, (_, index): KnowledgeDocument => ({
    ...ready,
    id: `failed-${index}`,
    status: 'failed',
    chunk_count: 0,
    error: { code: 'indexing_failed', message: 'Indexing failed.' },
  }))
  assert.equal(isDocumentList(list(failed)), true)
  assert.equal(canUploadDocument(list(failed)), false)
  assert.equal(failed.every(canReplaceDocument), true)
})

test('polling runs only for initial processing or a pending replacement', () => {
  assert.equal(hasPendingDocuments([]), false)
  assert.equal(hasPendingDocuments([ready, failedReplacement]), false)
  assert.equal(hasPendingDocuments([{ ...ready, status: 'failed' }]), false)
  assert.equal(hasPendingDocuments([processing]), true)
  assert.equal(hasPendingDocuments([replacing]), true)
  assert.deepEqual(nextDocumentPoll([ready], { startedAt: 0, checks: 0 }, 0), { kind: 'idle' })
  assert.deepEqual(nextDocumentPoll([replacing], { startedAt: 0, checks: 0 }, 0), {
    kind: 'schedule',
    delayMs: POLL_INTERVAL_MS,
  })
})

test('polling stops at both its attempt and elapsed-time bounds', () => {
  assert.deepEqual(nextDocumentPoll([processing], { startedAt: 0, checks: MAX_POLL_CHECKS }, 0), { kind: 'paused' })
  assert.deepEqual(nextDocumentPoll([processing], { startedAt: 0, checks: 0 }, MAX_POLL_DURATION_MS), { kind: 'paused' })
  assert.deepEqual(nextDocumentPoll([processing], { startedAt: 0, checks: 0 }, MAX_POLL_DURATION_MS - 500), {
    kind: 'schedule',
    delayMs: 500,
  })
})

test('manual refresh can start a new bounded round, but terminal documents do not poll', () => {
  const now = MAX_POLL_DURATION_MS + 1
  assert.deepEqual(nextDocumentPoll([replacing], { startedAt: now, checks: 0 }, now), {
    kind: 'schedule',
    delayMs: POLL_INTERVAL_MS,
  })
  assert.deepEqual(nextDocumentPoll([failedReplacement], { startedAt: 0, checks: MAX_POLL_CHECKS }, now), { kind: 'idle' })
})
