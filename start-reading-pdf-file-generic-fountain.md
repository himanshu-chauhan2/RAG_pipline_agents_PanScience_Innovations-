# Plan — AI Knowledge & Decision Assistant (hackathon build)

## Context

The assignment PDF (`AI_Knowledge_Decision_Assistant_Assignment_5_Pages.pdf`) asks for a **multi-tenant SaaS MVP**:
- An organisation signs up and uploads up to 10 PDFs (≤ 20 pages, ≤ 10 MB each).
- It gets a **public assistant link and embed code**.
- Visitors ask questions and get answers **grounded in those PDFs with "Doc.pdf — Page N" references**.

The part that carries 55% of the grade: the **LLM must work with separate "System 1" decision models**.
- The LLM understands the question and writes the answer.
- Small, fast, deterministic models make the actual yes/no, which-one and how-much decisions.
- Our code combines those decisions.
- A single "question → LLM → answer" prompt is explicitly rejected (section 8).

**Goal:** ship in 2–3 days as a working GitHub repo with `.env.example`, sample data for 2 orgs, a README and a demo video. Work on **one phase at a time**: implement, verify, then hand over for your review and **manual commit**. Do not start the next phase until you approve proceeding.

**Current checkpoint:** you committed and pushed P0 (`c22d4df`). P1 is implemented and verified, ready for your review and manual commit. P2 has not started. The estimates below total roughly 27 hours and are targets, not a reason to skip validation.

**Your decisions so far:**
- **LLM:** OpenAI models via your gateway (URL + key in `.env`).
- **System 1:** local models + rule engine.
- **Frontend:** React + Vite + TS + Tailwind.
- **Orchestration:** plain async Python.
- **Clarification context:** bounded chat history kept in browser memory and resent with the question; no conversation database table.
- **Dashboard authentication:** HttpOnly-cookie JWTs backed by revocable server sessions, as selected for P1. Logout revokes only the current session; other devices remain signed in.
- **Submission context:** built for the PanScience Innovations hackathon. The assignment remains the requirements checklist; the company website informs product positioning, not invented internal policies or official affiliation.

**Environment:**
- **Repo:** `C:\Users\HimanshuChauhan\Desktop\RAG_with_agents` (origin `himanshu-chauhan2/RAG_pipline_agents_PanScience_Innovations-`).
- **Machine:** Windows 11, Python 3.12, Node 22, uv; no Docker.

---

## How it works, in plain words

Take one visitor question: *"I'm a 2nd-year student with a 3.6 GPA and I already have a sports scholarship. Can I get the merit scholarship?"*

| Step | What happens | Who does it |
|---|---|---|
| 1. Identify org | Validate the assistant token and bounded chat context; resolve the organisation server-side | App logic |
| 2. Classify | Predict `eligibility` with a confidence score. Low confidence or an `out_of_scope` prediction alone must not cause a refusal | **System 1: Classification** (small trained model, local) |
| 3. Understand | Pull facts from the current question and chat context (`year=2, gpa=3.6, scholarship_types=["sports"]`) and create searches ("merit eligibility", "combining scholarships") | **LLM** (fast model) |
| 4. Find evidence | Search only this org's chunks and rank them by relevance | **System 1: Score** (local re-ranker) |
| 5. Select policy, then read its rules | Select *Merit*, then extract its supported rules: year >= 2, GPA >= 3.5, and no stacking except need-based scholarships. Preserve logical groups and exceptions, with source quotes | **System 1: Choice**, then **LLM** extraction and app validation |
| 6. Evaluate independent conditions | After policy/rule validation: ✅ year, ✅ GPA, ❌ sports scholarship is not an allowed stacking exception. Only independent checks may run concurrently | **System 1: Boolean** (rule engine, no LLM) |
| 7. Combine | Evaluate the rule tree. This supported ALL group is false → **Not eligible**. Missing facts, insufficient evidence and conflicting policies have different outcomes | App logic |
| 8. Answer | Render the authoritative verdict from application data; have the LLM explain it using supported claims and source spans | App logic + **LLM** (answer model) |
| 9. Validate answer and references | Check claims, verdict consistency, source spans and tenant-scoped citations. Repair an invalid answer once or return an explicit non-answer; never just strip bad citations | App logic |

