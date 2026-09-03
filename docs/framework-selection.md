# StewardBench v1 framework selection

Status: Selected architecture; ADR 0007 accepted. Product-owner review is the
next governance checkpoint.

Date: 2026-09-03

Decision record: [ADR 0007](adr/0007-django-monolith-and-postgresql-worker.md)

## Decision summary

StewardBench v1 will be a cohesive Django application backed only by
PostgreSQL:

- a modular Django monolith using Django's ORM, migrations, forms,
  authentication, password hashing, sessions, and CSRF protection;
- a product UI rendered with Django templates, selectively enhanced with HTMX
  and small amounts of plain JavaScript;
- a domain-specific background worker from the same codebase and application
  image, using PostgreSQL run/work records as the durable queue and state
  authority;
- one web process/container, one worker process/container, and PostgreSQL for
  the normal v1 Docker topology; and
- pytest/pytest-django tests against PostgreSQL, with selective browser and
  Docker integration tests.

The product UI is not Django Admin. No SPA, separate internal API service,
Redis, RabbitMQ, Celery, RQ, Dramatiq, Kafka, or Kubernetes component is part of
the v1 foundation.

Use a supported Django LTS line. Django 5.2 is the supported LTS at this
decision date; pin the then-current secure patch release when application
scaffolding is separately authorized. Reassess the supported LTS at that point
rather than freezing a patch version in an architecture record.

## Requirements that drive the choice

The deciding product shape is an authenticated, relational operations
application for a small technical team. It needs dense tables, filters, forms,
detail pages, review navigation, and modest charts. It also needs durable,
browser-independent execution of up to roughly 200 remote questions with
conservative target concurrency.

The decision must preserve these established constraints:

- PostgreSQL is the only application database, including development/tests
  that exercise persistence semantics.
- Docker must work on a laptop and the initial DGX host; Kubernetes is v2.
- ADMIN mutates and launches; OPERATOR is read-only; authorization is
  server-side.
- application services own evaluation semantics and can later be called by an
  API or CLI without reimplementing them.
- run intent, progress, terminal observations, and historical identities are
  durable; a browser request does not execute a run.
- target-specific behavior remains behind adapters.
- terminal executions are immutable, and uncertain worker recovery never
  silently fabricates continuity or overwrites evidence.

No documented team-familiarity preference distinguishes the candidates, so it
was not scored.

## Candidate comparison

Ratings are 1 (weak) to 5 (strong). Weighted scores measure fit for this v1,
not the general quality of a framework.

| Criterion | Weight | Django monolith | FastAPI + server-rendered UI | FastAPI + SPA |
| --- | ---: | ---: | ---: | ---: |
| Implementation simplicity | 16 | 5 | 3 | 2 |
| Built-in auth/forms/CRUD/migrations | 15 | 5 | 2 | 2 |
| Operational UI fit | 13 | 5 | 4 | 4 |
| Durable background-work fit | 12 | 4 | 4 | 4 |
| PostgreSQL/domain-model fit | 10 | 5 | 5 | 5 |
| Testability | 8 | 5 | 5 | 4 |
| Small-team maintainability | 8 | 5 | 3 | 2 |
| Docker/infrastructure simplicity | 6 | 5 | 5 | 2 |
| Future API/CLI path | 4 | 4 | 5 | 5 |
| Kubernetes portability | 4 | 5 | 5 | 5 |
| Low frontend overkill | 4 | 5 | 4 | 1 |
| **Weighted score / 100** | **100** | **96.8** | **75.6** | **63.2** |

### Candidate A: Django-centric monolith — selected

Django directly supplies the largest share of StewardBench's undifferentiated
needs: a relational ORM and migrations, forms and validation, template
rendering, secure session authentication, password handling, CSRF protection,
and request/database test support. This reduces integration code around the
actual evaluation workflow.

The application remains modular internally. Views call application services;
services enforce authorization and domain invariants; repositories/ORM queries
persist them; adapters isolate evaluated-product APIs. Future API endpoints and
a CLI wrap the same services. They do not require a separate v1 service.

Django Admin is not the Nautobot/Zabbix-inspired product UI and must not become
an alternate path around service authorization. The v1 product UI uses normal
views, forms, and templates. Any developer-only use of Django Admin remains
outside product workflows and cannot introduce a third role or mutable-history
bypass.

