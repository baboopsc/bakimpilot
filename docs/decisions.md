# Decision log

Each entry: **what** we decided, the **alternatives** we looked at, and **why**.
Newest entries at the bottom. IDs are referenced from code comments (e.g. `D-005`).

---

## D-001 — One repository with `backend/` and `frontend/` folders (monorepo)
- **Alternatives:** separate repos for API and web app.
- **Why:** one person, one project. A single repo means one CI pipeline, one
  `docker-compose.yml`, and API + UI changes land in the same commit, so they
  can't drift apart.

## D-002 — PostgreSQL everywhere, including tests
- **Alternatives:** SQLite for tests (faster to set up), MySQL.
- **Why:** the RAG assistant needs `pgvector`, which only exists in Postgres.
  Running tests on the same database as production means the constraints,
  locking (`SELECT … FOR UPDATE`) and query behaviour we test are the real ones.
  The cost is that tests need a running Postgres (Docker locally, a service
  container in CI).

## D-003 — Configuration from environment variables (`django-environ`)
- **Alternatives:** separate `settings_dev.py` / `settings_prod.py` files.
- **Why:** the same code runs on a laptop, in CI and in production; only env vars
  change (the "12-factor" approach). Secrets never live in git; `.env.example`
  documents what exists.

## D-004 — Custom `User` model with one `role` field
- **Alternatives:** Django's built-in Groups + Permissions; a separate Profile table.
- **Why:** Django recommends a custom user model from day one because swapping
  later is painful. We have exactly four fixed roles, and a user has one role,
  so a single `role` column is simpler to reason about and to test than
  per-model permission rows. If roles ever became configurable, Groups would be
  the upgrade path.

## D-005 — JWT: access token in memory, refresh token in an httpOnly cookie
- **Alternatives:** both tokens in `localStorage`; classic Django session cookies.
- **Why:** `localStorage` can be read by any injected script (XSS), so a stolen
  refresh token gives a week of access. With an httpOnly cookie, JavaScript can't
  read the refresh token at all. The access token lives only in memory and
  expires after 15 minutes. Refresh tokens are **rotated** on every use and
  **blacklisted** on logout, so a replayed old token is rejected (there's a test
  for this). The cookie is `SameSite=Strict` and scoped to `/api/auth/`, so it's
  only sent to the auth endpoints. Even a forged cross-site refresh request
  can't read the new access token, because of CORS.
  JWT was a requirement of the brief, and it keeps the API usable by non-browser
  clients (e.g. a flight-data ingestion service).

## D-006 — Role-based permissions: everyone reads, writes are opt-in per view, fail closed
- **Alternatives:** check roles inside each view method; object-level permissions.
- **Why:** one permission class (`RoleBasedPermission`) is the default for every
  endpoint. Reading needs a login; writing needs a role the view lists in
  `write_roles` / `action_roles`. If a developer forgets to configure a view,
  only ADMIN/PLANNER can write. A missing setting can't accidentally let a
  VIEWER change data.

  | Role | Can do |
  |---|---|
  | ADMIN | everything, including user management |
  | PLANNER | fleet, components, rules, flight logs, work orders, inventory |
  | TECHNICIAN | work on assigned work orders (checklist, parts, sign-off) |
  | VIEWER | read only |

## D-007 — Business logic lives in `services.py` functions
- **Alternatives:** "fat models", logic in serializers/views, Django signals.
- **Why:** rules like "a flight adds hours to every installed component" must run
  the same way from the API, the admin, a Celery task or a test. Plain functions
  with `transaction.atomic()` are easy to read, call and unit-test. Signals were
  rejected because they hide side effects: you can't see from the calling code
  what happens.

## D-008 — Append-only audit log, written explicitly
- **Alternatives:** `django-simple-history` / `django-auditlog` (automatic row
  versioning); database triggers.
