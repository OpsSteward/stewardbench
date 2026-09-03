---
name: stewardbench-development
description: Develop StewardBench safely within its Django/PostgreSQL architecture. Use for implementation, refactoring, migration, worker, adapter, UI, and development-test changes; not for independent QA or acceptance audits.
metadata:
  short-description: Develop StewardBench safely
---

# StewardBench development

Build StewardBench incrementally without weakening its product, evidence, or
history contracts. This skill governs implementation work; it is not the
independent QA/acceptance authority and does not define the acceptance harness.

## Start from repository authority

1. Inspect Git status and preserve unrelated work.
2. Read [AGENTS.md](../../AGENTS.md) and the authority relevant to the change.
3. Treat accepted [ADRs](../../docs/adr/README.md) as controlling for the
   decisions they settle. For implementation architecture, read
   [ADR 0007](../../docs/adr/0007-django-monolith-and-postgresql-worker.md) and
   [Framework selection](../../docs/framework-selection.md).
4. Read the affected product, architecture, domain, evaluation, UI, import,
   adapter, and roadmap specifications. Check
   [Open questions](../../docs/open-questions.md) before making a choice that
   changes behavior or architecture.

Repository authority wins over this skill. Use this skill to apply that
authority, not to restate, reinterpret, or override it. An unresolved material
choice requires product-owner/architecture direction rather than an inferred
implementation decision.

## Preserve the selected architecture

Unless a new accepted ADR changes it, implementation MUST remain:

- a Django modular monolith;
- Django ORM and version-controlled Django migrations over PostgreSQL only;
- Django templates as the primary presentation mechanism, with selective HTMX
  or plain JavaScript only when the interaction benefits;
- one codebase/application image with distinct web and dedicated worker entry
  points;
- PostgreSQL-backed durable Run/work/Execution state as the queue authority;
- Docker v1 topology of web, worker, and PostgreSQL; and
- pytest/pytest-django, PostgreSQL integration tests, selective Playwright, and
  Docker smoke validation as the test architecture.

Do not add a v1 SPA, a UI-only internal API service, SQLite support, or
Redis/RabbitMQ/Celery/RQ/Dramatiq/Kafka. Kubernetes remains v2. A demonstrated
need for one of these requires an explicit architecture review and ADR before
implementation.

## Plan the smallest coherent change

Before editing:

- state the requested outcome and inspect the current implementation/tests;
- identify the authoritative contract and affected invariants;
- reproduce the defect when applicable;
- trace the smallest end-to-end path through view/form, application service,
  domain/persistence, worker, and adapter boundaries as relevant;
- decide the migration, compatibility, security, and test implications; and
- stop if the change depends on an unresolved product decision or deferred
  roadmap feature.

Prefer narrow, reviewable changes over broad rewrites. Do not build abstractions
for hypothetical products, scale, or future interfaces. Target-specific logic
belongs behind adapters; reusable product behavior belongs in application
services, not presentation handlers.

## Protect domain invariants

For every touched workflow, explicitly check the relevant invariants in
[Domain model](../../docs/domain-model.md) and
[Evaluation methodology](../../docs/evaluation-methodology.md). In particular:

- terminal Executions and completed Runs are immutable historical
  observations;
- retry/rerun creates a new Run and Execution and preserves source links;
- every Execution retains its exact QuestionVersion, concrete submitted
  question, frozen bindings, target revision, and build snapshot;
- a missing/invalid frozen binding produces NON_COMPARABLE, never silent
  substitution;
- human GOOD/BAD remains separate from automated evaluator/judge results;
- review state remains separate from human judgment;
- execution outcome remains separate from answer quality;
- INVALID preserves the observation/evidence while excluding it from normal
  quality metrics;
- a Baseline is observed historical performance, not truth, and may contain BAD
  or unreviewed observations;
- answer change is not automatically regression;
- later target/build/configuration changes never rewrite historical identity;
- comparator uncertainty/error must surface attention rather than hide change;
  and
- secrets never enter captured requests, responses, evidence, diagnostics,
  comments, logs, or exports.

Any behavior change touching one of these MUST include a regression test that
demonstrates the invariant, including a negative/forbidden path where useful.

## Django conventions