The chat widget shows a collapsible **"How I decided"** panel with steps 2–7: structured inputs, source-backed rules, outputs and timings, **not private chain-of-thought**.

**Fresh, high-confidence simple questions** such as "When is the application deadline?" skip steps 3, 5, 6 and 7 and normally make **one** LLM call. If retrieval finds no good evidence on this path, there are **zero** LLM calls. Complex questions and any request with history go through contextual understanding first; normally this has used **one** LLM call before retrieval. Missing evidence then stops rule extraction and answer generation. Retry, fallback and output-repair calls are additional and must be logged.

---

## Shared contracts and correctness rules

### Chat context and response states
- `POST /api/ask` accepts `{token, question, history?}`. History contains only `{role: "user" | "assistant", content}` messages; omitted history means a new question.
- MVP limits: current question 1–2,000 characters after trimming; at most 8 history messages and 8,000 history characters. Reject malformed or oversized input with a clear 400 error.
- Keep the original question and subsequent turns in memory for the current assistant token. Clear them on **New chat**, token change or page reload. At the limit, ask the visitor to start a new question including the relevant facts; do not silently drop context.
- A follow-up such as "3.6" includes the original question and the assistant's GPA clarification. Any non-empty history forces contextual understanding before retrieval/routing, even if the short reply looks like a simple question to the classifier. Treat all supplied history as **untrusted conversation data**, not instructions or authoritative rules, verdicts or citations. Re-retrieve evidence and recompute decisions on every request. Conflicting user facts require clarification.
- Resolve the organisation from the validated token on every request. History cannot select a tenant, grant access, or supply trusted document IDs.
- Successful processing returns a typed outcome: `answered`, `needs_info`, `insufficient_evidence`, or `needs_review`. Eligibility verdicts (`eligible` / `not_eligible`) exist only for supported, conclusive decisions.
- Processing failures use a non-2xx error response with a stable code, meaningful message and request ID. A model failure is **not** a knowledge-base miss or an answered question.

### Rule and answer validation
- Use a typed rule tree: non-empty `all` / `any` groups, unary `not`, and predicates with a field, allowed operator, typed value and source evidence. Start with equality, comparisons, membership and set-subset checks; reject unsupported expressions.
- Each applicable condition, group and exception needs supporting `{chunk_id, quote}` evidence. Validate tenant/document/page ownership, quote spans, operators, values, units and applicability. Never execute model-generated code.
- Quote existence is necessary but **does not prove the extracted meaning is correct**. Test extraction against human-authored expected trees, including inverted operators, changed thresholds and omitted exceptions. Ambiguous or unsupported policy interpretation must abstain.
- Example: `ALL(year >= 2, gpa >= 3.5, scholarship_types subset_of ["need_based"])`. An explicitly empty scholarship list means none; a missing list is unknown, not an empty default.
- First require a supported, non-empty rule set for the selected policy. Missing/unverified rules or weak support → `insufficient_evidence`; conflicting policy evidence → `needs_review`; ambiguous policy selection → `needs_info`.
- Malformed model output and runtime failures use the error contract, not an unknown rule result or a knowledge-base miss.
- For a valid tree, use three-valued logic: ALL is false if any child is false and true only if all are true; ANY is true if any child is true and false only if all are false; otherwise the result is unknown. NOT preserves unknown. Unresolved user facts → `needs_info` only when they prevent a conclusive result.
- Answer generation returns structured statements with supporting source spans. Render decision verdicts and evaluated conditions from application data, not an LLM-selected verdict. For factual details, prefer verified source quotations over an unchecked paraphrase.
- Validate factual claims against their cited evidence, especially entities, numbers, deadlines, thresholds and exceptions. A retrieved chunk ID alone is not a grounding check. Allow one repair attempt for an invalid answer. Return `insufficient_evidence` only when the required support is genuinely absent; persistent malformed, unsupported or contradictory generation despite available evidence is an explicit generation error (502).
- Do not leave unsupported claims visible after removing their citations. Test semantic correctness with known expected answers and review the demo answers; document that automated checks are not a general proof of semantic entailment.

---

## Libraries — and why each one

