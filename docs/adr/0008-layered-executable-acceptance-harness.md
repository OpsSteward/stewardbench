# ADR 0008: Layered executable acceptance harness

- Status: Accepted
- Date: 2026-09-03

## Context

StewardBench must prove its own product, historical-integrity, worker, RBAC,
comparison, adapter, import, and deployment contracts without treating every
failed end-to-end check as an application defect. Its PostgreSQL-backed worker
has transaction, lock, lease, restart, and ambiguous remote-call behavior that
cannot be established with SQLite or mocks. Routine acceptance also cannot
depend on a live OpsSteward deployment or nondeterministic LLM services.

ADR 0007 selected pytest/pytest-django, PostgreSQL integration tests, controlled
adapter tests, selective Playwright, and Docker smoke as the testing
architecture. A durable acceptance design is needed to define how those pieces
produce independent, attributable evidence.

## Decision

Use a layered executable acceptance harness with small observable failure
domains:

- pytest and pytest-django are the common runner and Django integration basis;
- persistence, migration, locking, claim, lease, JSONB, and concurrency
  acceptance uses disposable real PostgreSQL, never SQLite;
- one reusable deterministic fake evaluated-target HTTP service supports
  adapter, worker/process, and Docker acceptance and independently journals
  request identity, count, lifecycle, conversation, and concurrency;
- deterministic evaluator, semantic-comparator, and LLM-judge doubles support
  normal offline acceptance, with static safety/calibration fixtures;
- Django request/service tests prove server-side workflows and RBAC;
- Playwright is limited to high-value browser behavior that direct requests and
  database assertions cannot establish as well;
- Docker smoke proves the selected web/worker/PostgreSQL topology and durable
  restart behavior; and
- live OpsSteward checks are a separately configured, explicitly optional,
  conservatively bounded layer outside routine acceptance.

Scenarios declare stable IDs, authority, prerequisites, expected observable
evidence, PASS criteria, and likely defect domains. Results are PASS, FAIL, or
BLOCKED. A failed harness prerequisite, fixture, double, or environment does not
become a StewardBench FAIL without independent evidence of a product contract
violation.

Normal tests remain under the conventional test tree. A dedicated harness
directory is reserved for reusable external-system simulators, scenario assets,
and black-box/process orchestration; it is not a second application framework.

The detailed layers, evidence model, fake-target contract, initial scenario
catalog, tiers, and later sequencing are specified in
[Executable acceptance harness design](../acceptance-harness-design.md).

## Consequences

- Acceptance can isolate application, harness, fixture, database, worker,
  adapter, evaluated-target, evaluator/judge, comparator, and environment
  failures.
- PostgreSQL and process-level tests cost more than unit tests, so execution is
  tiered and the expensive layers are run according to risk and milestone.
- The fake target becomes critical harness infrastructure and must validate its
  own journal and scenario preconditions.
- Duplicate and ambiguous target calls are proven through target-side evidence,
  not only StewardBench logs.
- One Docker/browser flow cannot substitute for domain, migration, RBAC,
  immutability, comparison, or worker acceptance.
- Optional live integration can identify real wire-contract drift without
  making routine acceptance unsafe or dependent on production.
- This ADR designs the harness architecture only. It adds no harness,
  application, Docker, dependency, or CI implementation.
