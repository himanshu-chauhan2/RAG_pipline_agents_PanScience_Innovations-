import type { LoginInput, RegisterInput } from '../api/auth.ts'

export type AuthField = keyof RegisterInput
export type FieldErrors = Partial<Record<AuthField, string>>
export type ValidationResult<T> =
  | { valid: true; data: T }
  | { valid: false; errors: FieldErrors }

const encoder = new TextEncoder()
const characterCount = (value: string) => Array.from(value).length

function emailError(email: string): string | undefined {
  if (!email) {
    return 'Enter your email address.'
  }
  if (characterCount(email) > 254) {
    return 'Use an email address of 254 characters or fewer.'
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(email)) {
    return 'Enter a valid email address.'
  }
  return undefined
}

function passwordError(password: string, isRegistration: boolean): string | undefined {
  if (password.length === 0) {
    return 'Enter your password.'
  }
  if (isRegistration && password.trim().length === 0) {
    return 'Your password cannot contain only whitespace.'
  }
  if (isRegistration && characterCount(password) < 8) {
    return 'Use at least 8 characters.'
  }
  if (encoder.encode(password).byteLength > 72) {
    return 'Use at most 72 UTF-8 bytes. Some characters use more than one byte.'
  }
  return undefined
}

export function validateLogin(input: LoginInput): ValidationResult<LoginInput> {
  const data = { email: input.email.trim().toLowerCase(), password: input.password }
  const errors: FieldErrors = {}
  const invalidEmail = emailError(data.email)
  const invalidPassword = passwordError(data.password, false)
  if (invalidEmail) errors.email = invalidEmail
  if (invalidPassword) errors.password = invalidPassword
  return Object.keys(errors).length ? { valid: false, errors } : { valid: true, data }
}

export function validateRegistration(
  input: RegisterInput,
): ValidationResult<RegisterInput> {
  const data = {
    organization_name: input.organization_name.trim(),
    full_name: input.full_name.trim(),
    email: input.email.trim().toLowerCase(),
    password: input.password,
  }
  const errors: FieldErrors = {}
  if (!data.organization_name) {
    errors.organization_name = 'Enter your organisation name.'
  } else if (characterCount(data.organization_name) > 120) {
    errors.organization_name = 'Use an organisation name of 120 characters or fewer.'
  }
  if (!data.full_name) {
    errors.full_name = 'Enter your full name.'
  } else if (characterCount(data.full_name) > 100) {
    errors.full_name = 'Use a full name of 100 characters or fewer.'
  }
  const invalidEmail = emailError(data.email)
  const invalidPassword = passwordError(data.password, true)
  if (invalidEmail) errors.email = invalidEmail
  if (invalidPassword) errors.password = invalidPassword
  return Object.keys(errors).length ? { valid: false, errors } : { valid: true, data }
}

export function serverFieldErrors(fields: Record<string, string> | undefined): FieldErrors {
  const errors: FieldErrors = {}
  const knownFields: AuthField[] = ['organization_name', 'full_name', 'email', 'password']
  for (const field of knownFields) {
    if (fields?.[field]) {
      errors[field] = fields[field]
    }
  }
  return errors
}
