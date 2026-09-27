import { DOCUMENT_LIMITS } from '../api/documents.ts'

export function validatePdfSelection(file: Pick<File, 'size'> | null): string | undefined {
  if (!file) return 'Choose one PDF to continue.'
  if (!Number.isSafeInteger(file.size) || file.size <= 0) {
    return 'The selected file is empty or has an invalid size. Choose another PDF.'
  }
  if (file.size > DOCUMENT_LIMITS.max_size_bytes) {
    return 'The file exceeds 10 MB (10,000,000 bytes). Choose a smaller PDF.'
  }
  return undefined
}
