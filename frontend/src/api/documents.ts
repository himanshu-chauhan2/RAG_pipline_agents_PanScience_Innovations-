import {
  ApiError,
  isIsoDateTime,
  isNonemptyString,
  isRecord,
  requestJson,
  requestNoContent,
} from './client.ts'

export const DOCUMENT_LIMITS = {
  max_documents: 10,
  max_pages: 20,
  max_size_bytes: 10_000_000,
} as const

export const DOCUMENT_VALIDATION_TIMEOUT_MS = 60_000

export interface DocumentRequestContext {
  organizationId: string
  signal: AbortSignal
}

export interface DocumentError {
  code: string
  message: string
}

export interface DocumentReplacement {
  name: string
  status: 'processing' | 'failed'
  error: DocumentError | null
}

export interface KnowledgeDocument {
  id: string
  name: string
  pages: number
  size_bytes: number
  status: 'processing' | 'ready' | 'failed'
  error: DocumentError | null
  warnings: string[]
  chunk_count: number
  created_at: string
  updated_at: string
  replacement: DocumentReplacement | null
}

export interface DocumentList {
  documents: KnowledgeDocument[]
  used: number
  max_documents: 10
  max_pages: 20
  max_size_bytes: 10000000
}

function isCount(value: unknown, maximum = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= maximum
}

function isDocumentError(value: unknown): value is DocumentError {
  return isRecord(value) && isNonemptyString(value.code) && isNonemptyString(value.message)
}

function isReplacement(value: unknown): value is DocumentReplacement {
  return (
    isRecord(value) &&
    isNonemptyString(value.name) &&
    (value.status === 'processing' || value.status === 'failed') &&
    (value.error === null || isDocumentError(value.error))
  )
}

export function isKnowledgeDocument(value: unknown): value is KnowledgeDocument {
  return (
    isRecord(value) &&
    isNonemptyString(value.id) &&
    isNonemptyString(value.name) &&
    isCount(value.pages, DOCUMENT_LIMITS.max_pages) &&
    value.pages > 0 &&
    isCount(value.size_bytes, DOCUMENT_LIMITS.max_size_bytes) &&
    value.size_bytes > 0 &&
    (value.status === 'processing' || value.status === 'ready' || value.status === 'failed') &&
    (value.error === null || isDocumentError(value.error)) &&
    Array.isArray(value.warnings) &&
    value.warnings.every((warning) => typeof warning === 'string') &&
    isCount(value.chunk_count) &&
    isIsoDateTime(value.created_at) &&
    isIsoDateTime(value.updated_at) &&
    (value.replacement === null || isReplacement(value.replacement))
  )
}

export function isDocumentList(value: unknown): value is DocumentList {
  return (
    isRecord(value) &&
    Array.isArray(value.documents) &&
    value.documents.every(isKnowledgeDocument) &&
    isCount(value.used, DOCUMENT_LIMITS.max_documents) &&
    value.used === value.documents.length &&
    new Set(value.documents.map((document) => document.id)).size === value.documents.length &&
    value.max_documents === DOCUMENT_LIMITS.max_documents &&
    value.max_pages === DOCUMENT_LIMITS.max_pages &&
    value.max_size_bytes === DOCUMENT_LIMITS.max_size_bytes
  )
}

function readDocument(document: KnowledgeDocument): KnowledgeDocument {
  return {
    id: document.id,
    name: document.name,
    pages: document.pages,
    size_bytes: document.size_bytes,
    status: document.status,
    error: document.error ? { code: document.error.code, message: document.error.message } : null,
    warnings: [...document.warnings],
    chunk_count: document.chunk_count,
    created_at: document.created_at,
    updated_at: document.updated_at,
    replacement: document.replacement
      ? {
          name: document.replacement.name,
          status: document.replacement.status,
          error: document.replacement.error
            ? {
                code: document.replacement.error.code,
                message: document.replacement.error.message,
              }
            : null,
        }
      : null,
  }
}

function requireDocumentId(document: KnowledgeDocument, id: string): KnowledgeDocument {
  if (document.id !== id) {
    throw new ApiError('invalid-response', 'The API returned a different document. Refresh the list before continuing.')
  }
  return readDocument(document)
}

function fileBody(file: File): FormData {
  const body = new FormData()
  body.append('file', file, file.name)
  return body
}

function documentOptions(context: DocumentRequestContext) {
  if (!isNonemptyString(context.organizationId)) {
    throw new ApiError('invalid-response', 'The displayed organisation is unknown. Recheck your session before accessing documents.')
  }
  return { signal: context.signal, expectedOrganizationId: context.organizationId }
}

export async function listDocuments(context: DocumentRequestContext): Promise<DocumentList> {
  const list = await requestJson('/api/documents', isDocumentList, documentOptions(context))
  return { ...DOCUMENT_LIMITS, used: list.used, documents: list.documents.map(readDocument) }
}

export async function getDocument(id: string, context: DocumentRequestContext): Promise<KnowledgeDocument> {
  const document = await requestJson(`/api/documents/${encodeURIComponent(id)}`, isKnowledgeDocument, documentOptions(context))
  return requireDocumentId(document, id)
}

export async function uploadDocument(file: File, context: DocumentRequestContext): Promise<KnowledgeDocument> {
  const document = await requestJson('/api/documents', isKnowledgeDocument, {
    ...documentOptions(context),
    method: 'POST',
    body: fileBody(file),
    successStatus: 202,
    timeoutMs: DOCUMENT_VALIDATION_TIMEOUT_MS,
  })
  return readDocument(document)
}

export async function replaceDocument(
  id: string,
  file: File,
  context: DocumentRequestContext,
): Promise<KnowledgeDocument> {
  const document = await requestJson(`/api/documents/${encodeURIComponent(id)}`, isKnowledgeDocument, {
    ...documentOptions(context),
    method: 'PUT',
    body: fileBody(file),
    successStatus: 202,
    timeoutMs: DOCUMENT_VALIDATION_TIMEOUT_MS,
  })
  return requireDocumentId(document, id)
}

export async function deleteDocument(id: string, context: DocumentRequestContext): Promise<void> {
  await requestNoContent(`/api/documents/${encodeURIComponent(id)}`, { ...documentOptions(context), method: 'DELETE' })
}
