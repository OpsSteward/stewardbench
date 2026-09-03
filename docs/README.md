# StewardBench documentation

This directory is the authoritative product and architecture foundation for
StewardBench v1. The root [README](../README.md) is an introduction; the
documents below control implementation decisions.

## Authority and precedence

When documents appear to conflict, use this order:

1. accepted Architecture Decision Records (ADRs) for the decision they cover;
2. the product, domain, architecture, evaluation, and UI specifications in this
   directory;
3. the roadmap for release boundaries;
4. historical/reference material.

Reference material describes how the project arrived here. It is not current
authority when it conflicts with an accepted StewardBench decision. Genuine
unresolved matters are listed in [Open questions](open-questions.md); an
implementation agent must not silently decide them when the choice changes
product behavior or architecture.

## Document map

| Document | Purpose |
| --- | --- |
| [Product definition](product-definition.md) | Identity, users, workflows, scope, non-goals, philosophy, and glossary |
| [Architecture](architecture.md) | Context, boundaries, components, lifecycles, background work, storage, security, and extensibility |
| [Domain model](domain-model.md) | Conceptual entities, relationships, state dimensions, and invariants |
| [Evaluation methodology](evaluation-methodology.md) | Trust hierarchy, human review, evaluators, baseline comparison, semantic change, and conversation rules |
| [UI/UX specification](ui-ux.md) | Navigation, views, filters, review workstation, charts, and visual identity |
| [Question corpus import](question-corpus-import.md) | Non-destructive workbook mapping and legacy-history treatment |
| [Target adapter contract](target-adapter-contract.md) | Product-independent adapter behavior and proposed OpsSteward metadata contract |
| [Roadmap](roadmap.md) | v1, v2, and v3+ boundaries |
| [Framework selection](framework-selection.md) | Weighted technology comparison and selected v1 application, UI, persistence, worker, Docker, and testing architecture |
| [Executable acceptance harness design](acceptance-harness-design.md) | Layered evidence architecture, deterministic doubles, PostgreSQL concurrency strategy, acceptance catalog, and implementation sequence |
| [v1 implementation milestones](implementation-milestones.md) | Acceptance-first staged implementation plan, dependencies, schema/UI/harness sequencing, and complete scenario traceability |
| [M0 development and deployment](development.md) | Implemented Docker, configuration, bootstrap, worker, testing, and smoke procedures |
| [Framework decision inputs](framework-decision-input.md) | Requirements used by the completed technology-selection phase |
| [Open questions](open-questions.md) | Only decisions that still need product-owner or integration evidence |
| [ADRs](adr/README.md) | Durable architectural decisions |
| [Brand asset specification](assets/brand/README.md) | Approved identity and required future assets |
| [Reference material](reference/README.md) | Status and handling of historical source documents |

## Core rule

Optimize for the smallest v1 that makes repeat evaluation materially faster:
execute selected questions, preserve exact evidence and identity, compare with
a human-reviewed historical baseline, and surface the small subset requiring
administrator attention.