### Backend (Python, managed with `uv`)
| Library | Why | Why not the alternative |
|---|---|---|
| **fastapi** + uvicorn | Async web API with typed Pydantic requests and decisions, plus generated `/docs`. Offload blocking model inference to a bounded worker/thread pool; async alone does not parallelise CPU work | Flask would need additional API validation conventions |
| **sqlalchemy** + **SQLite** | Database in one file with nothing to install. ORM models keep a later Postgres migration manageable; a driver, configuration and migration testing will still be needed | Postgres needs an install or Docker |
| **pydantic-settings** | Reads `.env` into typed config (gateway URL, key, model names, limits) | Scattered `os.environ` calls |
| **bcrypt** | Password hashing | passlib: unmaintained, breaks with new bcrypt |
| **pyjwt** | Signed admin JWT in an HttpOnly cookie, backed by a revocable database session | — |
| **email-validator** | Validates email addresses through Pydantic; canonical email uniqueness is enforced by the database | Avoid a hand-written email regex |
| **python-multipart** | FastAPI needs it for file uploads | — |
| **pypdf** | Reads PDFs **page by page**, so every chunk keeps its page number for references. Also counts pages and detects encryption. Pure Python | PyMuPDF: AGPL licence |
| **fastembed** | Runs two small models **locally on CPU**: embeddings (`bge-small-en`) for search, and a cross-encoder re-ranker for Score/Choice. No PyTorch (saves ~2 GB) and no extra API cost | sentence-transformers pulls in PyTorch |
| **numpy** | Similarity search over at most ~1,000 chunks per org, which takes milliseconds | A vector DB is overkill at this size |
| **scikit-learn** | Trains the question-type **classifier** (logistic regression) on ~100 example questions, with separate validation and held-out evaluation data | — |
| **openai** (official SDK) | Talks to your gateway via `base_url`. Async, with retries and timeouts. `parse(response_format=PydanticModel)` returns **typed JSON** instead of free text | Raw HTTP: more code, no typing |
| dev: pytest, httpx, ruff | Tests and linting | — |
| dev: reportlab, pyyaml | Generates the sample PDFs from text; reads the test-question list | — |

### Frontend
| Library | Why |
|---|---|
| **React + Vite + TypeScript** | Fast dev server with an API proxy; types catch API mismatches |
| **react-router-dom** | Pages: login, register, dashboard, and the public chat at `/a/:token` |
| **Tailwind CSS** | A clean UI quickly, without a heavy component library (the chat runs inside an iframe, so it must stay small) |
| **embed.js** (our own ~50 lines, no deps) | Pasted into any website, it adds a chat bubble that opens our chat page in an iframe |

**Deliberately not used**, and the reason given in the README:
- LangChain / LangGraph: extra abstraction hides the pipeline stages the graders want to see.
- A vector database: too small a dataset to need one.
- Cloud embeddings: extra cost and latency.

### LLM configuration (all in `backend/.env`, which is gitignored)
```
LLM_BASE_URL=<your gateway URL>
LLM_API_KEY=<your key>
LLM_FAST_MODEL=gpt-5.6-luna      # understanding + rule extraction: fast, cheap, many calls
LLM_ANSWER_MODEL=gpt-5.6-terra   # final answer: balanced quality and speed
LLM_FALLBACK_MODEL=gpt-5.1       # used once if the main model errors
```
- I create `backend/.env` with empty values, and **you paste the URL and key yourself**, so the key never appears in chat or git. Only `.env.example` (placeholders) gets committed.
- Model names are configurable. You can switch the answer model to `gpt-5.6-sol` for demo day with no code change.
- **P0 smoke test confirms how your gateway behaves:**
  - Does it accept `chat.completions` with a JSON schema?
  - Which parameters does it take (`max_completion_tokens` vs `temperature`)?
  - Is it plain OpenAI-compatible or Azure-style?

  If JSON-schema mode isn't supported, we fall back to JSON mode plus Pydantic validation, controlled by one setting.
- Validate every model response. Use bounded retries/fallback for documented failure cases, record attempts and call counts, and surface exhausted failures explicitly.

---

