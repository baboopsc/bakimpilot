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