- Organize cohesive Django apps around domain responsibilities. Do not prescribe
  app names before the implementation plan establishes them.
- Keep views/controllers thin: parse/validate, authorize, call an application
  service, and render/redirect.
- Put meaningful workflows and state transitions in explicit application/service
  functions reusable by views, workers, and future interfaces.
- Use model methods only for behavior naturally owned by one model. Avoid god
  models and business logic hidden in templates.
- Prefer forms/model forms and explicit validation over ad hoc request parsing.
- Do not use Django Admin as the StewardBench product UI or as a path around
  application-service authorization and immutability rules.
- Enforce ADMIN/OPERATOR authorization server-side in the service boundary;
  hidden UI controls are not authorization.
- Use transactions around state transitions that must be atomic and database
  constraints for invariants PostgreSQL can enforce.
- Prefer explicit service calls to signal-driven workflows. Use signals only
  where decoupled framework lifecycle behavior is genuinely clearer.
- Reuse focused query/filter functions for list projections. Do not add generic
  repositories that merely wrap Django ORM.
- Paginate operational tables that can grow, and keep filters in stable query
  parameters.
- Escape evaluated-product output by default. Explicitly sanitize any supported
  rich representation; never execute returned markup or script.

## Database and migration discipline

- Exercise meaningful persistence behavior on PostgreSQL. Never substitute
  SQLite for development or tests.
- Create a migration for every persistent schema change and commit it with the
  behavior that needs it.
- Review generated and handwritten operations for locks, table rewrites, data
  loss, defaults, nullability, constraint timing, and historical compatibility.
- Never use a migration or data fix to rewrite immutable Run/Execution evidence
  retroactively.
- Separate complex data migrations from schema migrations when that makes
  deployment, rollback, or review safer. Make forward and rollback implications
  explicit, even when reversal cannot safely restore lost semantics.
- Keep relational identity/state/query fields relational. Use JSONB only for
  materially variable payloads/evidence authorized by the architecture.
- Add constraints and indexes deliberately from a domain invariant or observed
  query need; do not index speculatively.
- When adding/changing lifecycle enums, preserve readable historical values and
  define compatibility for existing rows before deploying code that expects the
  new state.
- Run the repository's migration consistency checks and apply migrations to a
  disposable PostgreSQL database when schema behavior changes.

## Background worker rules

Worker code creates immutable evidence and requires focused design and tests.
Changes MUST preserve:

- durable Run plan, work intent, Execution progress, and terminal state in
  PostgreSQL;
- short claim transactions, with database locks released before any remote
  target call;
- unique claim/lease ownership plus heartbeat or equivalent reconciliation;
- safe worker restart: reclaim only demonstrably safe work and never overwrite
  terminal observations;
- explicit infrastructure error for an interrupted call whose remote completion
  is ambiguous—never silent duplicate submission;
- sequential mode with one in-flight request;
- bounded parallel mode respecting both requested run concurrency and aggregate
  target-wide limits;
- per-question timeout and optional delay;
- independent persistence/failure attribution for each Execution; and
- complete independence from browser navigation or an open HTTP request.

Do not make a framework callback, request-lifecycle task, or web-process thread
the authoritative executor. Test claiming, ownership loss, completion races,
timeouts, partial failure, bounded parallelism, restart/reconciliation, and
ambiguous interruption as applicable.

## Target adapter boundary

Keep evaluated-product-specific connectivity, authentication, request/response,
conversation/session, runtime metadata, normalization, and error mapping behind
the contract in [Target adapter contract](../../docs/target-adapter-contract.md).

Canonical QuestionVersion, comparison, and review logic MUST NOT depend on
OpsSteward routes or payload fields. Adapters report normalized observations and
errors; they do not decide GOOD/BAD, semantic equivalence, or network truth.
Do not add GitHub, Neo4j, Nautobot, Kytos, Kafka, MCP, or other oracle/integration
access to solve an adapter concern without separate approval.

## Operational UI rules

Implement the workflows in [UI/UX](../../docs/ui-ux.md) with server-rendered
HTML first and progressive enhancement second:

- prioritize information density, clarity, predictable navigation, accessible
  labels/statuses, tables, filters, pagination, and efficient review;
