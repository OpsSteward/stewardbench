# StewardBench

[![Stability](https://img.shields.io/badge/stability-beta-yellow.svg)](https://github.com/OpsSteward/stewardbench)
[![Version](https://img.shields.io/badge/version-v1.0.0-blue.svg)](https://github.com/OpsSteward/stewardbench/releases/tag/v1.0.0)
[![Release](https://img.shields.io/badge/release-v1.0.0-brightgreen.svg)](https://github.com/OpsSteward/stewardbench/releases/tag/v1.0.0)
[![Tests](https://img.shields.io/badge/tests-197%20passing-brightgreen.svg)](https://github.com/OpsSteward/stewardbench)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](https://github.com/OpsSteward/stewardbench)
[![Django](https://img.shields.io/badge/Django-5.2%20LTS-blue.svg)](https://github.com/OpsSteward/stewardbench)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-blue.svg)](https://github.com/OpsSteward/stewardbench)

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

The initial baseline is intentionally human-reviewed. Exact comparison records
whether deliberately narrow normalized answer text changed, without calling a
change a regression or a correctness result. M7 adds separate conservative
semantic triage: only established equivalence can resolve an exact
change-only review requirement; uncertainty and comparator failure remain
visible for review. A baseline is observed historical performance—not
universal ground truth.

## Status

StewardBench v1.0.0 is released. Its first live-certified evaluated target is
OpsSteward v1.0.4 Production, using the supported session-cookie `/api/chat`
and `/api/version` contract. Consult the [release acceptance report](docs/releases/v1.0.0-acceptance.md)
for the retained live evidence and remaining limitations.

M0 provides the runnable authenticated foundation. M1 adds the managed,
product-neutral catalog. M2 adds the approved, non-destructive workbook import,
immutable source provenance, deterministic draft Questions, and visibly
uncontrolled legacy observations. M3 adds frozen Run/Execution capture through
the deterministic fake-target adapter. M4 hardens it with PostgreSQL claim
leases, multiple workers, sequential or bounded parallel execution,
target-revision-wide capacity, and conservative ambiguous-call recovery. M5
adds attributed append-only human review, comments, validity decisions, and
retry/rerun history. M6 adds named immutable Baselines, controlled replay using
the exact historical QuestionVersion/bindings/concrete question, and versioned
exact comparison. M7 adds append-only, versioned semantic triage with a
deterministic acceptance comparator; the real provider/model remains an
explicit open decision. M8 adds versioned ordered conversation scenarios, a
durable shared target-session attempt, per-turn transcript/review/comparison
evidence, and full retries from Turn 1. Real OpsSteward wire-contract
certification is an M10 operational-integration responsibility and remains
explicitly unclaimed until approved wire evidence and credentials are available.

## Run with Docker

Requirements: Docker Engine with Compose, and a shell for generating local
secret values.

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Put the generated value in `.env` as `DJANGO_SECRET_KEY` and replace the example
database password. Then build, start PostgreSQL, apply migrations explicitly,
bootstrap the first product ADMIN, and start the two application processes:

```bash
docker compose build
docker compose up -d db
docker compose run --rm web python manage.py migrate --noinput
docker compose run --rm -e STEWARDBENCH_ADMIN_PASSWORD web \
  python manage.py create_stewardbench_admin \
  --username your-admin --password-env STEWARDBENCH_ADMIN_PASSWORD
docker compose up -d web worker
```

The bootstrap command reads `STEWARDBENCH_ADMIN_PASSWORD` from the invoking
shell without printing it. Omitting `--password-env` uses a hidden interactive
prompt instead. The command refuses to create another account when an ADMIN
already exists and never changes an existing account.

Open <http://localhost:8000/>. After login, an ADMIN can create, activate,
deactivate, re-role, and reset passwords for later users from **Users**.
OPERATOR accounts can enter the application but have no administrative mutation
access. ADMIN can curate the M1 catalog from **Questions**, **Products**,
**Environments**, **Targets**, **Domains**, **Tags**, and **Historical
fixtures**. OPERATOR can browse those same catalog records read-only.

M2 corpus import is an explicit administrative command. Dry-run is the default;
apply requires both `--apply` and an existing ADMIN username:

```bash
docker compose run --rm web python manage.py import_stewardbench_workbook --dry-run
docker compose run --rm web python manage.py import_stewardbench_workbook \
  --apply --actor your-admin
```

Both commands verify the repository workbook against the approved mapping v1
checksum. Applied source history is browsable under **Corpus imports**.

See [development and deployment instructions](docs/development.md) for checks,
configuration, the worker foundation, Docker smoke, and DGX guidance.

## Documentation

- [Agent operating contract](AGENTS.md)
- [StewardBench development skill](skills/stewardbench-development/SKILL.md)
- [StewardBench QA/acceptance skill](skills/stewardbench-qa/SKILL.md)
- [Documentation index](docs/README.md)
- [Product definition](docs/product-definition.md)
- [Architecture](docs/architecture.md)
- [Domain model and invariants](docs/domain-model.md)
- [Evaluation methodology](docs/evaluation-methodology.md)
- [UI/UX specification](docs/ui-ux.md)
- [Question corpus import specification](docs/question-corpus-import.md)
- [Target adapter contract](docs/target-adapter-contract.md)
- [Roadmap](docs/roadmap.md)
- [Framework selection](docs/framework-selection.md)
- [Executable acceptance harness design](docs/acceptance-harness-design.md)
- [v1 implementation milestones](docs/implementation-milestones.md)
- [Framework decision inputs](docs/framework-decision-input.md)
- [Open questions](docs/open-questions.md)
- [Architecture decision records](docs/adr/README.md)

## Roadmap at a glance

- **v1:** Docker, PostgreSQL, local ADMIN/OPERATOR access, corpus import,
  API-based execution, human review, immutable baselines, conservative exact
  and semantic triage, review workflows, and basic trends.
- **v2:** Kubernetes, CI-triggered (non-gating) evaluations, and improvements
  justified by v1 operations.
- **v3+:** possible mature automation API, user-facing CLI, release gating,
  MCP adapters, advanced regrading, and broader analytics.

See the [roadmap](docs/roadmap.md) for authoritative boundaries. The framework
and future executable acceptance-harness architectures are now documented.
The authoritative v1 implementation milestone plan pairs each product increment
with development tests and independent acceptance evidence. The repository-
specific development and independent QA/acceptance skills govern implementation
and acceptance work. M0 through M11 are accepted; current work is operational
use, maintenance, and evidence-driven lessons learned.

M10 also records external response latency, target-reported token telemetry when
available, and runtime/model context independently from human answer quality.
This supports controlled build comparisons during OpsSteward routing/model
optimization without creating a composite score or automatic release gate.