- **Why:** in aviation maintenance, "who signed off this task and when" is a
  regulatory record. The useful unit is a *business event* ("work order signed
  off"), not a raw row diff. Each service function writes its audit entry inside
  the same transaction as the change, so you can't have one without the other.
  The model refuses updates and deletes, and the API only exposes it read-only.
  (A production system would also revoke UPDATE/DELETE grants at DB level.)

## D-009 — Django 5.2 LTS + Django REST Framework
- **Alternatives:** Django 6.0 (newer, shorter support); FastAPI.
- **Why:** 5.2 is the Long-Term-Support release (security fixes until 2028),
  which is what an internal enterprise system should run. Django's admin, ORM,
  migrations and auth come built in. FastAPI would mean assembling those pieces
  ourselves.

## D-010 — `PartType` (catalog) separate from `Component` (serialized unit)
- **Alternatives:** one `Component` table that repeats the life limits on every row.
- **Why:** the manufacturer sets life limits per **part number**, not per unit.
  Storing them once on `PartType` means 20 engines share one definition, and
  changing a limit (e.g. after a service bulletin) is a single update. Each
  `Component` holds only what is unique to it: serial number, manufacture date,
  usage. Three independent limits (hours, cycles, days), each optional, because
  real parts are limited differently. A battery ages by calendar time, landing
  gear by cycles, an engine by hours.

## D-011 — Running hour/cycle totals are stored (denormalised) and verifiable
- **Alternatives:** compute usage on every read by summing flight logs over the
  component's install periods.
- **Why:** usage is read constantly (due list, dashboard, every component page)
  but changes only when a flight is logged. Summing history on every read gets
  slower as the fleet grows. So `log_flight` updates the totals once, inside
  a transaction, with `F()` expressions (the DB does `x = x + n`, so no lost updates).
  To protect against the classic risk of denormalised data (drift), the
  totals can always be **rebuilt from first principles**:
  `expected_component_usage()` and the `verify_counters` management command. A
  test proves they agree. The aircraft row is locked with `SELECT … FOR UPDATE`
  during a flight insert, so concurrent inserts for the same aircraft run one at
  a time; another test fires 8 parallel threads and checks nothing is lost.

## D-012 — Install history as time intervals, with DB-enforced integrity
- **Alternatives:** a single `current_aircraft` foreign key on `Component`.
- **Why:** a foreign key only tells you where a part is *now*. Maintenance needs
  *where it was then*: a back-dated flight must credit the components that were
  installed at take-off time, and an investigator asks "which aircraft has
  this serial number flown on?". So each install is an `Installation` row with
  `installed_at` / `removed_at`. Two **partial unique indexes** in PostgreSQL
  (`WHERE removed_at IS NULL`) guarantee a part is never installed twice and a
  position never holds two parts, even if some future code skips the service
  checks (there's a test that bypasses the service and gets an `IntegrityError`).

## D-013 — Flight logs are immutable through the API
- **Alternatives:** allow PATCH/DELETE and recalculate counters.
- **Why:** flight logs drive component life, so a silent edit could hide an
  overdue part. Like accounting ledgers, corrections should be explicit new
  entries, not overwrites. Create + read only; the admin can't add or change
  them either. Technicians may log flights (they record post-flight data on
  the line), along with planners and admins. Flights in the future, overlapping
  flights, and flights on stored/retired aircraft are rejected.

## D-014 — Due items are computed live; the arithmetic is a pure function
- **Alternatives:** store a "next due" row per task and update it on every
  flight / record; a rules library or a DSL for maintenance rules.
- **Why:** a stored "next due" value is one more denormalised value that can go
  stale (rule interval edited, back-dated flight, record deleted in the admin…).
  Computing on read means the due list is *always* consistent with the current
  counters and rules. It's still cheap: `compute_due_items` makes a fixed
  number of queries however big the fleet is (a test asserts ≤ 5 queries for 15
  aircraft), using PostgreSQL `DISTINCT ON` to fetch only the latest record per
  task. The safety-critical arithmetic (`evaluate_measure`, `build_item`) touches
  no database, so it's unit-tested exhaustively at the boundaries (44 h / 45 h /
  50 h of a 50 h interval).
  Rules model the real-world pattern **"every N hours / N cycles / N days,
  whichever comes first"**: each set interval is checked separately and the worst
  status wins. Hard life limits from `PartType` go through the same code path as
  a special item kind (`LIFE_LIMIT`).
- **Edge cases decided:**
  * Never-done tasks count from new (aircraft in-service date / component
    manufacture date, 0 h). This is conservative: a used component arriving
    without a baseline record shows as due, which forces the planner to enter
    when the task was last done (`POST /api/maintenance-records/`).
  * Component tasks are tracked on the **component**, so the history follows the
    part when it moves to another aircraft.
  * "Due soon" = 90 % of the interval used (`MAINTENANCE_DUE_SOON_RATIO`).

## D-015 — Projected due dates from 30-day utilisation; Celery beat for the clock
- **Alternatives:** no projection; per-aircraft planned utilisation entered by hand.
- **Why:** planners think in dates ("what's due in the next 30 days?"), but
  most intervals are hours or cycles. Average daily flying over the last 30 days
  turns "12 h remaining" into "~6 days". If the aircraft hasn't flown, no
  projection is shown rather than a made-up one.
  An hourly Celery beat job (`run_due_check`) re-evaluates the fleet, because
  calendar limits expire without any event (no flight, no click) to trigger
  them. Redis is the broker. It's a simple, well-known setup, and the same
  Redis can later serve caching.

## D-016 — Alerts are reconciled, de-duplicated, and auto-resolved
- **Alternatives:** create a new alert every time the check finds a problem;
  email notifications.
- **Why:** an hourly check that inserts "aircraft X overdue" every hour trains
  people to ignore alerts. Instead, `sync_alerts` compares the *current
  problems* with the *open alerts*: new problem → open, gone → resolve,
  DUE_SOON→OVERDUE → escalate (and clear the acknowledgement so someone looks
  again). A partial unique index (`dedup_key WHERE resolved_at IS NULL`)
  guarantees one open alert per problem. Running it twice changes nothing
  (idempotent), so Celery retries are safe. Acknowledging means "I've seen it";
  only fixing the problem resolves an alert.

**Airworthiness rule:** GROUNDED if anything is overdue (task or life limit),
ATTENTION if something is due soon, otherwise AIRWORTHY. (Phase 4 adds open
grounding work orders as a GROUNDED reason.)

## D-017 — Work orders as an explicit state machine
- **Alternatives:** a free-form `status` field anyone can PATCH; a workflow
  library (django-fsm, viewflow).
- **Why:** each status change has preconditions (checklist complete, the right
  person, the right previous state) and side effects (audit entry, maintenance
  record). Plain functions in `workorders/services.py` with an `ALLOWED_FROM`
  table make every legal transition visible in ~10 lines, with no extra
  dependency. The API has no way to set `status` directly; only actions
  (`/start/`, `/sign-off/`, `/certify/`, …) move it.
  ```
  OPEN → IN_PROGRESS → AWAITING_INSPECTION → CLOSED
                 ↖────── reject ──────┘
  OPEN / IN_PROGRESS → CANCELLED
  ```
  Who does what: planners create, assign, certify, reject and cancel; only the
  **assigned technician** starts the work, ticks the checklist and signs.
  Work-order numbers come from the primary key (`WO-2026-00042`), which avoids
  the race of "read the last number, add one" between two planners.
  A closed work order linked to a rule automatically creates the
  `MaintenanceRecord`, which resets that task in the due list, using the
  counters captured at **technician sign-off**. That way, hours flown while
  waiting for inspection still count toward the next interval.
  Grounding work orders (e.g. a defect) make the aircraft GROUNDED until closed.

## D-018 — Digital sign-off: password re-entry, two-person rule, content hash
- **Alternatives:** a simple "Sign" button; PKI/qualified e-signatures.
- **Why:** in aviation, the person who did the work and the person who releases
  it should be different people (independent inspection). We enforce that in
  the service **and** with a DB `CHECK` constraint
  (`inspector_signed_by <> tech_signed_by`).
  Signing asks for the user's password again, so it's a deliberate act by
  the account owner, not a click on someone else's unlocked screen.
  At sign-off we store a SHA-256 hash of exactly what was signed (checklist
  items, who ticked them, notes). The inspector's signature hashes the
  technician's signature, forming a small chain. If anyone edits the checklist
  in the database afterwards, `GET /work-orders/{id}/verify/` reports it and
  certification is refused (tested). Real PKI signatures would be the next
  step for regulatory use. Here the goal is to show tamper evidence without
  certificate infrastructure.

## D-019 — Inventory as a ledger of stock movements
- **Alternatives:** a single editable `quantity` field.
- **Why:** "why do we have 3 filters when we bought 10?" can only be answered
  if every change is recorded. `StockMovement` rows (receipt / issue / return /
  adjustment, with who, why and which work order) are the history, like a bank
  statement. `quantity_on_hand` is the running balance: updated under a row
  lock with `F()`, never editable through the API or admin, and protected by a
  DB `CHECK (quantity_on_hand >= 0)`. Adjustments (stock counts) require a
  written reason. Only the assigned technician can draw parts for a work
  order, and only while it's in progress, so parts usage is traceable to
  the job. When a movement crosses the reorder point, the low-stock check is
  queued **after commit** (`transaction.on_commit`), so an alert never refers
  to a change that was rolled back. If the broker is down, the stock change
  still succeeds and the daily check catches up.

## D-020 — Dashboard: one aggregated endpoint; readiness counts ACTIVE aircraft
- **Alternatives:** the frontend calls 6 endpoints and aggregates; a separate
  analytics store.
- **Why:** the dashboard is the most-opened page, so one request returning
  everything it needs is faster and simpler to cache later. It reuses the same
  engine as the due list, so numbers on the dashboard can never disagree with
  the due list.
  **Readiness % = (AIRWORTHY + ATTENTION) / ACTIVE aircraft.** Stored aircraft
  are excluded (a parked aircraft isn't a readiness failure). ATTENTION
  counts as ready: it may fly today and just needs planning. With zero active
  aircraft the value is `null`, not a division error.
  The 30-day timeline uses projected due dates (D-015). Overdue items are pinned
  to today so they're never hidden in the past.

## D-021 — Demo data through the real services
- **Alternatives:** JSON fixtures; raw SQL inserts.
- **Why:** `python manage.py seed_demo --reset` builds a 6-aircraft fleet with
  60 days of flights, baselines, work orders in every state and stock, by
  calling the same service functions the API uses. So the demo exercises the
  real rules (it caught a life-limit check during development), counters
  verify cleanly (`verify_counters`), and the audit log looks like real use.
  It's deterministic (fixed random seed). One aircraft (TB2-T003) gets a
  creeping vibration/temperature trend for the anomaly detector to find.

## D-022 — AI behind a provider interface; "mock" = a deterministic implementation
- **Alternatives:** call the LLM SDK directly in each feature; a framework such
  as LangChain; a mock that returns canned strings.
- **Why:** the brief requires a configurable provider and a demo/test suite that
  runs with no API key. Each AI feature has two implementations:
  1. an **LLM path** (`LLM_PROVIDER=anthropic`: Claude via the official SDK), and
  2. a **deterministic path** that's genuinely useful on its own: extractive
     answers with citations, a rule-based query parser that understands Turkish
     and English, template explanations of anomalies.

  `LLM_PROVIDER=mock` selects path 2. The same path is the **fallback** when
  the LLM fails (outage, rate limit, refusal), and the response is marked
  `degraded: true`. The maintenance app never stops working because an AI
  vendor is down. A framework like LangChain was rejected: three features
  need one `complete()` and one `complete_json()` call, and owning ~100 lines
  is easier to explain and test than a large dependency.
  Claude settings: `claude-opus-5-5`, effort `medium` set explicitly,
  structured outputs (JSON schema) for the query parser, and server-side
  refusal fallbacks (`fallbacks="default"`), so a declined request is retried
  on a fallback model within the same call. Tests stub the SDK client and check
  the exact request shape, so they never touch the network.
  Every AI call is logged (`AIRequestLog`: user, feature, provider, latency,
  tokens, degraded), and the AI endpoints have their own per-user throttle
  because LLM calls cost money.

## D-023 — pgvector with a fixed 384-dimension column; offline hashing embeddings
- **Alternatives:** a separate vector database (Pinecone, Qdrant, Chroma);
  semantic embeddings from an API from day one.
- **Why:** pgvector keeps vectors in the same PostgreSQL as everything else: one
  backup, one transaction, and SQL joins to documents/permissions. Search uses
  cosine distance with an **HNSW index** (approximate nearest neighbour), so it
  stays fast as manuals grow. The vector dimension is part of the column type,
  so it's fixed in settings (`EMBEDDING_DIM = 384`). Switching to a model with
  another dimension means a migration plus re-ingesting (`/reingest/`).
  The offline embedder uses the hashing trick over words and word pairs. It
  matches **shared words, not meaning**. Measured on the demo manual, a
  Turkish question about an English page scores 0.09 vs 0.08 for an unrelated
  question, so cross-language search needs a real multilingual embedding
  model. That's the known limitation, and the reason the provider sits behind
  an interface. Anthropic doesn't offer an embeddings endpoint; adding a
  semantic provider (e.g. Voyage AI, or a local sentence-transformers model) is
  one class in `providers.py`.

## D-024 — RAG: page-bounded chunks, numbered sources, validated citations
- **Alternatives:** chunk the whole document as one stream; let the model cite freely.
- **Why:** technicians need to open the page the answer came from. Chunks
  (~900 characters, 150 overlap) never cross a page boundary, so every hit
  has exactly one page number. The model receives numbered excerpts, must
  answer only from them, must quote limits exactly, and must say "not covered"
  rather than fill gaps from general knowledge. A wrong torque value is a
  safety issue. After the answer, every `[n]` is checked against the excerpts
  actually sent; invented citations are dropped (tested). If the best match is
  below a similarity threshold, the system answers "not found" without calling
  the LLM at all. Upload safety: content is checked for the `%PDF-` signature
  (not just the file name), size is capped at 25 MB, duplicate files are
  rejected by SHA-256, and ingestion runs in Celery so big PDFs don't block
  a web worker.

## D-025 — Natural-language queries: the LLM fills a whitelisted spec, never SQL
- **Alternatives:** text-to-SQL (the LLM writes SQL that we execute).
- **Why:** text-to-SQL can be manipulated by prompt injection ("…; DROP TABLE"),
  can read tables the user shouldn't see, and produces queries nobody has
  tested. Here the model can only choose one of 7 entities and fill named
  filters (JSON schema enforced by structured outputs). `normalise()` re-checks
  the output anyway (never trust model output). Our ORM code runs the query,
  read-only. The interpreted spec and a one-line explanation are returned with
  the rows, so a misunderstanding is visible. Without an LLM, a keyword parser
  covers the common questions in Turkish and English.

## D-026 — Anomalies are detected by statistics; the LLM only explains them
- **Alternatives:** ask the LLM to find anomalies in raw flight data; ML models
  (isolation forest, LSTM).
- **Why:** detection must be deterministic, explainable and testable. A
  language model can't be trusted to notice (or not invent) a 3-sigma shift.
  We use a **robust z-score** (median and MAD instead of mean and standard
  deviation, so a single broken sensor reading in the baseline doesn't hide a
  real change). The last 5 flights are compared with the 30 before them.
  Flagged when ≥ 2 of the 5 exceed |z| > 3.5: one spike is treated as noise, a
  trend is not (both cases tested). An ML model would need labelled failure data
  we don't have. The LLM's job is narrow: turn the numbers plus aircraft
  context (installed parts, recent work orders) into a plain-language
  explanation and ordered checks, always marked **advisory**: certifying
  staff, not the AI, decide airworthiness. A daily Celery job turns detected
  anomalies into deduplicated ANOMALY alerts.

## D-027 — Frontend: client-rendered app behind a same-origin proxy, TanStack Query for server state
- **Alternatives:** server components fetching from Django with the user's
  token; Redux/Zustand for data; calling Django directly from the browser
  with CORS.
- **Why:** every screen is behind a login and shows per-user, fast-changing
  data, so there's little to gain from server-rendering it. Pages are client
  components; **TanStack Query** owns server state: caching, background
  refetch (the dashboard refreshes every 60 s and on tab focus), retries, and
  invalidation after mutations (logging a flight invalidates everything,
  because counters move every derived view). There's no global store: almost
  all "state" is server state, and the little UI state lives in components.
  Next.js **rewrites** `/api/*` to Django, so the browser talks to one origin.
  That makes the httpOnly, `SameSite=Strict` refresh cookie work without
  CORS, and the backend URL is never exposed to the browser. The access token
  is kept **in memory only**. On a 401 the client refreshes once and retries;
  parallel 401s share one refresh request (unit-tested). Opening a manual PDF
  fetches it with the token and opens a blob URL at `#page=N`, because a plain
  link can't carry an in-memory token.
- **UI rules:** status is always icon + text, never colour alone; semantic
  colour tokens (dark ops theme by default, light theme available); visible
  focus rings; reduced-motion respected; the chart has a screen-reader table.
  The demo exercises role-based UI (a viewer sees no write buttons), but the
  **server** is the security boundary. Hiding a button is convenience, not
  protection.

## D-028 — Next.js 16 Cache Components: Suspense around session-dependent UI
- **What happened:** `next build` failed: with Cache Components, reading the
  URL (`usePathname`, `useSearchParams`) outside `<Suspense>` blocks
  prerendering. The fix was structural: the authenticated shell sits inside
  `<Suspense>` (the static shell is a spinner), and `loading.tsx` gives each
  page its own boundary below the layout. Routes in the `(app)` group set
  `instant = false`: the docs' documented opt-out for session-gated routes,
  which Next can't verify as instant because only the browser knows the
  session. Lesson kept: **run the production build in CI**. Dev mode didn't
  show this.

## D-029 — Test pyramid: pytest (most), Vitest (client logic), Playwright (critical journeys)
- **Alternatives:** only unit tests; only E2E; Cypress.
- **Why:** the safety-critical rules live in the backend, so most tests are
  pytest against real PostgreSQL (rule engine boundaries, concurrency, DB
  constraints, permissions). Vitest covers the tricky client code (token
  refresh, error messages). Playwright drives a real browser through the
  journeys that must never break: login and session restore, role-based UI,
  the full **create → technician signs → inspector certifies** work order,
  and the AI assistant. E2E found a real issue during development (the login
  rate limit tripping on rapid logins), handled by showing a clear
  "too many attempts" message and a configurable `LOGIN_THROTTLE`.
  Playwright was chosen over Cypress for multi-user flows in one test,
  first-class tracing, and parallel CI support.

## D-030 — One backend image for API, worker and beat; Compose for the whole stack
- **Alternatives:** separate images per process; Kubernetes.
- **Why:** the API, the Celery worker and Celery beat run the same code with
  different commands, so one image keeps them in lock-step (no version
  skew). The Dockerfile installs dependencies before copying code (layer
  caching), collects static files at build time (served by WhiteNoise, no
  separate file server), runs as a **non-root** user and has a health check.
  The frontend uses a multi-stage build with Next's `standalone` output, so
  the final image has no dev dependencies. Migrations run in a one-shot
  `migrate` service that the others wait for
  (`service_completed_successfully`), so a new release never serves requests
  against an old schema. Compose is enough for one server; Kubernetes would
  add a lot of operational surface for no benefit at this scale.
  Running the built images during development caught a **real production
  bug**: Celery's Redis transport needs `packaging`, which was only installed
  locally as a side effect of pytest. It's now pinned in `requirements.txt`.

## D-031 — CI: four jobs, from fast feedback to full stack
- **Why:** `backend` (ruff, migrations-up-to-date check, Django deploy checks,
  pytest on real Postgres+pgvector) and `frontend` (lint, types, Vitest,
  production build) run in parallel for fast feedback. `e2e` starts the real
  API with demo data and runs Playwright against the **production** Next
  build. `docker` builds every image, starts the full Compose stack, and
  smoke-tests it, including a Celery job through Redis. The pipeline checks
  the deployable artifact, not just the source. A failing E2E run uploads the
  Playwright trace and API log as artifacts.

## D-032 — Deployment: single VM + Caddy (documented, not automated yet)
- **Alternatives:** a PaaS (Render/Railway/Fly); Kubernetes; managed DB.
- **Why:** the stack needs PostgreSQL **with pgvector**, Redis, a worker and a
  scheduler, which is awkward or costly on many free PaaS tiers but simple on one
  VM with Compose. Caddy gives automatic HTTPS, HSTS and the HTTP→HTTPS
  redirect (which is why Django's own HSTS/redirect checks are silenced).
  Continuous deployment (CI → server) is left out on purpose: it needs a
  server and secrets that belong to the owner, and pushing/deploying is the
  owner's decision. See `docs/deploy.md`.

## D-033 — Stretch: a Go service for flight-data ingestion
- **Alternatives:** a Django endpoint that accepts raw telemetry; a Celery task
  that parses uploads.
- **Why:** raw telemetry is large (a 3-hour flight at 1 Hz is ~11,000 samples)
  and arrives in bursts when several aircraft land. Parsing and aggregating it
  is CPU work that would tie up gunicorn workers. A small Go service handles it
  concurrently with low memory and ships as a ~10 MB distroless image (no shell,
  non-root). It uses only the standard library. Django receives only the
  summary it actually stores: take-off/landing, cycles (ground→air transitions,
  so touch-and-goes count), max temperature, mean vibration, and fuel (trapezoid
  integral of fuel flow, skipping telemetry dropouts so a gap isn't counted
  as fuel burned).
  **Reliability:** the Go service retries network errors, 5xx and 429 with
  exponential backoff, but never 4xx (a validation error won't fix itself).
  Retrying is only safe because the Django endpoint is **idempotent on
  `external_id`**: a retry of a stored flight returns 200 and is not counted
  twice. This was verified end to end in containers: 1,092 samples → one flight,
  the second upload → `duplicate: true`, `verify_counters` clean.
  **Security:** machine-to-machine auth with a shared token compared in
  constant time (`hmac.compare_digest`). A user's JWT is not accepted on that
  endpoint, and the token can only create flights. In production the port is
  bound to localhost/VPN only. Flights still go through `log_flight`, so every
  rule (no overlaps, no future flights, inactive aircraft rejected) applies to
  ingested data exactly as to manual entry.

## D-034 — Free live demo: Render (API) + Neon (Postgres) + Vercel (web)
- **Alternatives:** the single VM of D-032 (costs money, needs a server); Railway/Fly
  (no lasting free tier for this stack); everything on Render (its free Postgres
  is deleted after 30 days and pgvector support depends on the plan).
- **Why:** each piece has a free tier that fits what it does. **Neon** is managed
  PostgreSQL where `CREATE EXTENSION vector` works, so the existing migration
  (`apps/ai/migrations/0001_initial.py`, `VectorExtension()`) enables pgvector
  with no manual step. **Render** runs the Django image as a Python web
  service from `render.yaml` (infrastructure as code, reviewable in git).
  **Vercel** builds and hosts Next.js natively.
- **Free-tier constraints and how they're handled:**
  - Render's free plan has no pre-deploy hook, so `backend/scripts/render-start.sh`
    runs `migrate` and `seed_demo --if-empty` before gunicorn. Both are
    idempotent, so it's safe on every boot.
  - The free instance sleeps after ~15 min idle (first request then takes ~1 min)
    and its **disk is ephemeral**. The DB lives on Neon so data survives, but
    uploaded PDFs don't. `seed_demo --if-empty` rebuilds the demo manual's PDF
    on boot (it's generated from code), and the file endpoint returns 404 instead
    of 500 when a file is missing. Real production would put media on S3-compatible storage.
  - Secrets (`DATABASE_URL`, API key, allowed origins) are `sync: false` in the
    Blueprint: typed once into the dashboard, never stored in git.
    `DJANGO_SECRET_KEY` is generated by Render. `ALLOWED_HOSTS` picks up
    Render's `RENDER_EXTERNAL_HOSTNAME` automatically.
  - DB connections are reused for 60 s with health checks (`CONN_MAX_AGE`,
    `CONN_HEALTH_CHECKS`): every new TLS connection to Neon costs time, and Neon
    closes idle connections when it scales to zero.
- **Demo login:** the login page has a one-click "Try the demo" button (planner)
  plus links for the other roles, all using the seeded demo users. It can be
  hidden with `NEXT_PUBLIC_DEMO_LOGIN=false`. `DEMO_RESET_ON_START=true` wipes and
  re-seeds on every boot if visitors leave the data in a mess.

## D-035 — Celery runs eagerly on the free demo
- **Alternatives:** a paid Render worker + Redis (Render Key Value / Upstash);
  replacing Celery with threads or a DB-backed queue.
- **Decision:** `CELERY_TASK_ALWAYS_EAGER=true` in `render.yaml`. Every `.delay()`
  runs inline in the web process: no broker, no worker. The task code is the same,
  so Docker Compose (D-030) still runs the real Redis + worker + beat.
- **Trade-offs, accepted for a demo:**
  - Slow tasks (PDF ingestion) run inside the HTTP request. The upload request
    takes longer, and gunicorn's timeout is raised to 120 s for that.
  - No retries or isolation: a failing task fails in the web process (the
    exception is stored on the eager result and not re-raised, so the request still completes).
  - **No Celery beat:** the hourly due-check and the daily stock/anomaly scans don't
    run on a schedule. They do run at seed time and whenever the triggering action
    happens (e.g. stock consumption queues a stock check). On a real deployment,
    beat runs (Compose) or a cron calls the same tasks.
- This is one environment variable, not a code fork. Tests already run eagerly
  the same way (`conftest.py`).

## D-036 — AI provider "auto": Claude only when a key exists
- `LLM_PROVIDER` now defaults to `auto`: Claude if `LLM_API_KEY` (or
  `ANTHROPIC_API_KEY`) is set, otherwise the offline mock provider (D-022). If the
  Anthropic client can't even be constructed (no credentials), it logs a warning
  and degrades to the mock instead of breaking every AI page. So a public demo
  works with zero secrets, and adding a key upgrades it with no code change.

## D-037 — Vercel proxies /api to Render (the browser never calls Render)
- **Alternatives:** the browser calls `NEXT_PUBLIC_API_URL` directly with CORS.
- **Why:** the refresh token is an httpOnly `SameSite=Strict` cookie (D-005).
  `*.vercel.app` and `*.onrender.com` are different sites (both are on the Public
  Suffix List), so a cookie set by Render would be a **third-party cookie**,
  which Safari and Chrome block. Users would be logged out on every reload.
  Next.js rewrites (`next.config.ts`) proxy `/api/*` to the URL in
  `NEXT_PUBLIC_API_URL`, read at **build time**, so the cookie stays first-party
  on the Vercel domain and the `SameSite=Strict` protection is kept.
  `CORS_ALLOWED_ORIGINS` is still set to the Vercel origin, so a direct call
  (e.g. from a future client) is limited to that origin. The same rewrite already
  served Docker (D-027); only the env var name changed (`API_ORIGIN` still works).