## Project layout
```
backend/app/
  main.py  config.py  db.py  models.py
  auth/            register, login, JWT, current-org dependency
  kb/              upload + validation, PDF → page chunks → embeddings, list/delete/replace
  retrieval/       embed query → top-20 by similarity (this org only) → re-rank → top-5
  decisions/       classifier.py  rules.py (Boolean engine)  choice.py  score.py  combiner.py
  llm/             client.py (gateway wrapper)  understand.py  extract_rules.py  answer.py
  ask/             pipeline.py — runs steps 1–9, builds the "How I decided" trace, logs usage
  api/             routes: /api/auth/*, /api/documents/*, /api/assistant/*, /api/usage, /api/ask
backend/tests/     test_auth, test_upload_limits, test_retrieval, test_decisions, test_ask, test_chat_context, test_tenant_isolation
frontend/src/      pages (Login, Register, Dashboard, Chat) · components · api client
frontend/public/embed.js
demo/external-site.html          a fake "university website" that embeds the assistant
sample_data/                     policy texts → PDFs for 2 orgs · classifier_examples.yaml · test_questions.yaml
scripts/                         smoke_test.py · make_sample_pdfs.py · seed_demo.py · run_eval.py
```

**Database tables (7; 4 introduced in P1):**
- `organizations`, `users`, `assistants` (org_id, token).
- `auth_sessions` (user_id, expiry, revoked_at); the user relation resolves the organisation. This table is the intentional addition for reliable per-session logout.
- `documents` (org_id, name, pages, size, status, error), `chunks` (org_id, document_id, page, text, embedding).
- `question_logs` (org_id, question, type, status, error_code, latency, llm_call_count).

Every tenant-resource query filters by the verified `org_id`, resolved from the admin session or assistant token, **never from a caller-supplied organisation field**. Login performs a canonical-email lookup before tenant resolution; only a verified password and matching server session can expose the resulting account.
Chat history stays in browser memory; no conversation table is needed for this MVP. Store outcome/error metadata for usage counts; do not log credentials or private reasoning.

---

## Phase-by-phase delivery and commits

**Planning checkpoint:** the revised plan is approved for implementation. You decide whether to commit the plan separately or with P0. The assistant must not stage, commit, switch/create branches, amend, merge or push; all Git write operations remain manual.

**Implementation sequence: P0 → P1 → P2 → P3 → P4 → P5 → P6, one commit per phase.**

**Checkpoint at the end of every phase, without exceptions:**
1. Implement only that phase and its directly related tests/documentation.
2. Run the relevant checks: targeted backend tests and lint, frontend build/type-check when frontend changes, and a browser click-through for changed UI. P6 runs the full release checks.
3. Fix failures before calling the phase complete. Show you what works, the checks/results, the exact files changed, and any libraries added with their reasons.
4. **Stop for your review and manual commit.** Address your feedback in the same phase; do not bundle unfinished or later phases into the handoff.
5. Provide the reviewed file list, validation results, outstanding blockers and suggested commit message. You choose the branch and perform staging/committing yourself.
6. **Wait for your go-ahead before starting the next phase.** The assistant performs no Git write operations; it never commits or pushes on your behalf.

| Phase | Deliverable | Depends on |
|---|---|---|
| P0 | Stack smoke test, skeleton and test-data contracts | Plan approved; start authorised |
| P1 | Organisation accounts and dashboard shell | P0 verified and committed |
| P2 | PDF management and tenant-scoped indexing | P1 verified and committed |
| P3 | Grounded Ask API, response states and isolation | P2 verified and committed |
| P4 | Structured decisions, comparisons and clarification processing | P3 verified and committed |
| P5 | Public chat, embedding and usage UI | P4 verified and committed |
| P6 | Evaluation, packaging, documentation and demo | P5 verified and committed |

### P0 — Setup & smoke test · ~2 h
- **Status:** implemented, verified, and manually committed/pushed as `c22d4df`.
- Backend skeleton (`/api/health`), frontend skeleton, `.env.example`, `.gitignore` (`.env`, models, DB, uploads, the assignment PDF).
- **`scripts/smoke_test.py`** answers "will our stack work on this machine and gateway?" before we build on it:
  - one gateway call per model, with a typed JSON response
  - local embedding and re-ranker model download and run (catches corporate-proxy SSL problems early)
  - pypdf reads a PDF
