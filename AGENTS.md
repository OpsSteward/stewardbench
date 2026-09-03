# StewardBench agent operating contract

This file applies to the entire repository. Start with the [README](README.md)
and [documentation index](docs/README.md), then read the authority relevant to
an area before changing it.

## Repository purpose

StewardBench is an implementation-independent AI network-operations evaluation
platform. OpsSteward is the first evaluated product, not a hard-coded
architectural dependency.

The main v1 purpose is to automate repeated operator-question execution,
establish a human-reviewed baseline, compare subsequent builds or patches, and
surface the small subset of changed or failed answers requiring human
attention.

## Authority hierarchy

Use this precedence when sources differ:

1. Accepted [ADRs](docs/adr/README.md) for the decisions they explicitly settle.
2. [Product](docs/product-definition.md), [architecture](docs/architecture.md),
   [domain](docs/domain-model.md), [evaluation](docs/evaluation-methodology.md),
   and [UI](docs/ui-ux.md) specifications.
3. The [roadmap](docs/roadmap.md) for release boundaries and the specialized
   [import](docs/question-corpus-import.md) and
   [adapter](docs/target-adapter-contract.md) specifications within their scope.
4. [Historical/reference inputs](docs/reference/README.md), including the
   original Evaluation Lab blueprint and workbook.

Reference material explains provenance and supplies corpus data; it does not
override deliberate later StewardBench decisions. Treat
[open questions](docs/open-questions.md) as unresolved. Do not silently decide
one when the choice changes product behavior or architecture.

## Critical invariants

- A Baseline is observed historical performance, not universal ground truth.
- Human GOOD/BAD is authoritative when present. Automated evaluator and judge
  results remain independent signals.
- A changed answer is not automatically a regression.
- Review state and human judgment are separate. Execution outcome and answer
  quality are separate. Automated outcome, validity, and change state also
  remain orthogonal.
- Completed runs and terminal Execution observations are immutable. Retry and
  rerun create new Runs and Executions; they never reopen or replace history.
- INVALID excludes an observation from normal quality metrics but never deletes
  it or its evidence.
- Controlled comparison requires the same QuestionVersion, frozen bindings,
  and concrete submitted question. Missing or invalid frozen bindings produce
  NON_COMPARABLE, never silent substitution.
- Historical target revision and build identity remain frozen; unknown identity
  is recorded as unknown rather than fabricated.
- Only ADMIN may launch, retry, or rerun evaluations. OPERATOR is read-only.
- PostgreSQL is the only application database. Docker is the v1 deployment
  boundary; Kubernetes is deferred to v2.
- Supported evaluated-product APIs are the v1 execution boundary. Keep
  OpsSteward-specific behavior behind versioned target adapters.
- StewardBench must not reproduce OpsSteward or build comprehensive
  authoritative-answer infrastructure as a v1 prerequisite.
- Semantic comparison is conservative. Uncertainty or comparator failure must
  surface human review rather than hide a possible change.
- Secrets must never enter immutable requests, responses, evidence,
  diagnostics, comments, logs, or exports.

## v1 scope guard

Do not silently implement deferred work, including:

- Kubernetes or CI-triggered evaluation;
- automatic release gating;
- MCP evaluation;
- a user-facing CLI or comprehensive REST/API-triggered evaluation surface;
- comprehensive deterministic answer-oracle infrastructure;
- external-event correlation or per-run operational-system snapshots;
- a sophisticated audit subsystem, complex RBAC, or OIDC/Authentik;
- scheduled runs or multi-target fan-out;
- object-storage infrastructure;
- bulk historical regrading; or
- automatic random-question generation.

If required work appears to depend on one of these, stop and document the need
for product-owner/architecture review instead of smuggling it into scope.

The v1 application architecture is selected in
[Framework selection](docs/framework-selection.md) and
[ADR 0007](docs/adr/0007-django-monolith-and-postgresql-worker.md): a Django
modular monolith, server-rendered UI with selective HTMX, Django ORM/migrations,
and a PostgreSQL-backed worker. Do not replace or expand that stack silently;
material change requires an ADR.

## Development behavior

- Inspect existing code, documentation, and Git status before changing them.
- Make the narrowest coherent change and preserve unrelated user work.
- Update authoritative documentation when behavior or architecture changes.
- Add or update tests with behavior changes; use migrations for persistent
  schema changes.
- Preserve historical data, evidence, attribution, and Unicode/multilingual
  content. Avoid destructive mutation or normalization.
- Prefer the simplest architecture that satisfies documented requirements;
  avoid speculative infrastructure and abstraction.
- Keep target-specific integration behind adapter boundaries and UI concerns
  separate from orchestration and evaluation semantics.
- Treat evaluated-product output as untrusted: escape or explicitly sanitize it
  before rendering, and never execute returned markup or script.

## Validation expectations

Do not claim completion from code inspection alone. Run repository-provided
checks plus evidence appropriate to the affected subsystem, which may include:

- unit, integration, and regression tests;
- database migration and constraint checks;
- RBAC tests;
- API and UI behavior checks;
- Docker/runtime validation;
- `git diff --check`; and
- a clean or fully understood `git status`.

Exact commands will be established after framework selection. Do not invent
commands or claim checks that do not exist. Report what ran, its result, and any
validation that could not run.

## Defect attribution

When validation fails, use observable evidence to distinguish a StewardBench
product/runtime defect from a test/harness defect, fixture/data problem,
target/OpsSteward failure, evaluator/judge failure, or environmental/
infrastructure failure. Do not automatically attribute every failure to
application code.

## Git hygiene

- Inspect status before and after work; do not overwrite unrelated changes.
- Keep commits scoped when the current task authorizes a commit.
- Never commit secrets, credentials, machine-specific state, or generated junk.
- Report changed files, tests/validation performed, commit SHA when applicable,
  and final status.
- Do not assume autonomous commit permission; follow the current task and
  repository instructions.

## Future skills and harness

Repository-specific development/QA skills and an executable StewardBench
acceptance harness are the next planned governance/quality work. Do not define
or scaffold them in this file or without a separately authorized task.
