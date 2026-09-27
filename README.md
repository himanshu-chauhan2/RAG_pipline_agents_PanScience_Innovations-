# AI Knowledge & Decision Assistant

A multi-tenant, document-grounded assistant being built **one phase at a time**.
See the [implementation plan](start-reading-pdf-file-generic-fountain.md) for the full scope.

## Current state: P0 foundation

Implemented:
- React, Vite, TypeScript and Tailwind setup workspace with real API health checking,
  explicit failure states, retry, and responsive layouts.
- FastAPI health endpoint and typed backend configuration.
- OpenAI-compatible / Azure-style gateway client construction and opt-in typed-JSON smoke checks.
- CPU embedding and cross-encoder re-ranking smoke checks using FastEmbed.
- Six reproducible fictional policy PDFs, spread across two organisations and 13 pages.
- 23 held-out evaluation cases with expected facts, decisions and document/page references.
- Separate classifier datasets: 96 training examples and 24 validation examples.
- Offline tests, dependency lockfiles and VS Code tasks.

**Not implemented yet:** accounts, database tables, PDF-upload APIs, tenant-scoped
retrieval, the decision engine, chat, or embedding the assistant. The PDFs are
fixtures, not an ingested knowledge base. The classifier dataset is not yet a
trained classifier. The final live-answer evaluation belongs to later phases.

## Local setup (Windows / PowerShell)

Prerequisites: Python 3.12, `uv`, and Node.js 22.14+ with npm. Docker is not required.
Run these commands from the repository root:

```powershell
uv sync --project backend --locked
npm --prefix frontend ci
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
uv run --project backend python -m scripts.make_sample_pdfs
uv run --project backend python -m scripts.smoke_test --pdfs
```

Open [backend/.env.example](backend/.env.example) to see the configuration options,
then edit your local `backend\.env`. Enter the gateway URL and API key **locally**;
never put credentials in chat, source code, frontend configuration, screenshots,
or commits. Both values may remain blank while working on the local foundation.
The copy command above does not overwrite an existing local configuration.

### Start the application

Use **Tasks: Run Task** in VS Code:
1. `P0: backend dev`
2. `P0: frontend dev`

Alternatively, use two PowerShell terminals at the repository root:

```powershell
# Terminal 1
uv run --project backend uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2
npm --prefix frontend run dev
```

- Workspace: <http://127.0.0.1:5173/>
- API health: <http://127.0.0.1:8000/api/health>
- API documentation: <http://127.0.0.1:8000/docs>

Both servers bind to loopback. Vite proxies `/api` to the backend; gateway secrets
never reach the frontend. Stop these processes with their terminal's Ctrl+C or
VS Code's **Terminate Task** command. Restart the backend after editing its
configuration. Do not stop unrelated processes if a port is occupied.

## What the health check means

`GET /api/health` returns:

```json
{
  "status": "ok",
  "service": "knowledge-decision-assistant",
  "version": "0.1.0",
  "phase": "P0",
  "gateway_configured": false
}
```

`gateway_configured` reports the presence of the URL and key, **not** a successful
gateway connection. This endpoint never calls an LLM, loads local models, exposes
credentials, or claims that later product features work.

```mermaid
flowchart LR
    Browser[React setup workspace] --> Proxy[Vite API proxy]
    Proxy --> Health[FastAPI health endpoint]
    Smoke[Explicit smoke-test CLI] --> PDFs[PDF text and page checks]
    Smoke --> Models[Local CPU embeddings and re-ranker]
    Smoke -->|With cost approval| Gateway[Gateway typed JSON check]
```

## Stack smoke checks

### Local checks

```powershell
uv run --project backend python -m scripts.smoke_test --pdfs --local-models
```

The first local-model check downloads public ONNX model weights. Subsequent runs
reuse `backend\.cache\models`, which is ignored by Git. Document text is processed
locally; no document contents are sent to the model-download service.

The check verifies:
- Every generated page preserves its source paragraphs and expected page number.
- Embeddings have the supported dimension, finite values and nonzero norms.
- Relevant text ranks above unrelated text in both embedding similarity and
  cross-encoder scores.

Windows may warn that the Hugging Face cache cannot create symlinks. Downloads
still work using copies; administrator access is not required. Unauthenticated
public downloads can also emit a rate-limit advisory.

