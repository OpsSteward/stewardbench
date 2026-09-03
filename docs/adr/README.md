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

No ADR selects an application or frontend framework. That decision belongs to a
separate phase after product-owner review; see
[Framework decision inputs](../framework-decision-input.md).
