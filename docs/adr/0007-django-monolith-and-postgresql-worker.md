# ADR 0007: Django monolith and PostgreSQL-backed worker

- Status: Accepted
- Date: 2026-09-03

## Context

StewardBench v1 is a CRUD- and workflow-heavy authenticated operations
application with relational, immutable history. It must run approximately 200
remote API questions sequentially or with bounded parallelism, retain progress
durably, and continue independently of the initiating browser request. v1 must
remain simple on laptops and a DGX Docker host while preserving a clean
Kubernetes path for v2.

The selection compared a Django-centric monolith, FastAPI with a
server-rendered UI, and FastAPI with a SPA. It also compared a domain-specific
PostgreSQL worker with request callbacks, framework/database task abstractions,
Celery, RQ, and Dramatiq. The weighted analysis is in
[Framework selection](../framework-selection.md).

## Decision

Use a cohesive modular Django application. Use a supported Django LTS line and
pin the secure patch release when implementation is authorized. Django provides
the web framework, ORM, migrations, forms, password/session authentication,
CSRF handling, and server-side request facilities.

Render the product UI with Django templates. Use HTMX selectively for
server-rendered fragments such as run-progress polling and review-flow updates,
with small plain-JavaScript modules for client-only behavior. Do not build a
SPA or separate frontend/API service for v1. Django Admin is not the product UI
and cannot bypass application-service authorization.

Represent the application role explicitly as exactly ADMIN or OPERATOR while
using Django authentication mechanics. Framework superuser, staff, group, or
model-permission concepts do not add StewardBench product roles. Views and the
worker call application services that enforce the documented role and domain
rules.

Use Django ORM and Django migrations against PostgreSQL only. Relational
constraints, transactions, and typed/filterable columns hold domain state;
JSONB is limited to variable evidence and payloads already authorized by the
architecture.

Use a dedicated worker process from the same Django codebase and application
image. PostgreSQL run-plan and pending work/Execution-intent records are the
durable queue and state authority. Claim work with short transactional row
locks, using `SKIP LOCKED` where appropriate, and explicit claim identity plus
lease/heartbeat or equivalent reconciliation metadata. Do not hold a database
transaction open during remote target calls.

The worker uses bounded I/O concurrency. Sequential mode permits one in-flight
request. Parallel dispatch respects the requested run limit and the target's
maximum, including aggregate work against that target. Per-question timeout,
optional delay, independent item failure, progress projection, and restart
reconciliation are worker responsibilities.

Terminal observations are never overwritten. After interruption, only work
known to be safe is reclaimed; an attempt that may have reached a target is
recorded as a benchmark-infrastructure error rather than silently resubmitted.
User retry creates a new Run and Execution.

The normal v1 Docker topology has three long-running containers: web, worker,
and PostgreSQL. Web and worker use the same application image with different
entry points. Migrations run as an explicit one-shot deployment step. Redis,
RabbitMQ, Celery, RQ, Dramatiq, Kafka, and Kubernetes are not required.

Use pytest with pytest-django as the common test approach. Persistence,
migration, transaction, and worker-claim tests run against PostgreSQL. Add
request/RBAC tests, controlled target-adapter integration tests, selective
Playwright tests for critical UI workflows, and Docker integration tests in the
later implementation/quality phases.

## Consequences

- The framework supplies most CRUD/auth/form/migration needs, allowing the
  small team to focus on the evaluation workflow.
- Server-rendered pages naturally fit URL-addressable tables, filters, forms,
  details, and review flows while HTMX supplies bounded live behavior.
- Future API and CLI callers reuse application services rather than requiring
  a v1 API-first or SPA architecture.
- Launching a run is a short transaction; execution and progress do not depend
  on a browser or web process.
- PostgreSQL remains the single durable system and no broker is operated in v1.
- StewardBench owns a small, domain-specific dispatcher and must thoroughly
  test claiming, concurrency, recovery, terminal-write idempotency, and failure
  attribution.
- A broker may be reconsidered only with measured contention/throughput or new
  routing, fan-out, or scheduling requirements that justify another durable
  component.
- The web and worker process boundary maps cleanly to separate Kubernetes
  workloads in v2 without changing the domain model.
- Exact dependency versions, HTTP/chart libraries, production web server, run
  cancellation, evaluator providers, OpsSteward wire contracts, and future API
  tooling remain separate decisions.

## Alternatives rejected

- **FastAPI with server-rendered templates:** capable, but requires more
  assembly and ownership for ORM/migrations, form workflows, sessions, CSRF,
  local user administration, and the exact RBAC policy without simplifying the
  durable worker.
- **FastAPI with a SPA:** adds a frontend build/application and comprehensive UI
  API contract without a v1 interaction that requires them.
- **Request-process background callbacks:** do not meet durable restart and
  browser-independent execution requirements.
- **Django Tasks or a generic database-backed queue:** still needs production
  execution infrastructure or duplicates the domain work state; no benefit is
  demonstrated over the narrow PostgreSQL dispatcher.
- **Celery, RQ, or Dramatiq:** provide valuable generalized task distribution
  but add Redis/RabbitMQ and parallel job state for a small bounded workload
  already modeled durably in PostgreSQL.

This ADR refines, and does not supersede, [ADR 0004](0004-docker-v1-and-durable-background-execution.md).
Docker remains v1, Kubernetes remains v2, and run cancellation remains
unresolved.