### Gateway checks (may incur charges)

After configuring the URL, key and model names locally, explicitly approve a run:

```powershell
uv run --project backend python -m scripts.smoke_test --gateway --allow-paid
```

This sends **one small synthetic request per distinct configured model**, covering
the fast, answer and fallback roles. It does not send PDFs, application code or
chat history. There are no automatic retries, model fallbacks, or silent response
format downgrades in this smoke test. Every failed selected check makes the
command exit nonzero. Errors omit response bodies, keys and gateway URLs.

| Setting | Purpose |
|---|---|
| `LLM_BASE_URL`, `LLM_API_KEY` | Server-side gateway connection; required for the gateway check |
| `LLM_FAST_MODEL`, `LLM_ANSWER_MODEL`, `LLM_FALLBACK_MODEL` | Gateway model or Azure deployment names |
| `LLM_API_STYLE` | `openai` (default) or `azure`; Azure also requires `LLM_API_VERSION` |
| `LLM_RESPONSE_MODE` | `json_schema` (default) or explicit `json` compatibility mode |
| `LLM_TOKEN_PARAMETER` | `max_completion_tokens` (default) or `max_tokens` |
| `LLM_MAX_OUTPUT_TOKENS`, `LLM_TIMEOUT_SECONDS` | Bounded output budget and request timeout |
| `EMBEDDING_MODEL`, `RERANKER_MODEL` | Supported FastEmbed model identifiers |
| `MODEL_THREADS`, `MODELS_CACHE_DIR` | Bounded CPU threads and backend-relative cache directory |

Both response modes are validated against a strict Pydantic schema. No temperature
parameter is sent. An invalid/incomplete completion fails rather than appearing
as a successful smoke check. The live P0 check verified OpenAI-compatible JSON
schema mode; Azure-style live connectivity has not been tested.

## Sample data

- [Policy source](sample_data/policies.yaml): three documents per organisation.
- [Generated PDFs](sample_data/pdfs): deterministic output, ready for later upload demos.
- [Evaluation cases](sample_data/test_questions.yaml): all six required question
  categories, multiple-condition decisions, scholarship exceptions, exact
  thresholds, clarification, comparisons and questions outside each tenant's knowledge.
- [Classifier examples](sample_data/classifier_examples.yaml): training and
  validation splits, checked for normalized duplicate questions against evaluation.

All organisations and policies are fictional demonstration data. PDF generation
checks the source text and explicit page boundaries; it does not silently let
content spill into an extra page. The page references in the evaluation fixtures
are validated against each organisation's own documents.

## Verification commands

Run from the repository root:

```powershell
uv run --project backend pytest backend\tests -q
uv run --project backend ruff check --config backend\pyproject.toml backend\app backend\tests scripts
uv run --project backend ruff format --check --config backend\pyproject.toml backend\app backend\tests scripts
npm --prefix frontend test
npm --prefix frontend run build
```

The backend gateway tests and frontend health tests use mocked HTTP transports.
They do not incur gateway charges. Frontend builds include TypeScript checking.
The `P0: frontend build` VS Code task runs the same build command.

P0 checkpoint verified on 27 September 2026:
- **33 backend tests** and **15 frontend tests** passed.
- Python lint/format checks and frontend TypeScript/production build passed.
- Six PDF fixtures and their 13 page references passed validation.
- Local CPU models produced 384-dimensional embeddings and correct relevant-text ordering.
- All three configured gateway roles returned validated typed JSON, one request each.
- The real browser/API integration, a simulated HTTP failure followed by retry,
  and desktop/mobile layouts (1440 px / 390 px) passed.

The current Starlette test client emits a non-blocking upstream deprecation warning
about its `httpx` transport; assertions still pass. Node's built-in TypeScript
stripping can emit an experimental warning on Node 22.

## Manual phase checkpoints

All staging, branch selection, commits and pushes are performed **manually by the
project owner**. P0 stops here for review; P1 starts only after the owner's go-ahead.
Suggested P0 message:

```text
chore: project setup, sample policies, smoke test
```

Do not include the local environment file, model cache, virtual environment,
uploads, databases, dependency-install directories, or the assignment PDF in a
commit. The repository ignore rules cover these paths while retaining sample
PDFs, environment placeholders and dependency lockfiles.
