# ADR 0002: PostgreSQL-only persistence

- Status: Accepted
- Date: 2026-09-03

## Context

StewardBench is a relational, history-heavy application with immutable evidence,
temporal versions, filtering, attributed state changes, and some flexible raw
payloads. Supporting a second development-only database would weaken or delay
use of the same constraints and data types used in deployment.

## Decision

PostgreSQL is the only supported StewardBench application database from day one,
including development. Core entities and relationships use relational modeling.
JSONB is used selectively for variable-shaped raw responses, evidence, runtime
metadata, and evaluator payloads. Schema migrations are first-class and
version-controlled.

v1 stores textual and structured evidence in PostgreSQL. It does not introduce
object storage, routine deletion, archival, partitioning, or retention-policy
infrastructure.

## Consequences

- SQLite compatibility is not an implementation requirement.
- Tests and development must exercise PostgreSQL semantics and constraints.
- Frequently filtered identity/state fields stay typed and relational rather
  than hidden in JSON.
- Exact responses and flexible evidence can be retained without turning the
  full domain into document records.
- Docker development includes PostgreSQL.
- If future binary artifact volume proves the need, object storage requires a
  later decision and metadata abstraction; it is not prebuilt.

See [Architecture](../architecture.md) and [Domain model](../domain-model.md).