- **Sample data written first, because it defines what the decision engine must handle:**
  - **Northbridge University:**
    - Scholarship Rules: merit needs year ≥ 2 and GPA ≥ 3.5, no stacking with other scholarships except need-based, GPA tiers.
    - Exam Re-evaluation Procedure: steps and deadlines.
    - Hostel Policy.
  - **Acme Logistics:**
    - Remote Work Policy: tenure ≥ 6 months, rating ≥ 3, role not on-site.
    - Leave Policy.
    - Travel Reimbursement: approval needed above $500.
  - `classifier_examples.yaml` with distinct training/validation splits; do not train or tune thresholds on the final evaluation questions.
  - `test_questions.yaml` with 15+ held-out cases covering direct information, policy, procedural, multi-condition decision, comparison and no-answer questions.
  - Include **at least 2 multi-condition questions**, **at least 1 question requiring multiple structured decisions**, and **at least 1 missing-answer question**, as required by section 18.
  - Define each case's expected outcome, applicable verdict, required facts/claims, expected document/page references and prohibited claims. Multi-turn cases include the history and expected missing fields.
- **Acceptance:** health endpoint and frontend load; local embedding/re-ranking and PDF extraction work; approved gateway smoke calls pass; generated PDFs have stable, known page references; test-data coverage is checked.
- *You'll need to:* paste the gateway URL and key into `backend/.env`.
- Real gateway smoke/evaluation runs require your approval; ordinary development tests use fakes.
- **Verified checkpoint:** 33 backend tests, 15 frontend tests, Python lint/format and frontend build/type-check pass. Six reproducible PDFs (13 pages), 23 held-out cases and 96/24 classifier train/validation examples are checked. CPU embedding/re-ranking smoke checks and your approved single-request checks for all three gateway roles pass. Browser health, failure/retry and desktop/mobile layouts are verified.
- P0 adds only the dependencies needed for this foundation; SQLAlchemy, auth libraries, the trained classifier and later feature packages remain for their respective phases.
- *Commit:* `chore: project setup, sample policies, smoke test`

### P1 — Organisation accounts · ~3 h
- **Status:** implemented and verified on 27 September 2026; awaiting your manual commit and go-ahead for P2.
- Register (creates the org, the admin user and the assistant token), login, logout.
- SQLite persists organisations, users, assistant tokens and revocable admin sessions. Registration is atomic; the database enforces one account per canonical email.
- Passwords use bcrypt with an 8-character minimum and a 72-UTF-8-byte maximum. Password whitespace is preserved; blank passwords are rejected.
- Admin JWTs have a fixed algorithm, issuer, audience, expiry, session ID and token type. The API also validates session ownership, expiry and revocation in the database. Assistant tokens cannot authenticate admin requests.
- Cookies are HttpOnly, SameSite=Lax and scoped to `/api`; HTTPS deployments must enable Secure cookies. Browser state contains account details, never the JWT. Sessions survive reload/restart and expire after 8 hours by default.
- Account-changing requests require an explicitly allowed Origin. Validation errors contain safe field messages and a request ID, never the submitted password.
- A random signing key is generated once in the ignored local data directory unless `AUTH_SECRET_KEY` is configured. Existing keys and databases are not overwritten.
- APIs: register/login/logout/current account, plus an authenticated own-organisation endpoint; foreign or unknown organisation IDs return 404.
- Dashboard shell with tabs: Knowledge Base / Assistant / Usage.
- Tests: wrong password → 401; no login → 401; **org A's login cannot see org B's data (404)**.
- **Acceptance:** register/login/logout work in the browser; the assistant token is separate from admin credentials; authentication and organisation-isolation tests pass.
- **Verified checkpoint:** 84 backend tests and 55 frontend tests pass, along with lint/format and the TypeScript/production build. Browser registration, login/logout, wrong-password feedback, session reload persistence, protected routes, all dashboard tabs, failure/retry states and desktop/mobile layout checks pass. Cookie flags and tenant-scoped account access are verified; no live LLM calls were made.
- *Commit:* `feat(auth): organisation registration, login, dashboard shell`