Use Django authentication for credentials, password hashing, sessions, and
login/logout mechanics. Model the StewardBench domain role explicitly as
exactly ADMIN or OPERATOR from the first migration. Django `superuser`, `staff`,
groups, and per-model permissions are not additional StewardBench roles. The
bootstrap command creates an ADMIN under the same product policy, and every
mutation is checked server-side in the service boundary.

### Candidate B: FastAPI with server-rendered UI — credible but rejected

FastAPI can render Jinja templates and provides excellent typed API primitives.
It does not, by itself, remove the need to select and integrate SQLAlchemy,
Alembic, form handling, sessions, password flows, CSRF behavior, user
administration, and the exact two-role policy. That assembly is reasonable for
an API-first product, but it is extra ownership for this CRUD- and workflow-heavy
v1.

FastAPI would not simplify durable evaluation execution: its response-linked
background task facility is intended for small same-process work, while this
product still requires an independent durable worker. OpsSteward's use of
FastAPI is not an architectural reason for StewardBench to use it because the
products have different shapes and communicate only through the adapter
boundary.

### Candidate C: FastAPI with a SPA — rejected

A SPA can implement every required screen but adds a frontend application,
build/tooling pipeline, API contract, duplicated client/server validation and
authorization concerns, state management, and more end-to-end test surface.
None of the required interactions—tables, filters, review controls,
side-by-side comparison, expandable evidence, polling, or charts—requires that
cost in v1.

No fourth Python architecture showed a material advantage. Smaller web
frameworks would require more assembly than FastAPI, and splitting a Django UI
from a separate API/worker service would add process and contract boundaries
without a v1 consumer that needs them.

## UI architecture

Render complete, bookmarkable pages on the server with Django templates and
forms. Query-string filters and pagination remain canonical, so navigation and
review queues work with full-page requests and are easy to test.

Use HTMX only for bounded progressive enhancement where a server-rendered
fragment is simpler than a full reload, initially:

- periodic run-progress refresh that stops when the run becomes terminal;
- filtered/paginated table fragments where this materially improves the flow;
- GOOD/BAD and review-state actions with an ordinary POST fallback;
- previous/next review transitions; and
- expanding or loading large raw/evidence sections on demand.

Use small, locally served plain-JavaScript modules for purely client-side
behavior. A small client chart library may render documented trends; the exact
library is an implementation dependency, not an architectural boundary. Do not
introduce a Node-based SPA build solely for charts or polling.

All mutations use normal server-side role checks and CSRF protection. Product
answers and evidence are untrusted and are escaped by default; any supported
rich representation requires explicit sanitization. Unicode content must round
trip unchanged.

## PostgreSQL, ORM, and migrations

Use Django ORM and Django migrations against PostgreSQL only. Use typed
relational columns, constraints, foreign keys, indexes, and transactions for
identity, state, temporal records, and frequently filtered fields. Use Django
`JSONField`/PostgreSQL JSONB only for genuinely variable raw evidence and
versioned evaluator payloads, as already specified.

Immutability is a domain/database concern, not an ORM assumption. Service
operations, constrained update paths, database constraints where practical,
and tests must prevent terminal observation mutation and historical identity
rewrites. Raw SQL is allowed narrowly when PostgreSQL behavior cannot be
expressed safely through the ORM; it does not create a parallel persistence
layer.

SQLAlchemy and Alembic are sound alternatives but add no product capability on
top of Django's integrated ORM/migration path. SQLite compatibility is neither
implemented nor used as a test shortcut.

## Background execution decision

### Selected mechanism

Use the existing domain run plan and pending work/Execution intent in
PostgreSQL as the durable queue. A dedicated worker process, packaged from the
same Django codebase, polls and claims eligible work. This is not a generic
task-serialization framework: database work records remain explicit domain
state visible to the UI, recovery logic, and preserved history.

The worker uses short PostgreSQL transactions and row locking, including
`SELECT ... FOR UPDATE SKIP LOCKED` where appropriate, to claim work without
holding a transaction open across a remote API call. Claim ownership includes a
unique token/worker identity plus lease/heartbeat or equivalent reconciliation
metadata. A completion transaction must still own the matching claim before it
can append terminal evidence.

