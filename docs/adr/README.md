# Architecture Decision Records

ADRs capture the small set of foundation decisions whose reversal would change
the product or system shape. Detailed behavior remains in the linked
specifications.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-independent-multi-product-core-and-adapters.md) | Accepted | Independent multi-product core with product-specific adapters |
| [0002](0002-postgresql-only-persistence.md) | Accepted | PostgreSQL-only application persistence |
| [0003](0003-immutable-observations-and-human-reviewed-baselines.md) | Accepted | Immutable observations and human-reviewed historical baselines |
| [0004](0004-docker-v1-and-durable-background-execution.md) | Accepted | Docker v1, Kubernetes v2, and durable background execution requirements |
| [0005](0005-supported-product-api-evaluation-only-in-v1.md) | Accepted | Supported evaluated-product APIs only in v1 |
| [0006](0006-local-authentication-and-two-role-rbac.md) | Accepted | Local authentication and exactly two v1 roles |
| [0007](0007-django-monolith-and-postgresql-worker.md) | Accepted | Django modular monolith, server-rendered UI, Django ORM/migrations, and PostgreSQL-backed worker |
| [0008](0008-layered-executable-acceptance-harness.md) | Accepted | Layered executable acceptance harness with real PostgreSQL, controlled doubles, selective Playwright, and Docker smoke |

ADR 0007 selects the v1 application architecture using the requirements in
[Framework decision inputs](../framework-decision-input.md) and the analysis in
[Framework selection](../framework-selection.md).

ADR 0008 defines how the future executable harness will independently establish
acceptance evidence. Its detailed design is in
[Executable acceptance harness design](../acceptance-harness-design.md).