- keep filters URL-addressable and preserve review-queue context;
- make every actionable dashboard/comparison counter link to the corresponding
  filtered records;
- show baseline/current answers together where comparison requires it;
- keep execution, automated, human, review, validity, and change states visually
  and semantically distinct;
- use text/icons in addition to color; and
- preserve safe access to raw evidence while escaping untrusted content.

Use HTMX for bounded fragment refresh/actions only when it is simpler than a
full-page flow. Preserve normal server-side validation, authorization, and CSRF
handling. Do not trade operational usability for decorative UI.

## Match tests to risk

Add the smallest test set that proves the changed behavior and its important
failure paths. Do not require the full suite for a trivial documentation edit;
broaden validation in proportion to subsystem risk.

| Test layer | Use when |
| --- | --- |
| Unit | Isolated state transitions, normalization, comparison primitives, and helpers |
| Django/application integration | Models, constraints, services, views, forms, RBAC, filtering, review, or baseline behavior |
| PostgreSQL integration | Transactions, locks, JSONB, constraints, concurrency, `SKIP LOCKED`, or worker claims matter |
| Worker integration | Claiming, execution, timeout, restart/reconciliation, bounded parallelism, or ambiguous interruption changes |
| Selective Playwright | A high-value end-to-end workflow such as login, launch, review, baseline creation, or changed-answer inspection |
| Docker smoke | Composition, migrations, configuration, or web/worker/database runtime behavior changes |

Do not mock away the behavior under test. Use controlled fake target responses
for adapter/worker integration rather than depending on a live OpsSteward system
unless the task explicitly authorizes it. Preserve Unicode/multilingual cases
where input, storage, rendering, or export is affected.

## Diagnose before fixing

When validation fails, gather observable evidence and classify the failure
before changing code:

- StewardBench product/runtime defect;
- test defect;
- fixture/data defect;
- migration/schema problem;
- worker lifecycle/concurrency problem;
- target/OpsSteward failure;
- evaluator/judge or external dependency failure; or
- environment/configuration/infrastructure problem.

Do not weaken a correct test merely to clear a failure. Fix the narrowest proven
cause, add a regression test, and keep diagnostics focused enough to preserve
failure attribution.

## Security-sensitive changes

Authentication, authorization, sessions, password handling, target credentials,
secret redaction, untrusted answer rendering, immutable history, and raw-evidence
exports require focused negative-path tests and explicit risk reporting. Never
persist usable credentials or rely on presentation-layer checks. Flag these
changes for later independent QA review; do not expand StewardBench into
OpsSteward-Sec.

## Documentation and scope

Update authoritative documentation and/or add an ADR in the same change when
implementation changes domain semantics, lifecycle, adapter contract, supported
API behavior, deployment topology, evaluation methodology, or v1 scope. Do not
rewrite product documents for private implementation details.

Do not silently implement deferred roadmap work. In particular, prohibit:

- changing question/baseline semantics to fit an implementation;
- overwriting historical observations or retrying ambiguous calls silently;
- treating baseline equality, automated evaluation, or comparator output as
  human truth;
- hiding uncertain answer changes;
- storing usable credentials in application data or evidence;
- adding SQLite, broker infrastructure, SPA/service decomposition, Kubernetes,
  MCP, CI gating, or other deferred architecture without approval; and
- changing tests solely to make failures disappear without evidence that the
  test is wrong.

## Change workflow and completion evidence

Use this risk-adjusted workflow:

1. Inspect status and relevant authority.
2. Identify affected invariants and inspect current code/tests.
3. Reproduce the defect when applicable and design the narrow change.
4. Implement with any required migration and regression tests.
5. Run targeted tests, then broader relevant tests.
6. Run PostgreSQL/migration, worker, browser, or Docker validation when the
   affected subsystem requires it.
7. Inspect the full diff, run `git diff --check`, and update contractual docs.
8. Inspect final status and report evidence and remaining risk.

Before claiming completion, report:

- what changed and why;
- files changed;
- migrations created or `none`;
- tests added/updated;
- exact validation commands and results;
- known limitations and remaining risks;
- Git status; and
- commit SHA when a commit was authorized and created.

Do not report completion without evidence. This skill does not grant permission
to commit, deploy, call live targets, or make other external changes; follow the
current task and repository instructions.