### P2 — Knowledge base · ~4 h
- **Upload checks, each with a clear message:**
  - is it a real PDF
  - ≤ 10 MB, defined as 10,000,000 bytes
  - not password-protected
  - ≤ 20 pages
  - fewer than 10 docs already
  - has readable text (scanned image PDFs get an error)
- **Processing:** split each page into ~800-character chunks (a chunk never spans two pages) → embed locally → status *Processing → Ready / Failed*.
- Dashboard: document table, a "7 / 10 documents used" meter, and delete / replace.
- Files are stored under random names in a private folder, with no public download.
- Processing/embedding failures leave an explicit Failed state and a useful message, not a partially searchable document. Deletion/replacement invalidates the old chunks and any retrieval cache.
- **Acceptance:** exact 10-document / 20-page / 10-MB boundaries pass and values above them fail; invalid/encrypted/scanned PDFs have clear errors; only Ready documents are searchable; delete and re-upload work at the document limit.
- *Commit:* `feat(kb): PDF upload with limits, page-aware chunking, local embeddings`

### P3 — Ask API with grounded answers · ~4 h
- Implement the shared `POST /api/ask {token, question, history?}` contract and response states. P3 delivers the direct-answer path; P4 adds clarification interpretation and decision routing.
  1. Validate token, question and history; resolve org.
  2. Retrieve from Ready documents in this org only, then re-rank.
  3. **Gate:** insufficient support → `insufficient_evidence` with a clear knowledge-base message. The fresh simple-question path makes no LLM call here.
  4. Generate structured source-backed statements.
  5. Apply the shared grounding/repair contract and build verified "Doc — Page" references.
- Errors: invalid token (401), invalid/empty/oversized input (400), unavailable model service (503), invalid model output after bounded repair (502), timeout (504).
- Retrieval, embedding, re-ranker and LLM failures have distinct logged error codes and meaningful messages. Optional matching snippets are labelled **source excerpts, not a generated answer**, and never turn a processing error into success.
- Dashboard: see the assistant URL, **regenerate the token** (the old link stops working).
- **Tenant isolation tests (required by section 11):**
  - org B's assistant never answers from org A's PDFs
  - an assistant token cannot call admin APIs
  - an old token after regeneration → 401
  - a deleted document disappears from answers
  - forged history, document IDs or citations cannot retrieve another org's content
- **Acceptance:** expected factual answers cite the correct documents/pages; unsupported claims and fake citations do not survive validation; no-answer call counts, repair limits, input validation, model-failure responses and tenant-isolation tests pass.
- *Commit:* `feat(ask): grounded answers with page references and tenant isolation tests`

### P4 — Decision engine: LLM + System 1 · ~6 h (the most important phase)
- **Classification:** train a logistic-regression model on question embeddings and evaluate on held-out data. Fresh, high-confidence simple questions use P3; eligibility/comparison use the relevant structured path. Every request with history goes through contextual understanding before retrieval/routing. Low confidence or `out_of_scope` triggers evidence-aware understanding/clarification, not automatic refusal. A classifier runtime failure is an explicit error, not a low-confidence prediction.
- **LLM "understand":** sees the current question and bounded conversation data, not trusted prior answers. Return typed intent, user facts with their originating message spans, missing/ambiguous facts and search sub-queries. A follow-up is resolved against the original question.
- **Choice, before rule evaluation:** use retrieved evidence to select the relevant programme/policy. Close candidates → `needs_info` asking which one. Never combine one policy's conditions with another's.
- **LLM "extract rules":** sees the selected policy's retrieved text and returns the shared typed rule tree with evidence. Validate applicability, condition groups, exceptions and typed predicates before execution. Do not reuse rules or citations supplied in chat history.
- **Boolean:** evaluate the supported tree deterministically with true / false / unknown and explicit unknown reasons. Missing facts are different from missing policy evidence.
- **Score:** use local relevance/evidence scores to gate support, not as a probability that someone is eligible. Compute per-decision support only when its policy/evidence inputs are available.
- **Execution order:** understand → retrieve/rank → choose policy → extract/validate rules → evaluate independent conditions → combine → generate/validate answer. Comparisons branch per entity. `asyncio.gather` is only for independent async tasks; offload blocking model inference to a bounded worker/thread pool. Cheap Boolean predicates can execute directly; do not claim CPU parallelism from async syntax.
- **Combiner:** apply the shared ALL/ANY/NOT truth tables and outcome precedence. Never return Eligible for an empty, unverified or unsupported rule set. Return named missing facts for `needs_info`; conflicting evidence uses `needs_review`, not a user-fact question.
- **Comparison questions are mandatory:** retrieve and keep evidence separate per entity; return supported side-by-side rows with references for each side. Explicitly identify missing information rather than inventing a comparison or applying eligibility's ALL combiner across entities.
- The response includes an application-generated `decision_trace` with structured inputs, source-backed rules, outputs, dependency order and timings. Exclude private chain-of-thought.
- Unit tests cover rule trees, type/operator guards, quote/meaning mismatches, exceptions, missing facts, empty rule sets, conflicting evidence, policy ambiguity, ordering, classifier/re-ranker/decision-engine failures and verdict-consistent output.
- **Acceptance:** merit + sports → Not eligible; allowed need-based stacking can pass; missing GPA can produce `needs_info` and a contextual "3.6" reply recomputes the outcome; comparisons cite both entities. Ordinary tests run without the network using fake LLM/model outputs; live extraction is separately checked against expected trees in the approved evaluation.
- *Commit:* `feat(decisions): structured rules, comparisons, contextual clarification`

