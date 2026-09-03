# StewardBench

**StewardBench — AI Network Operations Evaluation Platform**

StewardBench is an implementation-independent platform for evaluating and
benchmarking AI-driven network-operations systems. It automates repeated
question execution, preserves the resulting evidence, and directs human
attention to answers that changed or failed.

OpsSteward is the first evaluated product and AmLight Production is the first
operational environment. Neither is embedded in StewardBench's core domain
model: the platform is designed for multiple products, builds, environments,
and evaluation targets.

## Why it exists

The current evaluation loop requires an administrator to submit roughly 200
operator questions by hand, review every answer, repeat the process after each
patch or commit, and rediscover what changed. StewardBench v1 focuses on one
workflow:

> Questions → Execute → Capture → Review → Baseline → Re-execute → Compare →
> Review Changes

The initial baseline is intentionally human-reviewed. On later runs,
StewardBench uses exact and conservative semantic comparison to reduce review
to errors, timeouts, material changes, uncertain comparisons, and relevant
GOOD/BAD transitions. A changed answer is not automatically a regression, and
a baseline is observed historical performance—not universal ground truth.

## Status

StewardBench is in the **product and architecture foundation** phase. This
repository currently contains authoritative design documentation only. No
application framework has been selected and no application implementation has
begun.

## Documentation

- [Documentation index](docs/README.md)
- [Product definition](docs/product-definition.md)
- [Architecture](docs/architecture.md)
- [Domain model and invariants](docs/domain-model.md)
- [Evaluation methodology](docs/evaluation-methodology.md)
- [UI/UX specification](docs/ui-ux.md)
- [Question corpus import specification](docs/question-corpus-import.md)
- [Target adapter contract](docs/target-adapter-contract.md)
- [Roadmap](docs/roadmap.md)
- [Framework decision inputs](docs/framework-decision-input.md)
- [Open questions](docs/open-questions.md)
- [Architecture decision records](docs/adr/README.md)

## Roadmap at a glance

- **v1:** Docker, PostgreSQL, local ADMIN/OPERATOR access, corpus import,
  API-based execution, human review, immutable baselines, conservative change
  detection, review triage, and basic trends.
- **v2:** Kubernetes, CI-triggered (non-gating) evaluations, and improvements
  justified by v1 operations.
- **v3+:** possible mature automation API, user-facing CLI, release gating,
  MCP adapters, advanced regrading, and broader analytics.

See the [roadmap](docs/roadmap.md) for authoritative boundaries. The next phase
is product-owner review followed by a separate framework and technology
selection exercise—not implementation.
