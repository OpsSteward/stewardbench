# ADR 0001: Independent multi-product core and adapters

- Status: Accepted
- Date: 2026-09-03

## Context

OpsSteward is the first evaluated product and AmLight Production is the first
environment, but enduring operator questions should survive changes in product
implementation and eventually run against other compatible products. A target
is a stable deployment/interface identity while build and endpoint/configuration
identity change independently over time.

Embedding OpsSteward routes, AmLight assumptions, or deployed release values in
questions or core entities would prevent trustworthy longitudinal and
multi-product use.

## Decision

StewardBench is an independent product with product-neutral core entities for
Product, ProductBuild/BuildSnapshot, Environment, EvaluationTarget,
TargetRevision, Question/QuestionVersion, EvaluationRun, Execution, evaluation,
review, Baseline, and Comparison.

Evaluated-product API behavior is isolated behind versioned target adapters.
Canonical questions contain operator-language specifications and binding
requirements, not product/API-version payload fields. A TargetRevision selects
technical adapter capabilities and configuration. Each run/execution freezes
the effective target revision and observed/admin-declared build identity;
unknown metadata is allowed and never fabricated.

Resolvers and answer evaluators are separate boundaries. The adapter neither
derives network truth nor queries GitHub or operational data systems to
reconstruct an answer/build.

## Consequences

- OpsSteward and AmLight are initial records/adapter configuration, not special
  domain types.
- API changes between OpsSteward v1/v2 do not version the canonical question.
- One target can run many builds and one build can appear on multiple targets.
- Changing endpoint/configuration creates a new TargetRevision and cannot rewrite
  history.
- Adding another product requires an adapter and target configuration but should
  not redesign run/review/baseline concepts.
- This boundary adds normalization work, but keeps that work explicit and
  versioned.

See [Architecture](../architecture.md), [Domain model](../domain-model.md), and
[Target adapter contract](../target-adapter-contract.md).