### P5 — Chat widget, embed & usage · ~4 h
- **Public chat page `/a/:token`:** messages, loading state, reference chips, verdict badges for supported decisions, a collapsible **"How I decided"** panel, and distinct Need info / Insufficient evidence / Needs review / Processing error states.
- Implement browser-memory history, **New chat**, token-change clearing and the shared context limits. Follow-up replies resend the original question and prior turns; do not silently lose facts when the context fills.
- **Assistant tab:** copy the link, copy the iframe code, copy the `<script>` embed code, regenerate the token.
- `demo/external-site.html` embeds the assistant from a different port, proving it works on third-party sites.
- **Usage tab:** questions asked / answered / couldn't answer / needs info / needs human review / processing errors, plus recent questions. Each accepted question attempt increments asked and exactly one outcome bucket; no-answer and error states must not increment answered.
- **Security headers:** only the chat page may be framed; the dashboard cannot. There is also a basic per-token rate limit on `/api/ask`.
- **Acceptance:** complete a missing-GPA clarification in the browser, test context-limit/reset behaviour, copy both supported embed formats, load the iframe on the external page, rotate the token, and verify the UI and usage counts distinguish non-answers from failures.
- *Commit:* `feat(widget): public chat, embed code, usage dashboard`

### P6 — Ship it · ~4 h
- **One command runs everything:** FastAPI serves the built frontend. Start scripts are `start.ps1` for Windows and `start.sh`.
- `scripts/seed_demo.py` creates both demo orgs, uploads their PDFs and prints their assistant links.
- `scripts/run_eval.py` runs the held-out test questions using the scoring contract below and writes `docs/eval_report.md`: per-case expectations/results, pass/fail reasons, category totals, timings and LLM call counts. It makes real gateway calls, so **I ask you before each run**.
- **README:**
  - setup in 5 commands
  - architecture diagram (mermaid)
  - how PDFs are processed
  - how LLM + System 1 work together (the table above)
  - rule semantics, clarification limits, outcome/error states and fail-safe behaviour
  - evaluation method, held-out data and results
  - security and isolation
  - API endpoints
  - limitations and what we'd do next
- `docs/demo_script.md`: a minute-by-minute outline for your 8–15 min video.
- Record the actual demo and add its link before submission. Show the end-to-end product flow, both isolated orgs, a multi-decision trace, clarification, comparison and missing knowledge; explain data flow, not private reasoning.
- *Optional, only if time is left:* a Dockerfile and deploy notes for Render or Railway. This can't be tested locally because the machine has no Docker.
- **Acceptance:** clean documented setup works; full automated checks and approved live evaluation meet the release gates; the embedded flow works for both orgs; README, evaluation report and actual demo link are ready.
- *Commit:* `docs: README, eval report, demo script; chore: one-command start`

