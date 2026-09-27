import type { KnowledgeDocument } from '../api/documents'
import { canReplaceDocument } from '../documents/polling'
import Icon from './Icon'

export function formatFileSize(bytes: number): string {
  if (bytes < 1_000) return `${bytes.toLocaleString()} B`
  const divisor = bytes < 1_000_000 ? 1_000 : 1_000_000
  const unit = bytes < 1_000_000 ? 'kB' : 'MB'
  return `${(bytes / divisor).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${unit}`
}

function DocumentStatus({ status }: { status: KnowledgeDocument['status'] }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
      status === 'ready' ? 'bg-sage text-accent' : status === 'failed' ? 'bg-warning-soft text-warning' : 'bg-canvas text-muted'
    }`}>
      {status === 'processing' && <Icon name="refresh" className="size-3 motion-safe:animate-spin" />}
      {status === 'ready' ? 'Ready' : status === 'failed' ? 'Failed' : 'Processing'}
    </span>
  )
}

export default function DocumentTable({
  documents,
  disabled,
  onReplace,
  onDelete,
}: {
  documents: readonly KnowledgeDocument[]
  disabled: boolean
  onReplace: (document: KnowledgeDocument) => void
  onDelete: (document: KnowledgeDocument, trigger: HTMLButtonElement) => void
}) {
  return (
    <>
      <p className="mb-3 text-xs leading-5 text-muted lg:hidden">
        On smaller screens, scroll the table horizontally to see every column.
      </p>
      <div role="region" aria-label="Private document list" tabIndex={0} className="overflow-x-auto rounded-xl border border-line bg-white">
        <table className="w-full min-w-[44rem] text-left text-sm">
          <caption className="sr-only">
            Organisation PDFs. During replacement, a ready PDF’s metadata and chunks describe its active version.
          </caption>
          <thead className="border-b border-line bg-canvas/70 text-xs text-muted">
            <tr>
              <th scope="col" className="px-4 py-4 font-medium">Current PDF</th>
              <th scope="col" className="px-3 py-4 font-medium">Index status</th>
              <th scope="col" className="px-3 py-4 text-right font-medium">Pages</th>
              <th scope="col" className="px-3 py-4 text-right font-medium">Size</th>
              <th scope="col" className="px-3 py-4 text-right font-medium">Chunks</th>
              <th scope="col" className="px-4 py-4 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {documents.map((document) => (
              <tr key={document.id} className="align-top">
                <th scope="row" className="min-w-56 max-w-80 px-4 py-5 font-normal">
                  <div className="flex items-start gap-2.5">
                    <Icon name="documents" className="mt-0.5 size-5 text-accent" />
                    <div className="min-w-0">
                      <p className="font-semibold [overflow-wrap:anywhere]">{document.name}</p>
                      <p className="mt-1 text-xs leading-5 text-muted">
                        Updated{' '}
                        <time dateTime={document.updated_at}>{new Date(document.updated_at).toLocaleString()}</time>
                      </p>
                    </div>
                  </div>
                  {document.warnings.length > 0 && (
                    <div className="mt-3 rounded-lg border border-warning-line bg-warning-soft p-3 text-xs leading-5 text-warning">
                      <p className="font-semibold">
                        {document.status === 'ready' && document.replacement
                          ? 'Active PDF extraction warnings'
                          : 'Extraction warnings'}
                      </p>
                      <ul className="mt-1 list-disc space-y-1 pl-4">
                        {document.warnings.map((warning, index) => <li key={index}>{warning}</li>)}
                      </ul>
                      <p className="mt-2">
                        Only pages with extractable text can be indexed. OCR is not available.
                      </p>
                    </div>
                  )}
                  {document.status === 'failed' && (
                    <div className="mt-3 rounded-lg bg-warning-soft p-3 text-xs leading-5 text-warning">
                      <p>{document.error?.message ?? 'Indexing failed. Replace or delete this PDF to continue.'}</p>
                      {document.error && <p className="mt-1 break-all font-mono">{document.error.code}</p>}
                      <p className="mt-1">This document still occupies a slot.</p>
                    </div>
                  )}
                  {document.replacement && (
                    <div className={`mt-3 rounded-lg border p-3 text-xs leading-5 ${
                      document.replacement.status === 'failed'
                        ? 'border-warning-line bg-warning-soft text-warning'
                        : 'border-line bg-canvas text-muted'
                    }`}>
                      <p className="font-semibold">
                        {document.replacement.status === 'processing' ? 'Replacement processing' : 'Replacement failed'}
                      </p>
                      <p className="mt-1 [overflow-wrap:anywhere]">{document.replacement.name}</p>
                      {document.replacement.error && (
                        <>
                          <p className="mt-1">{document.replacement.error.message}</p>
                          <p className="mt-1 break-all font-mono">{document.replacement.error.code}</p>
                        </>
                      )}
                      <p className="mt-2 font-medium">
                        {document.status === 'ready'
                          ? 'The old PDF remains ready and indexed. It is replaced only when the new index succeeds.'
                          : 'A ready index is not available yet. The new PDF must finish indexing first.'}
                      </p>
                    </div>
                  )}
                </th>
                <td className="px-3 py-5">
                  <DocumentStatus status={document.status} />
                  {document.status === 'ready' && document.replacement && (
                    <p className="mt-2 text-xs leading-5 text-muted">Active version retained</p>
                  )}
                </td>
                <td className="px-3 py-5 text-right tabular-nums">{document.pages.toLocaleString()}</td>
                <td className="whitespace-nowrap px-3 py-5 text-right tabular-nums" title={`${document.size_bytes.toLocaleString()} bytes`}>
                  {formatFileSize(document.size_bytes)}
                </td>
                <td className="px-3 py-5 text-right tabular-nums">{document.chunk_count.toLocaleString()}</td>
                <td className="px-4 py-5">
                  <div className="flex min-w-28 flex-col items-start gap-2">
                    <button
                      type="button"
                      className="button-secondary min-h-10 px-3 py-2 text-xs"
                      disabled={disabled || !canReplaceDocument(document)}
                      aria-label={`Replace ${document.name}`}
                      title={!canReplaceDocument(document) ? 'Wait for the current indexing or replacement to finish.' : undefined}
                      onClick={() => onReplace(document)}
                    >
                      Replace
                    </button>
                    <button
                      type="button"
                      className="min-h-10 rounded-md px-3 py-2 text-xs font-semibold text-warning underline-offset-4 hover:underline disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={disabled}
                      aria-label={`Delete ${document.name}`}
                      onClick={(event) => onDelete(document, event.currentTarget)}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs leading-5 text-muted">
        Files stay private. For a ready PDF being replaced, the name, pages, size and
        chunk count and extraction warnings above still describe its active version.
      </p>
    </>
  )
}
