# Frontend · P0 foundation

React, Vite, TypeScript and Tailwind power a setup-only workspace. This phase
contains the responsive application shell and a real backend health check.
Accounts, PDF uploads, chat, decision features, routing and an embed widget are
**not implemented**.

## Local development

Use Node.js 22.14 or newer and npm. From this directory:

```powershell
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Start the backend separately using the repository's
instructions. Vite proxies `/api` to `http://127.0.0.1:8000`; the browser requests
the same-origin `GET /api/health`, not a separate cross-origin API.
The API documentation link opens `http://127.0.0.1:8000/docs` in a new tab.

No frontend environment file is needed. Gateway credentials and the gateway
address belong only in backend configuration, never in frontend source, forms,
browser storage or `VITE_*` environment variables.

## Health states

The page checks health on mount and offers a manual retry. Each request has an
eight-second timeout, including response-body reading, and is cancelled when the
component unmounts. Invalid JSON, unexpected contract fields, HTTP errors,
network errors and timeouts have explicit error states. A retry clears stale
health information.

The runtime validator expects:

```json
{
  "status": "ok",
  "service": "knowledge-decision-assistant",
  "version": "0.1.0",
  "phase": "P0",
  "gateway_configured": false
}
```

`gateway_configured: true` means **Configured, not verified**.
`gateway_configured: false` means **Setup needed**.
When the API cannot be checked, gateway configuration is **Not checked**, not
assumed to be absent. The health request never verifies gateway connectivity or
calls an LLM. Backend smoke tests are a separate step.

## Checks and build

```powershell
npm run typecheck
npm test
npm run build
npm run preview
```

- `typecheck` checks application code, Vite configuration and health tests.
- `test` uses Node's built-in test runner and TypeScript stripping; Node 22.14
  may print an experimental warning. All HTTP responses in these tests are
  mocked, so no backend or gateway requests are made.
- `build` runs TypeScript checking before producing `dist`.
- `preview` serves the production build at `http://127.0.0.1:4173` with the same
  local API proxy. It is a local preview, not a production deployment server.
  A deployed static build will need a same-origin backend or reverse proxy.

The interface uses system fonts, semantic landmarks, a keyboard skip link,
visible focus styles, live status announcements and reduced-motion support.
There are no remote font/CDN dependencies, UI libraries or routers.
