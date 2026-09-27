import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  serverFieldErrors,
  validateLogin,
  validateRegistration,
} from '../src/validation/auth.ts'

const input = {
  organization_name: 'Example Organisation',
  full_name: 'Alex Morgan',
  email: 'alex@example.com',
  password: 'example password',
}

test('registration trims names and normalizes email without changing password whitespace', () => {
  assert.deepEqual(
    validateRegistration({
      organization_name: '  Example Organisation  ',
      full_name: '  Alex Morgan ',
      email: '  Alex@EXAMPLE.COM ',
      password: '  example password  ',
    }),
    { valid: true, data: { ...input, password: '  example password  ' } },
  )
})

test('registration rejects blank names and empty or whitespace-only passwords', () => {
  const result = validateRegistration({
    ...input,
    organization_name: ' \t ',
    full_name: ' ',
    password: '        ',
  })
  assert.equal(result.valid, false)
  if (!result.valid) {
    assert.ok(result.errors.organization_name)
    assert.ok(result.errors.full_name)
    assert.ok(result.errors.password)
  }
  assert.equal(validateRegistration({ ...input, password: '' }).valid, false)
})

test('registration enforces the inclusive organisation and full-name limits', () => {
  assert.equal(
    validateRegistration({
      ...input,
      organization_name: 'a'.repeat(120),
      full_name: 'a'.repeat(100),
    }).valid,
    true,
  )
  assert.equal(validateRegistration({ ...input, organization_name: 'a'.repeat(121) }).valid, false)
  assert.equal(validateRegistration({ ...input, full_name: 'a'.repeat(101) }).valid, false)
  assert.equal(validateRegistration({ ...input, full_name: '😀'.repeat(100) }).valid, true)
})

test('registration requires eight Unicode characters, not eight UTF-16 units', () => {
  assert.equal(validateRegistration({ ...input, password: '1234567' }).valid, false)
  assert.equal(validateRegistration({ ...input, password: '12345678' }).valid, true)
  assert.equal(validateRegistration({ ...input, password: '😀'.repeat(4) }).valid, false)
  assert.equal(validateRegistration({ ...input, password: '😀'.repeat(8) }).valid, true)
})

test('registration enforces the 72 UTF-8 byte maximum without truncation', () => {
  assert.equal(validateRegistration({ ...input, password: 'a'.repeat(72) }).valid, true)
  assert.equal(validateRegistration({ ...input, password: 'a'.repeat(73) }).valid, false)
  assert.equal(validateRegistration({ ...input, password: '😀'.repeat(18) }).valid, true)
  assert.equal(validateRegistration({ ...input, password: '😀'.repeat(19) }).valid, false)
})

test('preserved password whitespace contributes to the registration length', () => {
  const password = '       x'
  assert.deepEqual(validateRegistration({ ...input, password }), {
    valid: true,
    data: { ...input, password },
  })
})

test('email validation rejects missing, malformed and oversized addresses', () => {
  const longestEmail = `${'a'.repeat(64)}@${'b'.repeat(63)}.${'c'.repeat(63)}.${'d'.repeat(61)}`
  assert.equal(longestEmail.length, 254)
  assert.equal(validateRegistration({ ...input, email: longestEmail }).valid, true)
  for (const email of ['', 'not-an-email', 'a@@example.com', 'a b@example.com', `${longestEmail}x`]) {
    assert.equal(validateRegistration({ ...input, email }).valid, false)
    assert.equal(validateLogin({ ...input, email }).valid, false)
  }
})

test('login normalizes email and preserves the original password', () => {
  assert.deepEqual(validateLogin({ email: ' Alex@EXAMPLE.COM ', password: ' pass ' }), {
    valid: true,
    data: { email: 'alex@example.com', password: ' pass ' },
  })
})

test('login allows nonempty short or whitespace passwords but enforces the byte limit', () => {
  assert.equal(validateLogin({ ...input, password: '' }).valid, false)
  assert.equal(validateLogin({ ...input, password: 'x' }).valid, true)
  assert.equal(validateLogin({ ...input, password: ' ' }).valid, true)
  assert.equal(validateLogin({ ...input, password: '😀'.repeat(18) }).valid, true)
  assert.equal(validateLogin({ ...input, password: '😀'.repeat(19) }).valid, false)
})

test('only known server fields become form errors', () => {
  assert.deepEqual(serverFieldErrors(undefined), {})
  assert.deepEqual(
    serverFieldErrors({ email: 'Already registered.', unexpected: 'Ignored.' }),
    { email: 'Already registered.' },
  )
  assert.deepEqual(
    serverFieldErrors(Object.fromEntries([['__proto__', 'Ignored.'], ['password', 'Too long.']])),
    { password: 'Too long.' },
  )
})
