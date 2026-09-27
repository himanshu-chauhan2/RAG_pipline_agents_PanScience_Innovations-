# Frontend · private knowledge base and public assistant

An **independent PanScience hackathon submission**, not an official PanScience
service. React, Vite, TypeScript, Tailwind and React Router provide organisation
accounts, a private PDF knowledge base, upload/replacement/deletion controls,
local indexing status, a public assistant chat, iframe code and backend health diagnostics.

The Assistant dashboard loads the authenticated owner's token and gives a
working public URL and iframe embed snippet. The public chat runs outside the
admin session gate, shows source pages and a structured decision trace, and
distinguishes missing facts and missing evidence from request errors. Usage
reporting, token rotation and script embedding are **not implemented**; there
are no fake metrics or PDF download links.

## Local development

Use Node.js 22.14 or newer and npm. From this directory:

```powershell
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Start the backend separately using the repository's
instructions. Vite proxies `/api` to `http://127.0.0.1:8000`. All application
requests are same-origin; the auth/document client explicitly uses
`credentials: "same-origin"`. The browser supplies the Origin header on mutation
requests; frontend code does not fabricate an Origin or Authorization header.

Use the same hostname throughout a session: `localhost` and `127.0.0.1` have
separate cookie stores. The backend accepts these hosts on ports 5173, 4173 and
8000. The API docs link opens `http://127.0.0.1:8000/docs` in a new tab.

No frontend environment file is needed. Gateway credentials and the gateway
address belong only in backend configuration, never in frontend source, forms,
browser storage or `VITE_*` environment variables.

## Routes and session behavior

| Route | Behavior |
| --- | --- |
| `/` | Redirects to the dashboard or sign-in after checking the session. |
| `/login` | Email/password sign-in; authenticated visitors go to the dashboard. |
| `/register` | Creates an organisation account and signs in automatically. |
| `/dashboard` | Protected; redirects to Knowledge Base. |
| `/dashboard/knowledge-base` | Private document list, real quota, uploads, safe replacement and confirmed deletion. |
| `/dashboard/assistant` | Owner-only assistant link and iframe embed code. |
| `/a/:token` | Public assistant chat; no admin sign-in needed. |
| `/dashboard/usage` | Explicitly unimplemented usage reporting. |

Redirect destinations are fixed application paths. User-supplied return URLs
are not accepted, preventing open redirects.

- `GET /api/auth/me` bootstraps the session. No protected content or account
  forms render until this check completes.
- A validated `401 / unauthenticated` error means anonymous. Network failures,
  server errors and malformed payloads display **Retry session check** rather
  than pretending the visitor is logged out.
- JWTs are held only in the backend's **HttpOnly cookie**, backed by revocable
  server sessions. Frontend code neither reads the cookie nor stores tokens in
  localStorage, sessionStorage or application state. Only validated user,
  organisation and expiry fields are retained in memory.
- A session is rechecked when its known expiry is reached and when an
  authenticated browser window regains focus. The backend remains authoritative.
  An already-expired success payload is treated as an invalid response, not
  accepted as a usable session. **Focus always calls `/api/auth/me`, even before
  expiry**: another tab can change the shared HttpOnly cookie. An unexpired check
  runs quietly; a same-user/same-organisation result updates the verified session
  without remounting the view, preserving native file-picker selections.
  Initial and expired-session checks still block the workspace; verification
  failures hide protected content and show Retry, and confirmed unauthenticated
  responses clear the session.
- Changed user/organisation identity, session clearing and explicit workspace
  mismatch resets discard the old protected view. Its document requests,
  mutations and polling timers are cancelled on unmount. A changed identity
  requires explicit workspace review before document changes.
- The dashboard loads `GET /api/organizations/{current-organization-id}`. A
  mismatched organisation response is rejected; a verified unauthenticated
  response returns the visitor to sign-in. Other failures have a separate retry.
- `POST /api/auth/logout` accepts **204 without parsing JSON**, or an already
  unauthenticated response. Network, server and invalid-response failures remain
  visible and **do not clear the local session**; the sign-out button can retry.
- Reads/auth requests time out after eight seconds, including body reading.
  PDF upload/replacement requests allow 60 seconds for transfer and validation.
  Requests are cancelled when their owning view unmounts. HTTP failures preserve
  the backend error code, field errors and request reference.

## PDF workflow

The table and quota meter come from `GET /api/documents`. An initial load failure
does not create an empty list or a zero count. If refreshing fails, the last
successful snapshot can remain visible only with **stale list/quota** warnings;
mutation controls stay disabled until a refresh succeeds. A previously empty
snapshot is labelled as historical, not as the current knowledge base.

- **Limits:** 10 documents, 20 pages per PDF and exactly **10,000,000 bytes**
  per file (10 decimal MB, not 10 MiB). Processing and failed initial documents
  occupy slots. The browser checks the selected file's size; the PDF accept
  filter is only a picker hint. Content, filename, encryption, page count and
  readable-text validation belong to the backend.
