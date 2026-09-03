# ADR 0004: Docker v1 and durable background execution

- Status: Accepted
- Date: 2026-09-03

## Context

A run may execute approximately 200 questions and cannot depend on an open
browser request. v1 must be simple to run on laptops, including macOS, and on a
DGX Docker host. Kubernetes is planned later, while adding an unproven broker or
distributed orchestrator now would increase operational scope.

## Decision

v1 is Docker-based with an experience approximately equivalent to
`docker compose up`. Conceptual components are a StewardBench web application,
PostgreSQL, and a background worker/process if required.

Run plans and progress are durable in PostgreSQL. Background processing supports
sequential and bounded-parallel operation, target concurrency/timeout/delay
policy, restart reconciliation, idempotent work claiming, independent item
failure, and polling-visible progress. Completed observations survive failures.

This ADR does not select a framework, worker library, broker, or process topology.
Celery, Redis, Kafka, and similar infrastructure are not assumed; a later
framework exercise must justify each component. Runtime/configuration boundaries
must permit Kubernetes deployment in v2 without redesigning the domain.

## Consequences

- Launch returns promptly after persisting a stable run plan.
- Users may leave and revisit a running evaluation.
- Sequential/parallel conditions and actual concurrency are retained for honest
  performance comparison.
- Process death must be detected and reconciled without overwriting captured
  answers or silently duplicating terminal observations.
- Kubernetes manifests and production orchestration are out of v1.
- Whether cooperative cancellation is inexpensive enough for v1 remains an
  explicit product/framework-phase question; pause/resume is excluded.

See [Architecture](../architecture.md),
[Framework decision inputs](../framework-decision-input.md), and
[Open questions](../open-questions.md).
