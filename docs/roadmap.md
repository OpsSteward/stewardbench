# Roadmap

This roadmap defines release boundaries, not delivery dates. Capabilities move
into a release only through explicit product-owner review. Optional work must
not delay the core v1 workflow.

## StewardBench v1 — core

The central workflow is:

> Questions → Execute → Capture → Review → Baseline → Re-execute → Compare →
> Review Changes

v1 must provide:

- Docker deployment suitable for a developer laptop (including macOS) and a DGX
  node;
- PostgreSQL as the application database in development and deployment;
- local username/password authentication, first-admin bootstrap, and exactly
  ADMIN/OPERATOR roles;
- management of products, environments, evaluation targets, target revisions,
  technical adapter capabilities, and simple execution limits;
- import of the existing question corpus without discarding useful legacy
  evidence;
- stable Questions, temporal QuestionVersions, controlled domain, lightweight
  tags, rationale, and DRAFT/ACTIVE/RETIRED lifecycle;
- lightweight representation of historical time-window fixtures, populated
  progressively and never treated as an infrastructure snapshot or v1 blocker;
- individual, multi-select, and all-matching question execution against one
  target per run;
- sequential and safely bounded parallel background execution;
- an OpsSteward API adapter for questions and, where supported, conversations,
  health, and runtime metadata;
- immutable capture of exact questions, resolved bindings, answers, raw
  responses, returned evidence, timings, and target/build snapshots;
- human GOOD/BAD review, independent review state, append-only comments, and
  VALID/INVALID decisions;
- named immutable baselines with visible review completeness;
- controlled comparison using identical QuestionVersion, binding values, and
  concrete submitted question;
- exact then conservative semantic change detection, with uncertainty surfaced
  as REVIEW REQUIRED;
- question/run/execution views, a high-throughput review workstation, attention
  dashboard, comparison triage, URL-addressable filters, and chronological
  GOOD/BAD trends;
- raw timing sufficient for basic run/latency metrics and later percentiles;
- indefinite retention of evaluation history; and
- CSV table export and complete JSON run export if their implementation remains
  inexpensive after core workflow acceptance.

The first implementation milestones should prove the smallest end-to-end slice,
then scale it to the corpus. Sophisticated evaluators and reporting are not
prerequisites to human baseline creation and comparison.

The accepted v1 implementation architecture is the Django modular monolith,
server-rendered/HTMX UI, Django ORM/migrations, and PostgreSQL-backed worker in
[Framework selection](framework-selection.md). This selection changes no
release boundary in this roadmap.

Run cancellation is unresolved and is listed in
[Open questions](open-questions.md). Pause/resume is not in v1.

## StewardBench v2 — planned direction

Likely v2 work, justified and refined by operational v1 experience:

- Kubernetes deployment without redesigning application boundaries;
- CI-triggered evaluation after a build/deployment, followed by result reporting
  and human review;
- improved semantic comparison and LLM-judge calibration;
- narrowly scoped deterministic evaluators where authoritative answers are
  reliable and inexpensive;
- richer performance analysis, including throughput and p50/p90/p95 views;
- dashboard/reporting improvements based on observed workflows;
- authentication enhancements if operations require them; and
- first-class handling only for capabilities proven valuable during v1.

Initial CI behavior is **deploy → trigger → report → human review**. v2 does not
initially make StewardBench an automatic release gate because changed network
facts may be legitimate.

## StewardBench v3+ — possible directions

These are possibilities, not commitments:

- user-facing evaluation CLI backed by the same application services;
- mature supported automation API;
- sophisticated release gating after trustworthy semantics are established;
- advanced historical regrading without rerunning evaluated products;
- first-class external-event correlation;
- richer artifact and visual-output evaluation with an artifact abstraction;
- MCP interaction adapters;
- advanced resolver infrastructure;
- broader multi-product benchmarking;
- additional authoritative-source evaluators;
- object storage if actual artifact volume requires it;
- additional identity/authentication integrations; and
- advanced analytics or LLM analysis over retained/exported history.

## Explicit sequencing guardrails

- Do not replace or expand the accepted v1 framework/process architecture
  without an explicit decision and ADR.
- Do not build Kubernetes before the Docker v1 workflow works.
- Do not require CI, MCP, a CLI, comprehensive API coverage, object storage, or
  independent network-system access to complete v1.
- Do not make optional exports or sophisticated charts block execution, review,
  baseline, and comparison.
- Do not promote answer-change detection into automatic correctness or release
  gating without sufficient operational evidence.