- **Upload:** choose one file, then explicitly submit it. A 202 response means
  accepted after PDF validation, not necessarily indexed. The list reports
  Processing, Ready or Failed, actual page/byte/chunk counts, extraction warnings
  and indexing error details.
- **Text extraction:** a wholly unreadable/scanned PDF is rejected with 400.
  A mixed or blank-page PDF may index its text-bearing pages with explicit
  warnings. **OCR is not available.** The always-present `warnings: string[]`
  field is rendered as plain text; an empty array means no reported warnings.
- **Replace:** select Replace on a Ready or Failed document, choose a new file
  and submit. This works at the 10-document quota because it reuses the slot.
  A pending index/replacement blocks another replacement in the UI; the server
  remains authoritative and can return `409 document_busy`.
- **Keep the old index:** a Ready document remains Ready with its old name,
  metadata, chunks and extraction warnings while its replacement processes.
  Replacement failure is displayed separately and leaves the old index active.
  Only a successful replacement swaps metadata/warnings and clears the
  replacement state. Failed initial documents have no ready index to retain.
- **Delete:** a focused, explicit confirmation precedes the DELETE request.
  Processing and replacing documents can also be deleted. The backend prevents
  pending work from restoring a deleted document. The client cancels an older
  list request before a mutation and refreshes the authoritative list afterward.
- **Failures:** field errors, quota/busy conflicts, unavailable storage,
  authentication failures and malformed responses are not silently ignored.
  The UI reconciles the document list after every mutation error when the view
  and session remain active, including validation errors. A workspace mismatch
  takes the forced session-revalidation path below instead of retrying the old
  document context. Network/timeout or
  invalid-response failures may leave an uncertain result: the selected file or
  delete confirmation is cleared after reconciliation, and the user is warned
  to review the list before submitting again. A failed reconciliation leaves a
  visibly stale snapshot with changes disabled. Mutations are never retried
  automatically.
- **Private files:** the frontend does not create object URLs or expose download,
  open-PDF or storage-path links. Processing uses local backend models; there
  are no frontend model or gateway calls.

### Bounded status polling

Only initial Processing documents or a Processing replacement trigger automatic
list checks. Checks do not overlap, run at three-second intervals, and stop at
40 checks or a two-minute monotonic-clock window per round (an in-flight request
also has its own timeout). Ready/Failed-only lists do not poll.

Polling stops on a list error and exposes Retry instead of retrying indefinitely.
Reaching the budget displays **Automatic status checks are paused** without
claiming that backend processing failed. Refresh status starts a new bounded
round; mutation reconciliation does the same when pending work remains. Leaving
the page, resetting the workspace identity or clearing/expiring the session
cancels timers and requests, not already accepted backend indexing work.
No percentage progress is invented.

### Cross-tab workspace safety

Every document helper requires `{organizationId, signal}`. List, get, upload,
replace and delete send **`X-Organization-ID` with the displayed, verified
organisation ID**, including automatic list checks and reconciliation reads.
An empty expected ID is rejected before fetching. The header is an expected-
context assertion, **never a tenant selector**: the backend selects and authorizes
the organisation from the verified cookie, then rejects a mismatched expectation
with `409 workspace_changed` before reading or changing documents.

This closes the race where another tab switches the shared cookie between a
focus check and a document request. Auth verification itself does not send this
header: `/api/auth/me` must report the cookie's actual current identity.

On `workspace_changed`, the frontend stops using the old document context,
blocks the view and rechecks `/api/auth/me`. It forces a fresh workspace view
even if verification returns the same identity, clearing file selections and
delete confirmations. The verified organisation is shown in a review notice.
Document mutation controls remain disabled until the user chooses **Use this
workspace**; no failed mutation is automatically replayed under the new cookie.
Regular `document_busy` and quota conflicts do not trigger an identity switch.

For browser integration checks, select a file and refocus the same identity
(selection should remain), then sign into another organisation in a second tab.
The first tab must either detect the new identity on focus or receive
`workspace_changed` for its old expected context, clear its selections, and
require workspace review before another submission.

### Document API contracts

| Request | Result |
| --- | --- |
| `GET /api/documents` | `{documents, used, max_documents: 10, max_pages: 20, max_size_bytes: 10000000}` |
| `GET /api/documents/{id}` | One validated document; a mismatched ID is rejected. |
| `POST /api/documents` | Multipart field `file`; requires 202 and a document response. |
| `PUT /api/documents/{id}` | Multipart field `file`; requires 202 with the same document ID. |
| `DELETE /api/documents/{id}` | Requires 204; no JSON parsing. |