**If we fall behind, cut in this order:** the script embed (keep the iframe) → dedicated replace-document UI (keep delete + re-upload within limits) → the recent-questions list → advanced Choice/Score presentation beyond the core decision demonstration.
**Never cut:** any mandatory question category, including comparison; at least two meaningful structured decision types (Classification + Boolean at minimum); correct policy selection and evidence gates; the decision trace; grounded references; isolation and failure tests; the no-answer path; the README diagram; or the actual demo video. Record any agreed scope cut at that phase's checkpoint.

---

## Verification
- **At each phase checkpoint:**
  - Run `uv run ruff check .` plus focused pytest selectors from `backend\`; for example, `uv run pytest tests\test_decisions.py tests\test_ask.py tests\test_chat_context.py` for P4.
  - Run `npm run build` from `frontend\` when the frontend changes; ensure it includes TypeScript checking.
  - Click through the changed UI in the browser preview; include a screenshot when useful.
  - Documentation-only updates need no application test run. Record checks that are not yet available instead of claiming they passed.
- **Release:** full backend tests/lint, frontend build/type-check, browser end-to-end checks and approved gateway evaluation.
- **Isolation:** `test_tenant_isolation.py` green. In the demo, ask the Acme assistant a scholarship question and it answers "not in the knowledge base".
- **Upload boundaries:** test 10 vs 11 documents, 20 vs 21 pages and 10,000,000 vs 10,000,001 bytes. Include invalid PDFs and document-processing failures.
- **Rule boundaries:** GPA 3.49 / 3.50 / 3.51, first vs second year, none / need-based / sports / mixed scholarships, missing vs explicitly empty facts, ALL/ANY/NOT with unknowns, empty trees, missing exceptions and unsupported rules.
- **Failure and grounding:** inject classifier, embedding, re-ranker, decision-engine, LLM and processing failures; assert explicit errors and correct usage buckets. Verify wrong-document/page citations, altered quotes, unsupported claims and an LLM verdict contradicting the engine cannot be returned as successful answers.
- **Call counts, without retries/repairs:** fresh, high-confidence simple question with no evidence → 0 LLM calls; complex/contextual question with no evidence after successful understanding → 1; no subsequent rule/answer calls. Test retry/repair/fallback bounds separately.
- **Context:** multi-turn clarification preserves facts, asks about conflicts, enforces limits, clears on reset/token change, and cannot override tenant identity or inject trusted policy/decision data.
- **End-to-end:**
  1. Run `seed_demo.py`.
  2. Open `demo/external-site.html`.
  3. Ask the scholarship question above.
  4. Expected: **Not eligible**, with policy selection before the three independent condition results, an explicit sports-stacking failure, evidence-support scores, and the expected "Scholarship_Rules.pdf — Page N" reference.
  5. Ask without GPA, supply "3.6" when requested, and verify the original facts remain in the recomputed result. Use an otherwise eligible example so missing GPA actually prevents a conclusive answer.
  6. Compare two supported options with references for both, then ask a missing-answer question and repeat the isolation demo for the second org.
- **Evaluation scoring:**
  - Each of the 15+ held-out cases names its category, org, question/history, expected outcome/verdict, required claims or rule outcomes, exact expected document/page references, missing fields and forbidden claims where applicable.
  - A case passes only if **all applicable assertions pass**. Compare structured outcomes and supported facts, not exact wording or an LLM's self-assigned grade.
  - Assert the required coverage counts, including 2 multi-condition cases and 1 multi-structured-decision case. Report comparison and no-answer results separately so a high aggregate score cannot hide a missing category.
  - Overall gate: `passed / total >= 0.90`, rounding the required pass count up. With 15 cases, at least **14 must pass**. No skipped/failed calls may be removed from the denominator.
  - Regardless of the aggregate score, **all designated mandatory demo cases and all isolation, upload-limit, failure-state, decision-safety and grounding regression tests must pass**. A leak or unsupported eligibility verdict blocks release.
  - Fix training randomness for reproducibility. Keep classifier training/threshold-tuning data disjoint from the final evaluation set; if evaluation cases inform tuning, report that and add fresh held-out cases.