The dispatcher uses a bounded I/O executor. Sequential runs permit one
in-flight target request. Parallel runs enforce both the run's requested limit
and the target's configured maximum; aggregate dispatch to the same target must
also respect that target limit. Per-question HTTP deadlines and optional delays
are enforced outside the web process, and each item reaches its own terminal
outcome without discarding completed siblings.

### Launch, progress, and recovery walkthrough

1. An ADMIN request validates policy and commits the frozen run manifest,
   PENDING run, and durable work intent in one short transaction.
2. The response redirects to run detail. Navigation or web-process restart has
   no effect on execution.
3. The worker claims eligible items transactionally, releases database locks,
   performs bounded target calls through adapters, and persists each result in
   a completion transaction.
4. UI polling reads database projections; the browser never owns task state.
5. On worker restart, terminal observations remain untouched. Demonstrably
   unstarted or safely reclaimable work is claimed again. A stale item that may
   have reached the target is finalized as an explicit benchmark-infrastructure
   error rather than silently resubmitted.
6. A user-visible retry always creates a new Run and Execution linked to the
   source; it never reopens history.

### Mechanism comparison

| Option | Durability and fit | Infrastructure | Decision |
| --- | --- | --- | --- |
| PostgreSQL domain queue + dedicated worker | Same transaction as run creation; domain-native progress; explicit recovery; row-lock support for consumers | Existing PostgreSQL plus one app worker | **Selected** |
| Framework/request background callback | Process-local lifecycle and restart ambiguity; cannot satisfy durable independent runs | No new service | Rejected as non-durable |
| Django Tasks abstraction | Production still needs a durable backend and worker; domain progress would still live in StewardBench records | Backend-dependent | Not selected; adds abstraction without solving execution |
| Generic database-backed job library | Can be durable, but duplicates run/Execution state and recovery ownership | Usually no broker | Reconsider only if custom claim mechanics become disproportionate |
| Celery + Redis/RabbitMQ | Mature distribution, retries, routing, scheduling, and monitoring; substantially more than v1 needs | Broker, worker, client integration, operational monitoring | Rejected for v1 |
| RQ + Redis | Simpler than Celery but still adds Redis and parallel job state beside domain state | Redis plus worker | Rejected for v1 |
| Dramatiq + Redis/RabbitMQ | Capable worker/retry model but still introduces a broker and duplicate job/domain state | Redis or RabbitMQ plus worker | Rejected for v1 |

The database worker is intentionally small, but it is not informal. Claiming,
leases/reconciliation, target concurrency, idempotent terminal writes, and
failure attribution are first-class tested application behavior.

Reconsider a broker only with measured evidence: PostgreSQL queue contention,
sustained backlog or throughput beyond the small-worker design, cross-service
routing/fan-out, scheduling requirements, or operational needs that justify an
additional durable system of record. Kubernetes alone is not such evidence.

## Docker topology

The normal v1 topology is three long-running containers:

```text
browser -> web container ----+
                            PostgreSQL
worker container ------------+----> evaluated-product APIs
```

- `web`: production HTTP server running the Django application;
- `worker`: the same application image/code/configuration, running a dedicated
  worker entry point; and
- `db`: PostgreSQL with a durable volume in local/DGX-managed Docker use.

Run migrations as an explicit one-shot deployment step using the application
image; do not let every web/worker replica race migrations at startup. Static
asset serving and the exact production HTTP server are deployment-detail
choices to settle in the implementation plan. Secrets are injected at runtime
and never copied into the image or durable evidence.

This topology is laptop- and DGX-Docker-compatible. In v2, the same stateless
web image and restartable worker image can become separate Kubernetes
workloads, with PostgreSQL supplied appropriately for that environment. No
Kubernetes manifests or assumptions enter v1.

## Testing architecture

Use pytest as the common runner with pytest-django for Django integration.
Tests that exercise persistence use a real disposable PostgreSQL database with
migrations applied—never SQLite. The intended layers are:

- fast unit tests for domain policies, comparison logic, normalization, and
  adapter mapping;
- application-service and Django request tests for transactions, forms,
  sessions, CSRF-sensitive behavior, and ADMIN/OPERATOR authorization;
