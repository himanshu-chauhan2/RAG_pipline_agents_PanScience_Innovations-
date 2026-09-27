import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { deleteDocument, replaceDocument, uploadDocument } from '../api/documents'
import type { KnowledgeDocument } from '../api/documents'
import { useAuth } from '../auth/AuthProvider'
import DocumentTable, { formatFileSize } from '../components/DocumentTable'
import Icon from '../components/Icon'
import RequestError from '../components/RequestError'
import { canReplaceDocument, canUploadDocument, hasPendingDocuments } from '../documents/polling'
import { useDocumentLibrary } from '../documents/useDocumentLibrary'
import { validatePdfSelection } from '../validation/documents'

interface DocumentTarget {
  id: string
  name: string
}

export default function KnowledgeBasePage() {
  const { state: sessionState, workspaceReviewRequired } = useAuth()
  const organizationId = sessionState.status === 'authenticated' ? sessionState.session.organization.id : ''
  const library = useDocumentLibrary(organizationId)
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [replacementTarget, setReplacementTarget] = useState<DocumentTarget | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DocumentTarget | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const deleteConfirmation = useRef<HTMLElement>(null)
  const deleteTrigger = useRef<HTMLButtonElement | null>(null)
  const listHeading = useRef<HTMLHeadingElement>(null)
  const data = library.snapshot?.data
  const canMutate = Boolean(data) && !library.stale && !library.error && !library.mutationPending && !workspaceReviewRequired
  const currentReplacement = data?.documents.find((document) => document.id === replacementTarget?.id)
  const currentDelete = data?.documents.find((document) => document.id === deleteTarget?.id)
  const quotaFull = data ? !canUploadDocument(data) : false
  const replacementBlocked = replacementTarget !== null && (!currentReplacement || !canReplaceDocument(currentReplacement))
  const submitDisabled = !canMutate || !file || Boolean(fileError) || replacementBlocked || (!replacementTarget && quotaFull)

  useEffect(() => {
    if (replacementTarget) fileInput.current?.focus()
  }, [replacementTarget])
  useEffect(() => {
    if (deleteTarget) deleteConfirmation.current?.focus()
  }, [deleteTarget])

  function clearFile() {
    setFile(null)
    setFileError(null)
    if (fileInput.current) fileInput.current.value = ''
  }

  function beginReplacement(document: KnowledgeDocument) {
    clearFile()
    setDeleteTarget(null)
    library.clearMutationError()
    setReplacementTarget({ id: document.id, name: document.name })
  }

  function cancelReplacement() {
    clearFile()
    setReplacementTarget(null)
    library.clearMutationError()
    listHeading.current?.focus()
  }

  function beginDelete(document: KnowledgeDocument, trigger: HTMLButtonElement) {
    clearFile()
    setReplacementTarget(null)
    library.clearMutationError()
    deleteTrigger.current = trigger
    setDeleteTarget({ id: document.id, name: document.name })
  }

  function cancelDelete() {
    setDeleteTarget(null)
    if (deleteTrigger.current?.isConnected) deleteTrigger.current.focus()
    else listHeading.current?.focus()
  }

  async function submitFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const error = validatePdfSelection(file)
    if (error || !file) {
      setFileError(error ?? 'Choose one PDF to continue.')
      fileInput.current?.focus()
      return
    }
    if (!canMutate || replacementBlocked || (!replacementTarget && quotaFull)) return
    const selectedFile = file
    const target = currentReplacement
    const outcome = replacementTarget && target
      ? await library.performMutation(
          (signal) => replaceDocument(target.id, selectedFile, { organizationId, signal }),
          () => target.status === 'ready'
            ? `Replacement accepted for ${target.name}. Its existing index is retained until the new PDF is ready.`
            : `Replacement accepted for ${target.name}. Check its indexing status below.`,
        )
      : await library.performMutation(
          (signal) => uploadDocument(selectedFile, { organizationId, signal }),
          (document) => `Upload accepted: ${document.name}. Current indexing status is reported below.`,
        )
    if (outcome === 'accepted' || outcome === 'uncertain') {
      clearFile()
      setReplacementTarget(null)
      listHeading.current?.focus()
    }
  }

  async function confirmDelete() {
    if (!deleteTarget || !currentDelete || !canMutate) return
    const target = currentDelete
    const outcome = await library.performMutation(
      (signal) => deleteDocument(target.id, { organizationId, signal }),
      () => `${target.name} was deleted. Its file, index and any pending work have been removed from this knowledge base.`,
    )
    if (outcome === 'accepted' || outcome === 'uncertain') {
      setDeleteTarget(null)
      listHeading.current?.focus()
    }
  }

  const pendingDocuments = data ? hasPendingDocuments(data.documents) : false
  const readyCount = data?.documents.filter((document) => document.status === 'ready').length
  const failedCount = data?.documents.filter((document) => document.status === 'failed').length

  return (
    <section aria-labelledby="knowledge-heading">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <p className="eyebrow">Knowledge Base</p>
        <span className="rounded-full border border-accent/20 bg-sage px-3 py-1.5 text-xs font-medium text-accent">
          P2 · Private PDFs
        </span>
      </div>
      <h1 id="knowledge-heading" className="max-w-2xl text-3xl leading-tight font-semibold tracking-[-0.035em] sm:text-4xl">
        Your organisation’s knowledge, in one place.
      </h1>
      <p className="mt-4 max-w-2xl text-base leading-7 text-muted">
        Upload and manage private PDFs with local indexing. Grounded chat and
        assistant publishing are still planned for later phases.
      </p>

      {!data && !library.error && (
        <div role="status" className="mt-8 rounded-xl border border-line bg-white p-6 text-sm text-muted">
          <Icon name="refresh" className="mb-3 size-5 text-accent motion-safe:animate-spin" />
          Loading the document list and checking available slots…
        </div>
      )}
      {library.error && (
        <div className="mt-6">
          <RequestError
            title={data ? 'The document list could not be refreshed.' : 'The knowledge base could not be loaded.'}
            error={library.error}
            onRetry={library.mutationPending ? undefined : library.refresh}
            retryLabel="Retry document list"
          >
            <p className="mt-2">
              {data
                ? 'The list and quota below are stale. Changes are disabled until a refresh succeeds.'
                : 'Document counts and available slots are unknown. This is not an empty knowledge base.'}
            </p>
          </RequestError>
        </div>
      )}
      {library.mutationError && (
        <div className="mt-6">
          <RequestError
            title={library.mutationError.kind === 'http' ? 'The document request was rejected.' : 'The document change is unconfirmed.'}
            error={library.mutationError}
          >
            {library.mutationError.fields?.file &&
              library.mutationError.fields.file !== library.mutationError.message && (
                <p className="mt-2">{library.mutationError.fields.file}</p>
              )}
            <p className="mt-2">
              {library.mutationError.kind !== 'http'
                ? 'Review the document list before another action. File selections and delete confirmations are cleared after reconciliation to prevent accidental resubmission; requests are never retried automatically.'
                : 'Review the message and current document status before trying again.'}
            </p>
          </RequestError>
        </div>
      )}
      <div role="status" aria-live="polite" aria-atomic="true">
        {library.notice && (
          <p className="mt-6 rounded-xl border border-accent/20 bg-sage px-5 py-4 text-sm leading-6 text-accent">
            {library.notice}
          </p>
        )}
      </div>

      {data && (
        <>
          <div className="mt-8 rounded-xl border border-line bg-white p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">
                  {library.stale ? 'Last known document slots' : 'Document slots'} <span className="ml-2 font-mono">{data.used} / {data.max_documents}</span>
                  {library.stale && <span className="ml-2 text-xs text-warning">Stale count</span>}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted">
                  Processing and failed PDFs count towards the limit. Replacements reuse a slot.
                </p>
              </div>
              <button
                type="button"
                className="button-secondary min-h-10 px-3 py-2 text-xs"
                disabled={library.refreshing || library.mutationPending}
                onClick={library.refresh}
              >
                <Icon name="refresh" className={`size-4 ${library.refreshing ? 'motion-safe:animate-spin' : ''}`} />
                {library.refreshing ? 'Refreshing…' : 'Refresh status'}
              </button>
            </div>
            <meter
              min={0}
              max={data.max_documents}
              value={data.used}
              aria-label={library.stale ? 'Document slots used, stale snapshot' : 'Document slots used'}
              className="quota-meter mt-4 h-3 w-full"
            >
              {data.used} of {data.max_documents} slots used
            </meter>
            <div className="mt-3 flex flex-wrap justify-between gap-2 text-xs leading-5 text-muted">
              <p>{readyCount} ready · {failedCount} failed{library.stale ? ' · Stale snapshot' : ''}</p>
              <p>
                Last checked{' '}
                <time dateTime={library.snapshot?.checkedAt.toISOString()}>
                  {library.snapshot?.checkedAt.toLocaleTimeString()}
                </time>
              </p>
            </div>
          </div>

          {library.stale && (
            <p role="status" className="mt-4 rounded-lg border border-warning-line bg-warning-soft px-4 py-3 text-sm leading-6 text-warning">
              {library.refreshing
                ? 'Refreshing after a document change. The previous list and quota are shown below; they are not current.'
                : 'Stale snapshot: do not rely on the displayed list or quota until a refresh succeeds.'}
            </p>
          )}

          <section aria-labelledby="upload-heading" className="mt-6 rounded-xl border border-line bg-white p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 id="upload-heading" className="text-lg font-semibold tracking-tight">
                  {replacementTarget ? 'Replace a PDF' : 'Add a PDF'}
                </h2>
                {replacementTarget && (
                  <p className="mt-2 text-sm leading-6 text-muted [overflow-wrap:anywhere]">
                    Replacing <strong className="font-medium text-ink">{currentReplacement?.name ?? replacementTarget.name}</strong>.
                    {' '}{currentReplacement?.status === 'ready'
                      ? 'The old indexed PDF stays active until the replacement succeeds.'
                      : 'This uses the existing slot, even when the knowledge base is full.'}
                  </p>
                )}
              </div>
              {replacementTarget && (
                <button type="button" className="button-secondary min-h-10 px-3 py-2 text-xs" disabled={library.mutationPending} onClick={cancelReplacement}>
                  Cancel selection
                </button>
              )}
            </div>
            <p id="pdf-file-hint" className="mt-2 text-xs leading-6 text-muted">
              One PDF at a time · up to 20 pages · maximum 10 MB (10,000,000 bytes).
              The server checks PDF content, encryption, page limits and readable text.
              {' '}Allow up to 60 seconds for validation.
            </p>
            <p className="mt-2 text-xs leading-6 text-muted">
              PDFs without extractable text are rejected. Mixed or blank-page PDFs can
              index their text-bearing pages with warnings. OCR is not available.
            </p>
            {quotaFull && !replacementTarget && (
              <p className="mt-3 text-sm leading-6 text-warning">
                All 10 slots are in use. Replace an existing PDF without using another slot, or delete one to add a new document.
              </p>
            )}
            {workspaceReviewRequired && (
              <p className="mt-3 text-sm leading-6 text-warning">
                Review the active organisation in the notice above and choose <strong>Use this workspace</strong> before selecting a PDF or changing documents.
              </p>
            )}
            {replacementBlocked && (
              <p className="mt-3 text-sm leading-6 text-warning">
                {currentReplacement
                  ? 'Indexing or a replacement is already in progress. Wait for it to finish, or cancel this selection.'
                  : 'This document is no longer in the current list. Cancel this replacement to continue.'}
              </p>
            )}
            <form onSubmit={submitFile} className="mt-4">
              <label htmlFor="pdf-file" className="mb-2 block text-sm font-medium">Choose a PDF</label>
              <input
                ref={fileInput}
                id="pdf-file"
                type="file"
                accept=".pdf,application/pdf"
                disabled={!canMutate || replacementBlocked || (!replacementTarget && quotaFull)}
                aria-invalid={fileError ? true : undefined}
                aria-describedby={`pdf-file-hint${fileError ? ' pdf-file-error' : ''}`}
                onChange={(event) => {
                  const selected = event.target.files?.item(0) ?? null
                  setFile(selected)
                  setFileError(selected ? validatePdfSelection(selected) ?? null : null)
                  library.clearMutationError()
                }}
                className="field-input min-w-0 p-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-sage file:px-3 file:py-2 file:text-sm file:font-medium file:text-accent"
              />
              {fileError && <p id="pdf-file-error" role="alert" className="mt-2 text-sm leading-6 text-warning">{fileError}</p>}
              {file && (
                <p className="mt-3 text-xs leading-6 text-muted [overflow-wrap:anywhere]">
                  Selected: <strong className="font-medium text-ink">{file.name}</strong>
                  {' '}· {formatFileSize(file.size)} ({file.size.toLocaleString()} bytes)
                </p>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-4">
                <button type="submit" disabled={submitDisabled} className="button-primary">
                  <Icon name={library.mutationPending ? 'refresh' : 'upload'} className={`size-4 ${library.mutationPending ? 'motion-safe:animate-spin' : ''}`} />
                  {library.mutationPending ? 'Request in progress…' : replacementTarget ? 'Replace PDF' : 'Upload PDF'}
                </button>
                <p className="max-w-sm text-xs leading-5 text-muted">
                  Upload acceptance is not indexing completion. Status updates appear in the list below.
                </p>
              </div>
            </form>
          </section>

          {deleteTarget && (
            <section
              ref={deleteConfirmation}
              tabIndex={-1}
              aria-labelledby="delete-heading"
              className="mt-6 rounded-xl border border-warning-line bg-warning-soft p-5 text-sm leading-6 sm:p-6"
            >
              <h2 id="delete-heading" className="text-lg font-semibold text-warning">Delete this PDF?</h2>
              <p className="mt-2 [overflow-wrap:anywhere]">
                <strong>{currentDelete?.name ?? deleteTarget.name}</strong> will be removed together with
                its index and any pending processing or replacement. This cannot be undone.
              </p>
              {!currentDelete && <p className="mt-2 text-warning">This PDF is no longer in the current list. Close this confirmation to continue.</p>}
              {library.stale && <p className="mt-2 text-warning">Refresh the stale document list before retrying a deletion.</p>}
              <div className="mt-4 flex flex-wrap gap-3">
                <button type="button" className="button-primary button-danger" onClick={() => void confirmDelete()} disabled={!canMutate || !currentDelete}>
                  {library.mutationPending ? 'Request in progress…' : 'Delete permanently'}
                </button>
                <button type="button" className="button-secondary" onClick={cancelDelete} disabled={library.mutationPending}>
                  {currentDelete ? 'Cancel' : 'Close confirmation'}
                </button>
              </div>
            </section>
          )}

          <section aria-labelledby="document-list-heading" className="mt-8" aria-busy={library.refreshing}>
            <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
              <h2 id="document-list-heading" ref={listHeading} tabIndex={-1} className="rounded-sm text-xl font-semibold tracking-tight">Your documents</h2>
              <p className={`text-xs leading-5 ${library.stale ? 'font-semibold text-warning' : 'text-muted'}`}>
                {library.stale ? 'Stale snapshot · Refresh required' : 'Private to this organisation · Local indexing'}
              </p>
            </div>
            {library.pollingPaused && pendingDocuments ? (
              <p role="status" className="mb-4 rounded-lg border border-line bg-white px-4 py-3 text-sm leading-6 text-muted">
                Automatic status checks are paused. Indexing may still be running on the server.
                Use <strong>Refresh status</strong> to check again and resume bounded checks.
              </p>
            ) : pendingDocuments && !library.error && !library.stale ? (
              <p className="mb-4 text-xs leading-5 text-muted">
                Checking pending work every 3 seconds, for up to 2 minutes per polling round. No percentage progress is estimated.
              </p>
            ) : null}
            <p role="status" aria-live="polite" className="sr-only">
              {library.stale ? 'Document information is stale.' : `${data.used} document slots used. ${readyCount} ready and ${failedCount} failed.`}
            </p>
            {data.documents.length === 0 ? (
              <div className="rounded-xl border border-dashed border-line bg-white/60 px-6 py-10 text-center">
                <Icon name="documents" className="mx-auto mb-4 size-8 text-accent" />
                <h3 className="text-lg font-semibold">{library.stale ? 'The previous snapshot was empty.' : 'No documents yet.'}</h3>
                <p className="mx-auto mt-2 max-w-md text-sm leading-7 text-muted">
                  {library.stale
                    ? 'The current document list is unknown. Refresh successfully before relying on the earlier empty result.'
                    : 'The backend reports an empty knowledge base. Choose your first PDF above to start indexing.'}
                </p>
              </div>
            ) : (
              <DocumentTable
                documents={data.documents}
                disabled={!canMutate}
                onReplace={beginReplacement}
                onDelete={beginDelete}
              />
            )}
          </section>
        </>
      )}
    </section>
  )
}
