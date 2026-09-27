# Frontend · P1 organisation accounts

An **independent PanScience hackathon submission**, not an official PanScience
service. React, Vite, TypeScript, Tailwind and React Router provide registration,
sign-in, a protected organisation dashboard and local health diagnostics.

PDF uploads/indexing, grounded answers, decision models, assistant publishing,
public links, embedding and usage reporting are **not implemented in P1**.
Dashboard navigation opens explicitly labelled future-feature pages; there are
no fake metrics, upload controls or non-working publish links. Assistant tokens
are not requested or displayed.

## Local development

Use Node.js 22.14 or newer and npm. From this directory:

```powershell
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Start the backend separately using the repository's
instructions. Vite proxies `/api` to `http://127.0.0.1:8000`. All application
requests are same-origin; auth requests explicitly use `credentials: "same-origin"`.
The browser supplies the Origin header on POST requests; frontend code does not
fabricate an Origin or Authorization header.

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
| `/dashboard/knowledge-base` | Real account context; PDF features explicitly planned for P2. |
| `/dashboard/assistant` | Explicitly unimplemented publishing/chat state for P3–P5. |
| `/dashboard/usage` | Explicitly unimplemented usage reporting state for P5. |

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
  accepted as a usable session.
- The dashboard loads `GET /api/organizations/{current-organization-id}`. A
  mismatched organisation response is rejected; a verified unauthenticated
  response returns the visitor to sign-in. Other failures have a separate retry.
- `POST /api/auth/logout` accepts **204 without parsing JSON**, or an already
  unauthenticated response. Network, server and invalid-response failures remain
  visible and **do not clear the local session**; the sign-out button can retry.
- Requests time out after eight seconds, including body reading, and are
  cancelled when their owning view unmounts. HTTP failures preserve the backend
  error code, field errors and request reference.

## Form validation

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

## API contracts

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
  "phase": "P1",
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
  gateway, credentials or extra test framework is needed.
- `build` runs TypeScript checking before producing `dist`.
- `preview` serves the production build at `http://127.0.0.1:4173` with the same
  local API proxy. It is a local preview, not a production deployment server.

A deployed frontend needs history fallback to `index.html` for React Router
paths and a same-origin backend/reverse proxy. Keep the backend's cookie and
allowed-origin settings aligned with that deployment.

The interface uses system fonts, visible focus styles, a keyboard skip link,
semantic landmarks, live status announcements and reduced-motion support.
There are no remote font/CDN dependencies or UI component libraries.