- PostgreSQL transaction tests for constraints, temporal rules, work claiming,
  `SKIP LOCKED`, leases/reconciliation, terminal-write idempotency, and target
  concurrency accounting;
- worker/adapter integration tests with controlled fake HTTP targets covering
  success, malformed responses, timeout, partial failure, restart, and
  ambiguous completion;
- selective Playwright browser tests for login, filtering/selection, run
  launch/progress, review navigation, comparison, and safe untrusted-content
  rendering; and
- Docker integration/smoke tests for migrations, web/worker/database startup,
  persistence across process restart, health, and configuration boundaries.

This identifies tools and test layers for later quality planning; it does not
define the independent acceptance harness.

## Risks and mitigations

| Risk | Mitigation / review trigger |
| --- | --- |
| Domain-specific worker code becomes a task system | Keep it limited to run dispatch/recovery; do not add general scheduling, arbitrary task routing, or workflow DSL features. |
| Worker death causes ambiguous remote completion | Use correlation IDs when supported, leases/heartbeats, explicit infrastructure-error finalization, and no silent resubmission. |
| Database polling or locking becomes contentious | Use short claim transactions, bounded polling/backoff, indexes, and measure contention before adding a broker or notification optimization. |
| Django conventions leak domain logic into views/models | Require application-service boundaries and test them through both web and worker callers. |
| Framework auth primitives introduce extra product roles | Keep exactly one explicit ADMIN/OPERATOR domain role and test every mutation as both roles. |
| HTMX fragments become a second UI architecture | Keep full-page URLs/forms canonical and server-rendered fragments reusable; use plain HTML fallback where practical. |
| Django ORM alone does not guarantee history immutability | Enforce immutable transitions in services and database constraints where practical, with direct regression tests. |

## Deferred decisions

This selection does not decide:

- run cancellation, which remains a product-owner choice; pause/resume remains
  out of scope;
- the exact Django/Python patch pins, production HTTP server, HTTP client,
  stylesheet system, chart library, or HTMX version;
- semantic comparator or LLM-judge provider/model/prompt;
- exact OpsSteward API routes, response schemas, or runtime metadata route;
- a future REST toolkit, comprehensive API, user-facing CLI, or MCP design;
- Kubernetes, CI integration, release gating, scheduled runs, or multi-target
  fan-out; or
- repository-specific skills and the independent executable acceptance
  harness.

## Primary technical evidence

- Django documents its integrated model layer, migrations, templates, forms,
  authentication, and other common web tooling in its
  [official overview](https://www.djangoproject.com/start/overview/).
- Django 5.2 is an LTS line with extended support through April 2028 in the
  [official supported-version table](https://www.djangoproject.com/download/).
- Django's [authentication documentation](https://docs.djangoproject.com/en/5.2/topics/auth/default/)
  describes session-backed login plus users, permissions, and groups; this
  decision deliberately narrows product authorization to the two documented
  StewardBench roles.
- Django exposes transactional row locks and `skip_locked` through
  [`select_for_update()`](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update).
  PostgreSQL explicitly identifies `SKIP LOCKED` as useful for multiple
  consumers of a
  [queue-like table](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE).
- HTMX supports server-driven
  [polling and load polling](https://htmx.org/docs/#polling), including
  progress views that terminate polling.
- FastAPI supports Jinja via Starlette but as an added template dependency, as
  shown in its [template documentation](https://fastapi.tiangolo.com/advanced/templates/).
  Its [background-task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/#caveat)
  distinguishes small same-process callbacks from larger multi-process work.
- Django's newer Tasks API explicitly does not provide a worker, and its
  built-in backends are development/test-only; see the
  [Django Tasks documentation](https://docs.djangoproject.com/en/6.0/topics/tasks/).
- Celery normally uses a message broker, as described in its
  [official introduction](https://docs.celeryq.dev/en/stable/getting-started/introduction.html#what-s-a-task-queue);
  [RQ](https://python-rq.org/docs/) uses Redis/Valkey, and
  [Dramatiq](https://dramatiq.io/) offers RabbitMQ or Redis brokers.
- Django creates isolated databases for database tests and applies migrations,
  as described in its
  [testing documentation](https://docs.djangoproject.com/en/5.2/topics/testing/overview/#the-test-database).