Multipart bodies contain only `file`; expected organisation context is a header,
not another form field. **Do not manually set Content-Type or Origin**: fetch
generates the multipart boundary and the browser supplies Origin.
The JSON auth client continues to
send its JSON content type. Document errors use the same structured error
contract as auth, including request references and optional field messages.

A document has `id`, `name`, `pages`, `size_bytes`, `status`, nullable
`error: {code, message}`, always-present `warnings: string[]`, `chunk_count`,
`created_at`, `updated_at`, and nullable
`replacement: {name, status: "processing" | "failed", error}`. The runtime guards
validate status values, integer counts, timestamps, published limits, unique
IDs and list/quota consistency. Only documented metadata is retained.

## Public assistant

`GET /api/assistant` requires the owner's cookie and returns this organisation's
token. The dashboard displays the full public URL and copyable iframe HTML;
clipboard failures explain how to copy manually. The URL should be shared only
for documents intended for public visitors.

`/a/:token` deliberately does **not** bootstrap an admin session. It calls
`POST /api/ask` with the token, current question and up to ten prior
user/assistant messages. New chat, route/token change or page reload discards
that browser-memory history; once five exchanges are reached, the form asks the
visitor to begin a new chat rather than silently removing older facts. The
backend may return `answered`, `needs_info` or `insufficient_evidence`; the UI
shows actual PDF filenames/pages, source excerpts, eligibility checks and
explicit processing errors. The question limit is 1,000 characters; the
backend, not browser code, authorizes the token and validates all inputs.
Live direct/compare questions may send retrieved PDF text to the configured
LLM gateway and incur costs.

## Account form validation

The server is authoritative; client checks provide immediate field feedback:

- Organisation name: trimmed, 1–120 Unicode characters.
- Full name: trimmed, 1–100 Unicode characters.
- Email: trimmed, lowercased, basic address validation, at most 254 characters.
- Registration password: at least eight Unicode characters, at most **72 UTF-8
  bytes**, and not entirely whitespace.
- Login password: nonempty and at most 72 UTF-8 bytes.

Passwords are never trimmed, normalized or truncated. There is no confirmation
field in API requests. Labels, autocomplete hints, inline errors, a focused
error summary, pending states and a show/hide password control support keyboard
and assistive-technology use.

## Account API contracts

`POST /api/auth/register` accepts
`{organization_name, full_name, email, password}` and requires status **201**.
`POST /api/auth/login` accepts `{email, password}` and requires **200**.
Both set the cookie; they and `GET /api/auth/me` return:

```json
{
  "user": {
    "id": "user-id",
    "full_name": "Alex Morgan",
    "email": "alex@example.com"
  },
  "organization": {
    "id": "organisation-id",
    "name": "Example Organisation"
  },
  "expires_at": "2030-01-01T08:00:00Z"
}
```

`GET /api/organizations/{id}` returns `{id, name}`. Error responses must match:

```json
{
  "error": {
    "code": "invalid_input",
    "message": "Review the supplied details.",
    "request_id": "request-reference",
    "fields": {
      "email": "Enter a valid email address."
    }
  }
}
```

`fields` is optional. Malformed error responses, including malformed 401
responses, are not accepted as confirmation that a session has ended.

## Local health diagnostics

The dashboard retains the P0 health check inside **Local system diagnostics**,
updated for the current backend phase:

```json
{
  "status": "ok",
  "service": "knowledge-decision-assistant",
  "version": "0.1.0",
  "phase": "P5",
  "gateway_configured": false
}
```

`gateway_configured: true` means **Configured, not verified**; `false` means
**Setup needed**. Failed health checks show configuration as **Not checked**.
Configuration presence is not gateway connectivity. Neither health checks nor
frontend tests call a gateway or LLM.

## Checks and build

```powershell
npm run typecheck
npm test
npm run build
npm run preview
```

- `typecheck` checks application code, Vite configuration and tests.
- `test` uses Node's built-in test runner and TypeScript stripping. Node 22.14
  may emit an experimental warning. HTTP responses are mocked; no backend,
  gateway, credentials or extra test framework is needed. Coverage includes
  multipart boundary generation, byte limits, active-warning replacement
  retention, the 60-second validation timeout, quota rules, failure contracts,
  cancellation, expected-organisation headers, quiet focus verification,
  workspace identity resets and the bounded polling policy.
- `build` runs TypeScript checking before producing `dist`.
- `preview` serves the production build at `http://127.0.0.1:4173` with the same
  local API proxy. It is a local preview, not a production deployment server.

A deployed frontend needs history fallback to `index.html` for React Router
paths and a same-origin backend/reverse proxy. Keep the backend's cookie and
allowed-origin settings aligned with that deployment.

The interface uses system fonts, visible focus styles, a keyboard skip link,
semantic landmarks, live status announcements and reduced-motion support.
There are no remote font/CDN dependencies or UI component libraries.
