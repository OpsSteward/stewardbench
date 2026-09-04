# StewardBench v1 implementation milestones

Status: Authoritative v1 implementation sequence

This plan translates the accepted product, Django/PostgreSQL architecture,
development and QA contracts, executable acceptance-harness design, and all 35
initial acceptance scenarios into small end-to-end delivery increments. It does
not authorize implementation by itself and does not change an accepted ADR.

## Authority basis

This sequence is subordinate to the repository [operating contract](../AGENTS.md)
and the [accepted ADRs](adr/README.md). Product behavior comes from the
[product definition](product-definition.md), [architecture](architecture.md),
[domain model](domain-model.md), [evaluation methodology](evaluation-methodology.md),
and [UI/UX specification](ui-ux.md). Release boundaries and specialized behavior
come from the [roadmap](roadmap.md), [corpus import specification](question-corpus-import.md),
and [target adapter contract](target-adapter-contract.md). The selected stack is
defined by [framework selection](framework-selection.md), and the 35 scenario
obligations and evidence layers come from the
[acceptance harness design](acceptance-harness-design.md).

Implementation follows the
[development skill](../skills/stewardbench-development/SKILL.md); independent
evidence follows the [QA skill](../skills/stewardbench-qa/SKILL.md). The
[open questions](open-questions.md) remain unresolved unless this plan names an
explicit decision checkpoint. This document sequences those authorities; it
does not override them.

The governing delivery rule is:

> Implement one observable capability, prove it independently, and only then
> let later capabilities depend on it.

A milestone is complete only when its development validation and independent
acceptance gate both pass. Code existence, a green unit-test subset, or a
partially exercised UI is not milestone completion.

## Outcome and sequencing principles

The v1 sequence establishes the shortest trustworthy path through the product:

> authenticate → curate questions → import the corpus → execute durably →
> review → baseline → compare → triage → complete optional evaluation and
> operational surfaces → release acceptance

Each milestone is a vertical product increment. Schema, services, UI, tests,
and harness support enter together only when needed by that increment. The
executable harness grows alongside the application; it is never deferred until
the application is otherwise complete.

The implementation must continue to honor these sequencing constraints:

- real PostgreSQL is used from M0 and for every persistence acceptance gate;
- the first executable slice uses the reusable deterministic fake target;
- the worker's process, locking, concurrency, and recovery behavior is accepted
  in M4 before review, baseline, and comparison features depend on it;
- the human review and exact-comparison value loop works before semantic-model
  or LLM-judge sophistication;
- target, comparator, evaluator, and judge doubles establish repeatable offline
  acceptance, but cannot be presented as live-product/provider certification;
- UI for each operational capability lands with that capability, not in a final
  presentation phase; and
- M11 introduces no major product feature. It stabilizes and accepts the
  already feature-complete M10 build.

## Milestone overview

| Milestone | End-to-end objective | Primary risk | Risk |
| --- | --- | --- | --- |
| M0 — Runnable authenticated foundation | Run the selected Docker/Django/PostgreSQL shape and enforce the two-role identity boundary. | Security/configuration bootstrap | MEDIUM |
| M1 — Managed catalog and target configuration | Curate product-neutral questions and versioned target configuration through an authenticated UI. | Temporal identity and authorization | MEDIUM |
| M2 — Reconciled source corpus | Import the real workbook non-destructively into draft canonical data and visibly separate legacy history. | Ambiguous source semantics and Unicode/provenance loss | HIGH |
| M3 — First durable executable slice | Launch one or many frozen questions and capture normalized observations through the fake-target adapter. | Adapter boundary and immutable request identity | HIGH |
| M4 — Proven durable worker | Execute sequentially or in bounded parallel with safe claims, restart reconciliation, and independent failure preservation. | Concurrency and ambiguous remote calls | HIGH |
| M5 — Human review and historical integrity | Review, comment on, invalidate, retry, and rerun observations without rewriting history. | Append-only corrections and immutable evidence | HIGH |
| M6 — Baselines and exact controlled comparison | Complete the first value loop: review → baseline → controlled replay → exact change triage. | Frozen identity and non-comparability | HIGH |
| M7 — Conservative semantic triage | Classify unequal answers conservatively and require review for material, uncertain, or failed comparison. | Dangerous false equivalence and provider calibration | HIGH |
| M8 — Ordered conversation scenarios | Run, retain, review, compare, and completely retry a multi-turn session from turn 1. | Session continuity and partial protocol failure | HIGH |
| M9 — Independent evaluators and LLM judge | Add versioned advisory automation without changing human authority or product outcomes. | Provider failures and signal conflation | MEDIUM |
| M10 — Operational experience complete | Finish attention dashboards, trends, filters, exports, trust-boundary hardening, and real OpsSteward adapter certification. | Cross-feature projections, secrets, and integration drift | HIGH |
| M11 — v1 release acceptance | Prove a fresh, migrated, restart-safe Docker installation and close the complete acceptance catalog. | Upgrade/deployment interaction and residual defects | HIGH |

Risk class controls the depth and independence of acceptance evidence; it does
not assign importance or criticality to a Product or Question.

## Dependency graph

```text
M0
 |
 v
M1 -----> M2 ------------------------------+
 |                                           |
 v                                           |
M3                                           |
 |                                           |
 v                                           |
M4                                           |
 |                                           |
 v                                           |
M5 -----> M9 ----------------------+         |
 |                                 |         |
 v                                 |         |
M6 -----> M7 ----------------------+         |
 |                                 |         |
 +------> M8 ----------------------+         |
                                   v         v
                                      M10
                                       |
                                       v
                                      M11
```

M2 corpus work may proceed after M1 while M3/M4 use small synthetic Questions.
M9 may proceed after M5 while M6–M8 proceed, because evaluator persistence is
orthogonal to comparison and conversation orchestration. M7 and M8 both require
M6: semantic results build on the exact comparison gate, and conversation
acceptance must preserve the same baseline identity rules. Parallel work must
remain on separate, reviewable feature branches and may merge only after its
declared prerequisites pass.

## Milestone contract

For every milestone, implementation follows this loop:

```text
implementation
  → development validation
  → independent acceptance
  → failure-domain classification
  → narrow remediation
  → regression test
  → re-acceptance
```

Independent acceptance reports PASS, FAIL, or BLOCKED. BLOCKED is not PASS. A
harness, fixture, mapping, target, evaluator, comparator, database, or
environment defect is repaired in its own domain; correct application behavior
must not be changed merely to satisfy a defective check. Each gate records the
authority, environment, build SHA, migration leaf, scenario/fixture versions,
commands, primary and corroborating evidence, result, and attribution.

### M0 — Runnable authenticated foundation

**Capability.** A user can start the documented topology, apply migrations,
bootstrap the first ADMIN, log in or out, manage a later user, and navigate an
authenticated server-rendered shell. An OPERATOR can enter the application but
cannot gain administrative capability.

**Domain and storage.** Create only Django authentication-related application
state needed for a local User with exactly one explicit StewardBench role,
ADMIN or OPERATOR. Use PostgreSQL from the first migration. Framework staff,
superuser, group, and model-permission flags do not create product roles.

**Application and UI.** Establish the Django modular monolith, settings and
authentication boundary, service-level role policy, first-admin bootstrap,
login/logout, ADMIN-only user management, inactive-user behavior, base
navigation/breadcrumb/layout, and authenticated health/readiness basics. Use a
text `StewardBench` wordmark and neutral documented styling; do not fabricate
the unfinished Benchmark Mark artwork.

**Runtime.** Create one application image with distinct web and worker entry
points plus PostgreSQL in Compose. The worker may expose only a readiness-safe
idle loop at this stage. Migrations are an explicit one-shot operation rather
than an implicit race among long-running containers.

**Harness and development tests.** Establish pytest/pytest-django, stable
scenario IDs, disposable real-PostgreSQL setup, the `minimal-domain` identity
subset, migration-from-zero checks, Django request/service authorization tests,
and synthetic secret canaries. No fake target is needed yet. Development tests
cover role validation, bootstrap idempotence/safety, password/session behavior,
CSRF on implemented mutations, anonymous denial, and inactive users.

**Primary acceptance scenarios.** ACC-AUTH-001, ACC-AUTH-002, and
ACC-RBAC-002. ACC-RBAC-002 is limited to the representative mutations that
exist in M0, while its unsupported-role and no-extra-role assertions are fully
mandatory. ACC-RBAC-001 begins an expanding authorization matrix here, but its
complete catalog-wide gate is assigned to M10.

**Acceptance evidence.** A migrated PostgreSQL schema, safely repeatable
bootstrap outcome, real password verification, HTTP/session observations,
before/after database fingerprints for denied mutations, role-change behavior,
and a minimal Compose process/readiness probe.

**Non-goals.** No Product, target, question, run, worker dispatch, Django Admin
product workflow, SPA/API service, broker, CI, Kubernetes, or branding artwork.

**Exit criteria.** The three primary scenarios PASS on PostgreSQL; anonymous
and inactive access is denied; exactly two product roles are enforced at both
service and request boundaries; the application shell starts with explicit
migrations; relevant development tests and migration checks pass; no plaintext
bootstrap secret is durable; documentation and `git diff --check` pass.

**Open dependencies.** Select supported Django/Python patch versions,
production HTTP server, and minimal styling/build-free static-asset approach at
implementation start. These are dependency choices within ADR 0007, not a
license to alter the architecture.

### M1 — Managed catalog and target configuration

**Capability.** An ADMIN can manage Products, Environments, stable Evaluation
Targets and immutable TargetRevisions, and can create, version, activate,
retire, search, filter, and inspect product-neutral Questions. An OPERATOR has
the corresponding read-only catalog.

**Domain and storage.** Introduce Product, Environment, EvaluationTarget,
TargetRevision, Question, QuestionVersion, controlled domain, tags,
BindingDefinition, and the lightweight optional HistoricalFixture. A new target
configuration creates a revision. A new evaluation-relevant question definition
creates a temporally bounded version. Domain is required before activation;
unknown build identity and an incomplete fixture library remain valid.

**Application and UI.** Add service-owned catalog and revision workflows,
server-side ADMIN enforcement, pagination, URL-addressable question filters,
question list/detail/version history, Product/Environment/Target list/detail,
target revision history and execution-policy forms, and ADMIN question/target
actions. Credential data is an external reference/status only and is never
displayed or persisted as a usable secret.

**Harness and development tests.** Extend `minimal-domain` fixtures and the
request/RBAC matrix. Add PostgreSQL tests for exact version references,
temporal boundaries/current-version rules chosen by the schema, target revision
immutability, Unicode tags/text, activation validation, credential-reference
handling, and forbidden direct mutation. No executable target double is needed.

**Primary acceptance scenarios.** None of the 35 catalog scenarios can yet run
to its complete PASS condition: ACC-QVER-001 requires completed executions.
M1 nevertheless has mandatory milestone-specific domain, PostgreSQL, request,
and authorization acceptance for the catalog behavior above. ACC-QVER-001 is
prepared here and becomes primary in M3.

**Acceptance evidence.** Rendered and persisted catalog histories, PostgreSQL
constraint/service probes, exact Unicode round trips, URL/filter record-set
reconciliation, target revision before/after snapshots, and ADMIN/OPERATOR
request outcomes.

**Non-goals.** No workbook import, run launch, adapter call, dynamic resolver,
operator-capability flags, comprehensive taxonomy, priority/criticality,
arbitrary experiment parameters, or product-specific request fields in a
QuestionVersion.

**Exit criteria.** Catalog CRUD/version transitions are attributed and accepted;
old versions/revisions remain readable and unchanged; ACTIVE eligibility rules
and exact two-role policy pass; URLs expose enough UI to exercise each
capability; migrations apply from M0 with representative data preserved; all
M1 checks PASS.

**Open dependencies.** Controlled domain, binding, duplicate, and conversation
mapping values needed for the workbook require the separate source-owner/admin
review described in M2. They are not inferred here.

### M2 — Reconciled source corpus

**Capability.** An ADMIN can inspect and execute an approved, idempotent import
of `v2-dev-troubleshooting.xlsx`, review its reconciliation report, then
explicitly activate sufficiently mapped Questions. Legacy observations remain
visibly uncontrolled history rather than fabricated Executions.

**Domain and storage.** Introduce LegacyImportBatch, row/cell mapping
provenance, LegacyObservation, mapping warnings/classification, checksum and
mapping-version identity, and explicit unknown/missing markers. Do not add
general provenance requirements to every Question. Keep import staging and
activation separate.

**Application and UI.** Implement read-only workbook inspection, reviewed
mapping input, transactional/idempotent import, draft Question creation/linking,
legacy-history presentation, and a per-sheet/total reconciliation report. The
source file remains unchanged. `Expected Answer` is guidance, raw `Acceptable`
is not automatically GOOD/BAD, and import actor is not fabricated as historical
reviewer.

**Harness and development tests.** Implement the real-workbook fixture and hash
guard, source inventory/reconciliation, representative raw-cell and Unicode
assertions, ambiguity/manual-mapping cases, duplicate/separator handling, and
same-checksum/mapping-version idempotency. A tiny synthetic edge workbook is
permitted only for cases absent from the real source.

**Primary acceptance scenario.** ACC-IMPORT-001.

**Acceptance evidence.** SHA-256 before and after; exact five-sheet inventory;
reconciliation of 39 known, 4 KB/RAG, 17 Interface Issues, 13 random, and 186
nonblank target-question source rows/cells; preservation of the 15 target-sheet
separators; representative PostgreSQL records and provenance; created/linked/
deferred/skipped/warning/error counts; and a second idempotent run.

**Non-goals.** No destructive workbook rewrite, guessed rows 155–156 merge,
guessed conversations/domains/bindings, automatic semantic deduplication,
unapproved Acceptable mapping, generic experiment framework, random-question
generation, or promotion of Interface Issues into questions by default.

**Exit criteria.** ACC-IMPORT-001 PASS; every substantive row is created,
linked, manually deferred, or reported with a reason; source counts and samples
reconcile to PostgreSQL; ambiguities remain explicit; imported executable
candidates stay DRAFT until their required mappings are approved; upgrade from
M1 preserves catalog state; no source byte changes.

**Open dependencies.** Source-owner/admin approval is required for Acceptable
semantics/attribution, timing/token units, rows 155–156, conversation grouping,
variables/bindings, controlled domains, cross-sheet identity, and Interface
Issues treatment. The milestone may implement and accept inspection/staging
before those decisions, but cannot PASS the approved-mapping import scenario
while the mapping fixture is unavailable; that outcome is BLOCKED.

### M3 — First durable executable slice

**Capability.** An ADMIN can select one, many, or all matching ACTIVE questions,
launch promptly against one target, leave the page, and observe a dedicated
worker complete a small sequential run through the deterministic fake target.
The run detail displays frozen plan, progress, exact question, response,
evidence, timing, target revision, and build identity/Unknown.

**Domain and storage.** Introduce EvaluationRun, stable run-manifest membership,
Execution intent/observation, ResolvedBinding, TargetSnapshot, BuildSnapshot,
adapter and normalizer identity, exact submitted question, raw/display answer,
raw response/evidence, outcome and timing fields, source correlation ID, and
sanitized diagnostic classification. Terminal observation fields become
immutable. Admin-declared build identity is the initial fallback; unknown is a
first-class value.

**Application and UI.** Implement launch services and one-target selection
snapshot, binding substitution for FIXED_ADMIN values, a normalized adapter
registry/contract, the minimal dedicated worker claim/execute/complete loop for
small sequential runs, run list/detail, polling progress, execution detail/raw
evidence, and advisory health. Launch is a short transaction and never performs
the remote call in the request process.

Implement normalized runtime-metadata retrieval now against fake-target modes:
runtime-discovered values and admin declarations are both preserved with source
and conflict visibility; absence is non-fatal. Each run/execution freezes the
effective observation. The actual OpsSteward metadata route remains optional
and may be added after its wire contract is confirmed. GitHub lookup is
prohibited.

**Fake target and harness.** Introduce the single reusable fake HTTP target,
minimal scenario/control schema, per-run synthetic control token, and
independent append-only journal. Required modes are valid complete Unicode
response with evidence/correlation, metadata present/absent/malformed,
authentication rejection, refusal/HTTP error, timeout, malformed JSON/schema,
wrong/incomplete 200 response, and bounded raw payload capture. Validate the
fake journal and preconditions independently.

**Development tests.** Cover manifest selection across pagination and later
catalog edits, launch authorization/transactionality, adapter normalization and
error mapping, exact raw/display persistence, bindings, timeout, complete-answer
requirement, build-source fallback/conflict, unknown metadata, terminal-write
idempotence, safe rendering basics, and target secret redaction primitives.

**Primary acceptance scenarios.** ACC-QVER-001, ACC-RUN-001, ACC-ADAPT-001,
and ACC-ADAPT-002.

**Acceptance evidence.** Prompt HTTP launch response; independently enumerated
manifest IDs; PostgreSQL run/execution snapshots; one fake-target journal entry
per intended request; exact Unicode/raw/evidence/correlation fields; adapter and
normalizer versions; metadata source/unknown behavior; normalized failure
classes; and no human quality judgment synthesized from transport outcomes.

**Non-goals.** No parallel dispatch, multi-worker claim race, full restart
matrix, semantic comparison, real provider, conversation, multi-target fan-out,
live production execution, dynamic resolver, or public execution API.

**Exit criteria.** The four primary scenarios PASS; one small background run is
durable and browser-independent; exact versions/selections survive edits;
complete valid responses become SUCCESS while malformed/incomplete responses
do not; target failures remain distinct from BAD; terminal capture is
immutable; migration from M2 representative state passes.

**Open dependencies.** Begin bounded discovery of the exact OpsSteward v1 and
v2 health, authentication, question, completion, error, evidence, conversation,
and metadata contracts before or during M3. M3's offline architecture can PASS
against the normalized fake path without inventing those wire shapes, but M10
cannot exit until the required real question adapter variant(s) are certified.
One adapter may negotiate variants only if evidence shows that is safe;
otherwise implement separately versioned OpsSteward v1 and v2 adapters.

Run cancellation is deferred from v1 by product-owner decision. It is not an M0
requirement and must not block M3. Pause/resume is also excluded. If later worker
evidence shows safe cooperative cancellation is effectively free, define and
review its state/evidence semantics and acceptance coverage before adding it;
completed and in-flight observations must remain preserved.

### M4 — Proven durable worker

**Capability.** Admins can run the frozen corpus sequentially or with bounded
parallelism while navigating away. Two worker processes cannot duplicate work,
one item failure does not erase siblings, and restart reconciliation never
silently repeats an ambiguously accepted call.

**Domain and storage.** Extend run/work state only as required for claim owner
and token, lease/heartbeat or equivalent reconciliation metadata, attempt phase,
aggregate target-concurrency accounting, actual mode/concurrency, and explicit
benchmark-infrastructure errors. Preserve PENDING/RUNNING/terminal lifecycle
and prohibit terminal overwrite.

**Application and UI.** Implement short `SKIP LOCKED` claim transactions,
release database locks before target calls, bounded I/O dispatch, sequential
mode, target-wide limits across simultaneous runs, timeout/delay, matching-owner
completion, stale-claim classification, safe reclaim, ambiguous-attempt
finalization, partial-run aggregate finalization, and accurate progress/status
polling. The worker remains a narrow run dispatcher, not a general task system.

**Fake target and harness.** Add delayed/barrier-blocked responses, deadline
exceeding behavior, disconnect before and after acceptance, deliberately
ambiguous accepted calls, active/max concurrency counters, lifecycle
timestamps, per-correlation counts, and process barriers. Add two-worker,
sequential, target-cap, partial-failure, and three restart-point orchestration
using real OS processes and PostgreSQL.

**Development tests.** Exercise claim uniqueness/current ownership, transaction
and lock duration, terminal races, lease expiry, safe versus ambiguous recovery,
target-wide capacity accounting, per-item timeout, delay, run finalization, and
projection consistency. Thread tests may cover local accounting but cannot
replace process-level crash evidence.

**Primary acceptance scenarios.** ACC-WORKER-001, ACC-WORKER-002,
ACC-WORKER-003, and ACC-WORKER-004.

**Acceptance evidence.** PostgreSQL lock/claim/lease rows during calls, worker
process exit/barrier records, fake-target request counts and observed maximum
concurrency, immutable terminal snapshots, per-item outcomes, run aggregates,
and proof that safe pre-call reclaim creates one call while accepted ambiguity
creates an explicit ERROR and no resubmission.

**Non-goals.** No broker, generic scheduling, adaptive throttling, arbitrary
task routing, worker autoscaling, Kubernetes, silent automatic remote retry,
pause/resume, or cancellation.

**Exit criteria.** All four worker scenarios PASS with real PostgreSQL and at
least two real worker processes; sequential maximum is one; target maximum is
observed across runs; locks are not held during remote calls; restart cases are
deterministic; one failure preserves siblings; progress and final state match
persisted work; no unresolved failure is misattributed to the application or
harness.

**Open dependencies.** Select the minimal cross-platform process-control and
fake-target HTTP dependencies defined as harness open questions. If safe
ambiguous-call behavior cannot be represented without silent resubmission or
history corruption, stop for architecture review.

### M5 — Human review and historical integrity

**Capability.** An ADMIN can review terminal observations as GOOD or BAD,
complete error triage without inventing judgment, append comments, change
validity by attributed decisions, and retry/rerun into new history. An OPERATOR
can inspect the same evidence but cannot mutate it.

**Domain and storage.** Introduce HumanReview with append-only correction links,
ReviewTracking events/projection, Comment, ExecutionValidityDecision, and the
minimal immutable AutomatedEvaluationResult and LLMJudgeResult envelopes needed
to prove that later human actions do not overwrite independent signals.
Provider invocation/configuration remains M9. Source run/execution links support
retry and rerun.

**Application and UI.** Add review/comment/validity/retry/rerun services and
server-side authorization; the execution review workstation; exact question,
answer, identity, and collapsed raw evidence; GOOD/BAD plus correction history;
REQUIRED/REVIEWED handling with no-judgment infrastructure triage; append-only
Unicode comments; validity history; related attempts; and stable previous/next
queue navigation. Retry one and rerun selected/all preview and create new Runs.

**Harness and development tests.** Add reviewed/error/invalid fixtures,
before/after canonical observation snapshots, stale completion races, correction
history, validity denominator exclusions, stable review queue changes, Unicode
comments, direct OPERATOR mutations, and explicit new target request identity
for user retry. Seed evaluator/judge records to prove independence without
calling a provider.

**Primary acceptance scenarios.** ACC-RETRY-001 and ACC-REVIEW-001.
ACC-VALID-001 begins here, but its complete baseline/comparison preservation
case becomes mandatory in M6 after those records exist.

**Acceptance evidence.** Old/new Run and Execution IDs and source links;
byte/value-identical source observations; appended reviewer/actor/timestamps;
REVIEWED paired with GOOD, BAD, and absent judgment; unchanged automated
records; retained INVALID evidence; independent metric denominators; baseline
warning hooks; UI/request denial and unchanged DB for OPERATOR.

**Non-goals.** No voting, adjudication, manual 1–5 score, structured invalid
reason taxonomy, comment editing/threads, retry-one-conversation-turn, reopening
completed runs, bulk regrading, or baseline/comparison behavior.

**Exit criteria.** The two primary scenarios PASS; milestone-specific validity
acceptance also passes; the first tedious but
functional review workflow is usable; transport failure never synthesizes BAD;
corrections append; INVALID remains visible and is excluded only from specified
quality metrics; retry/rerun creates deliberate new calls/history; workstation
navigation cannot silently skip items; migrations preserve M3/M4 observations.

**Open dependencies.** None for provider invocation: seeded normalized result
records are sufficient to establish review independence. Actual evaluator/judge
provider choices remain M9 dependencies.

### M6 — Baselines and exact controlled comparison

**Capability.** An ADMIN can promote a completed reviewed or partially reviewed
run to a named immutable Baseline, launch a controlled replay, and inspect exact
UNCHANGED, conservatively changed, and NON_COMPARABLE items with baseline and
current answers together.

**Domain and storage.** Introduce Baseline, immutable captured membership,
attributed active-state history, Comparison, ComparisonItem, comparison pipeline
identity, exact-equality outcome, comparability cause, and frozen-baseline
binding mode. Unequal comparable pairs remain conservatively CHANGED/REQUIRED
until M7 can establish semantic equivalence; no guessed equivalence is allowed.

**Application and UI.** Implement promotion with visible total/success/reviewed/
unreviewed/invalid/error/timeout completeness; activation/deactivation without
deletion; controlled replay that copies exact QuestionVersion, bindings, and
submitted question; comparability gates; normalized exact equality; baseline
list/detail; comparison summary/table; NON_COMPARABLE explanations; and
side-by-side baseline/current review. Later invalidation flags baseline
attention without rewriting membership or prior comparison.

**Fake target and harness.** Add fixed equal/unequal answer scripts and frozen-
binding valid/invalid modes. Add `reviewed-baseline`, `bad-baseline`,
`changed-answer`, and `non-comparable-binding` fixtures and exact set assertions.
No semantic double is invoked yet.

**Development tests.** Cover promotion eligibility/warning-not-gate,
membership immutability, active-state attribution, BAD/unreviewed/error/invalid
membership, controlled replay identity, binding/question/version mismatch,
invalid or unusable answer pairs, exact-normalization versioning, no semantic
call for non-comparable pairs, and comparison/result immutability.

**Primary acceptance scenarios.** ACC-BASE-001, ACC-COMP-001, ACC-COMP-002,
and ACC-VALID-001.

**Acceptance evidence.** Frozen membership and source snapshot, completeness
counts/warnings, active history, replay manifest/Execution values matching the
baseline exactly, comparator-not-called evidence, explicit NON_COMPARABLE cause,
and rendered adjacent answers with orthogonal outcome/judgment/review/validity/
change columns.

**Non-goals.** No baseline approval gate, official-global baseline, requirement
that members be GOOD, baseline deletion, automatic replacement binding,
semantic provider call, inference that exact match is current GOOD, or automatic
regression label.

**Exit criteria.** All four primary scenarios PASS; the internal product value
loop `run → review → baseline → replay → exact change detection` is usable;
baseline history cannot be rewritten; all prerequisite failures are
NON_COMPARABLE; unequal answers remain visible and review-required pending M7;
M5 history survives migrations.

**Open dependencies.** Real semantic comparator provider/model selection is
deliberately not required for M6. Representative immutable answer pairs should
be collected here to inform M7 selection without moving target output or secrets
outside the approved boundary.

### M7 — Conservative semantic triage

**Capability.** Comparable unequal answers are processed by a versioned
comparator so harmless differences may become UNCHANGED while material,
uncertain, malformed, timed-out, or failed comparisons remain visible and
REQUIRED. BAD baseline behavior stays historical rather than becoming truth.

**Domain and storage.** Add the comparator identity/configuration/version and
append-only semantic result details needed for EQUIVALENT, MATERIAL_CHANGE,
UNCERTAIN, and ERROR. Preserve exact input references and safe rationale/error;
recomputation appends a new comparison/result set.

**Application and UI.** Implement the comparator interface, exact-first
pipeline, deterministic fake comparator, conservative result mapping,
comparator failure attribution, triage ordering/filtering, reason display, and
BAD-baseline/current transition presentation. Change, correctness, execution,
validity, and review remain separate.

**Harness and development tests.** Add the static comparator-calibration corpus
and scripted EQUIVALENT/MATERIAL_CHANGE/UNCERTAIN/ERROR/timeout/outage/malformed
double. Test bypass on exact equality, versioned inputs/results, no overwrite,
safe diagnostics, all required attention mappings, and dangerous false-
equivalence cases.

**Primary acceptance scenarios.** ACC-BASE-002, ACC-SEM-001, ACC-SEM-002, and
ACC-SEM-003.

**Acceptance evidence.** Static case IDs and expected sets, double call journal,
persisted comparator identity and exact input references, semantic/change/review
states, BAD-to-current transitions backed only by actual human judgments, and
separate optional real-provider calibration results.

**Non-goals.** No universal answer oracle, network truth derivation, automatic
quality/regression judgment from change, similarity threshold hidden from
versioning, perfect semantic interpretation, or bulk historical regrading.

**Exit criteria.** The four primary scenarios PASS offline; exact equality
bypasses semantic work; known harmless unequal fixtures are EQUIVALENT;
material fixtures are CHANGED/REQUIRED; every uncertain/error mode is REQUIRED
and never UNCHANGED; comparator outputs never synthesize GOOD/BAD; prior results
remain immutable.

For StewardBench to claim that a real production semantic-comparison provider
is active, a provider/model/configuration must be explicitly selected,
integrated, versioned, and calibrated against representative pairs with
emphasis on false equivalence. That claim is distinct from v1 feature
completeness: the provider-neutral path may remain explicitly unconfigured at
M10, provided `COMPARATOR_NOT_CONFIGURED` keeps review required and the
operational UI/export reports the capability honestly.

**Open dependencies.** Semantic comparator provider/model/prompt/configuration
and calibration set. Material privacy, data-transfer, or retention implications
require product/security review before sending evidence to a provider.

### M8 — Ordered conversation scenarios

**Capability.** An ADMIN can run a versioned ordered ConversationScenario using
one target session, inspect the complete transcript and per-turn states, continue
after a recoverable failed/BAD turn, compare controlled conversation history,
and retry the complete conversation from turn 1 in a new attempt/session.

**Domain and storage.** Introduce ConversationScenario, version-bound ordered
ConversationTurn, required-for-overall flag, ConversationAttempt, non-secret
session identity, and turn Execution links. Preserve scenario/version, order,
exact bindings/questions, transcript, and derived overall human result.

**Application and UI.** Add scenario/turn management, target capability
validation, ordered worker dispatch without mid-scenario session replacement,
recoverable versus session-fatal behavior, complete retry, turn review,
transcript detail, derived GOOD/BAD/incomplete status, and baseline-controlled
conversation comparison using the M6 identity gate.

**Fake target and harness.** Add fixed conversation creation, session-bound
ordered turns, a BAD-quality answer, recoverable turn error, session invalidation,
fatal continuation errors, close failure, and journaled session/turn order. Add
the `conversation` fixture and full-retry request/session assertions.

**Development tests.** Cover exact version/order constraints, one session per
attempt, continue-after-turn-error where protocol permits, explicit errors when
continuation is impossible, close diagnostics, per-turn persistence/evaluation/
review, overall human-result derivation, frozen conversation comparison, and
new run/attempt/session from turn 1.

**Primary acceptance scenario.** ACC-CONV-001.

**Acceptance evidence.** Fake-target ordered session journal, PostgreSQL
scenario/attempt/turn rows, exact transcript and per-turn evidence, failure
positions, derived result from actual required-turn reviews, comparison identity,
and new linked retry identities.

**Non-goals.** No guessed workbook grouping, independent retry of dependent
turns, stop-on-BAD switch, silent new session after failure, generic workflow
engine, or MCP conversation transport.

**Exit criteria.** ACC-CONV-001 PASS; order/session continuity and failure
semantics are observable; complete retry starts from turn 1; BAD quality does
not stop later turns; protocol-fatal continuation produces explicit
infrastructure errors; transcript and history remain immutable; non-capable
targets reject before launch or report unsupported infrastructure, never BAD.

**Open dependencies.** Confirm OpsSteward v2 conversation/session wire
semantics before implementing its real adapter. The fake-target capability can
prove the product boundary, but M10 cannot certify real conversation support if
the target API cannot meet the contract. That contradiction requires product-
owner/integration review, not invented session behavior.

### M9 — Independent evaluators and LLM judge

**Capability.** Configured deterministic/policy evaluators and an optional LLM
judge can evaluate stored observations as independent versioned signals. Human
GOOD/BAD remains authoritative, disagreement remains visible, and provider
failure never changes the product outcome.

**Domain and storage.** Complete evaluator/judge identity, mechanism,
configuration/version, provider/model, prompt/version, input references,
timestamp, processing status, parsed outcome/dimensions, safe raw detail, and
error persistence on the M5 immutable envelopes. New evaluation appends; it
does not overwrite.

**Application and UI.** Add evaluator and judge interfaces, configured
invocation after response capture or on an individual stored observation,
versioned append behavior, failure isolation, ADMIN configuration only when a
real mechanism exists, and execution/review displays that show human precedence
and disagreement. No evaluator is required for every Question and evaluator
work cannot block preservation of the product response.

**Harness and development tests.** Add deterministic evaluator and fake-judge
doubles, `judge-integration` fixtures, structured-context assertions, success,
disagreement, malformed, timeout, outage, and newer-version append cases. Use
stored calibration examples; do not rely on a live nondeterministic model for
routine acceptance.

**Primary acceptance scenario.** ACC-JUDGE-001. Rerun ACC-REVIEW-001 with the
now-active integration path as a nearby regression.

**Acceptance evidence.** Double request/response trace, immutable execution and
prior-result snapshots, persisted mechanism/provider/model/judge/prompt
versions, structured dimensions, evaluator/judge error records, human review
and visible disagreement, and proof that product SUCCESS/ERROR and GOOD/BAD are
unchanged by provider behavior.

**Non-goals.** No composite score, automatic human judgment, universal
deterministic oracle, blocking dependency on an evaluator, bulk historical
regrading UI, or claim that prompt inspection proves judge quality.

**Exit criteria.** ACC-JUDGE-001 PASS offline; all configured result types are
independent and append-only; malformed/outage/timeout is an evaluator/judge
error rather than product FAIL/BAD; existing observation and human authority
are unchanged; M5 review regression passes.

**Open dependencies.** Real LLM-judge provider/model and initial rubric prompt
remain product/technology choices. The interface, deterministic double,
persistence, and disagreement behavior are mandatory; real activation and
calibration are capability-gated and do not block the core human-baseline loop.
If a real judge is advertised in v1, select and calibrate it before M10 exits.

### M10 — Operational experience complete

**Capability.** StewardBench presents a complete attention-oriented operations
experience: trustworthy dashboard counters and drill-down, dense bookmarkable
lists, chronological result/performance context, safe raw evidence, exports,
all mutation enforcement, and the supported real OpsSteward API adapter path.

This is the **v1 feature-complete point**. Once M10 exits, no major documented
v1 feature may remain; M11 contains only defects, UX polish, documentation,
migration/deployment hardening, and acceptance closure.

**Domain and storage.** Prefer projections over new persistence. Use timings,
states, snapshots, and result records already captured. Add only measured
indexes or small export/query-support fields justified by query plans. No
analytics warehouse, snapshot subsystem, or materialized score is introduced.

**Application and UI.** Complete the dashboard latest-run and selected-baseline
panels; actionable GOOD/BAD/ERROR/TIMEOUT/REQUIRED/UNCHANGED/CHANGED/
NON_COMPARABLE/transition counters; exact filtered drill-down; execution/run/
comparison filters and pagination; attention-first sorting; chronological
GOOD/BAD/unreviewed, latency p50/p90/p95, token medians, run-duration, and
throughput trends; question longitudinal version boundaries; and clear
Unknown/mode/target/concurrency context.

Implement filtered CSV and complete Run JSON export because the required data
is now already retained; preserve Unicode/structured types and exclude secrets.
Treat these as subordinate to the core loop. Add final approved vector/icon
assets if supplied. Until then retain the documented text-wordmark/temporary
asset workflow and do not invent final geometry; artwork absence does not
justify delaying functional acceptance unless the product owner explicitly
makes it a release gate.

Complete actual OpsSteward adapter work from confirmed evidence: question API
for supported v1/v2 targets, health and complete-answer behavior, errors,
authentication, evidence, and optional runtime metadata; conversation support
only where the confirmed target provides it. Preserve adapter/version per
Execution. Routine acceptance still uses the fake target; optional live checks
are separately configured, allow-listed, conservatively bounded, and never
default to a production host.

**Fake target and harness.** Add unsafe HTML/script/event-handler/Markdown/JSON/
code/long-text modes; canary secrets in headers, query, nested payloads, and
upstream errors; metrics mixed-state enumerated IDs; CSV/JSON assertions; and
selective Playwright flows for review, comparison, counters, all-matching,
OPERATOR affordances, and non-execution of returned markup. Finish the full
mutation URL/service matrix and the complete immutable observation snapshot.

**Development tests.** Cover independent count sets/denominators, invalid
exclusion, filters across pages and combinations, select-all matching, stable
review navigation, chart series and labels rather than pixels, export schema
and Unicode, redaction before persistence, output escaping/sanitization, direct
OPERATOR requests for every mutation, complete supported-operation immutability,
query plans/indexes where justified, and actual adapter mapping tests derived
from approved wire fixtures.

**Primary acceptance scenarios.** ACC-RBAC-001, ACC-IMM-001, ACC-ADAPT-003,
ACC-UNSAFE-001, ACC-METRIC-001, ACC-EXPORT-001, ACC-PERF-001,
ACC-PERF-002, and ACC-EFF-001.

**Acceptance evidence.** Complete direct-mutation denial matrix and unchanged
DB; canonical before/after historical snapshots; persisted/logged/rendered/
exported canary searches; browser execution canaries; exact expected record IDs
behind every counter/filter/page; numeric trend inputs with context; CSV/JSON
round trips; approved contract fixtures and separately reported optional live-
adapter checks.

**Non-goals.** No decorative-first dashboard, saved report builder, PDF/email/
scheduled exports, custom scoring, sophisticated analytics, automatic release
gating, GitHub build reconstruction, external-event correlation, final artwork
fabrication, comprehensive REST API/CLI, MCP, CI-triggered evaluation, or
Kubernetes. M10 includes bounded p50/p90/p95, run throughput, and token-median
projections from immutable evidence; parallel-efficiency attribution, custom
analytics, and any release gate remain v2/later work.

**Exit criteria.** All nine primary scenarios PASS; all earlier feature
scenarios remain PASS; every actionable count opens exactly its persisted set;
unsafe content never executes; secrets are absent before and after export;
metrics name mechanism and denominator; actual supported OpsSteward question
wire paths are certified or the affected advertised capability is explicitly
BLOCKED; an unconfigured semantic comparator or judge is visibly safe and
never presented as a live provider; any advertised real judge is calibrated;
no major v1 feature remains.

**Open dependencies.** Exact OpsSteward v1/v2 wire contracts and optional
metadata route; semantic comparator selection/calibration; optional real judge
selection/calibration; approved final brand artwork. Live target unavailability
does not invalidate deterministic product acceptance, but unresolved required
wire compatibility blocks the corresponding release claim.

### M11 — v1 release acceptance

**Capability.** A clean installation can migrate, bootstrap, import, configure,
execute, review, baseline, rerun, compare, triage, converse where supported,
export, restart, and retain evidence using the actual v1 Docker topology.

**Domain and storage.** No feature schema. Harden only proven defects in the
migration graph, constraints, indexes, or compatibility behavior. Exercise
representative prior migration states populated with Unicode, unknown identity,
JSONB evidence, import provenance, terminal runs/executions, reviews, validity,
baselines, comparisons, evaluator/judge results, and conversations.

**Application and UI.** No major new surface. Reconcile documentation, help/UI
copy, empty/error/blocked states, accessibility basics, operational startup,
health/readiness, explicit migrations, first-admin instructions, target setup,
and the supported smoke path.

**Harness.** Complete Docker smoke in a uniquely named disposable Compose
project using the application image for web and worker, PostgreSQL durable
volume, explicit migration step, and fake target. Exercise web navigation away/
return, web restart, worker restart/reconciliation, composition down/up without
volume deletion, and clean shutdown. Run the entire applicable 35-scenario
catalog in its required tiers; optional live/provider layers are reported
separately and never convert BLOCKED to PASS.

**Development tests.** Run the full repository suite, representative migration
upgrades, process-level worker suite, request/RBAC suite, browser suite, import
reconciliation, adapter/comparator/judge doubles, export/redaction checks, and
Docker smoke. Fix only attributable defects and add regression tests for each.

**Primary acceptance scenarios.** ACC-MIG-001 and ACC-DOCKER-001. All other
scenarios are mandatory regressions for the complete release scope.

**Acceptance evidence.** Migration graph/leaf and exact pre/post historical
snapshots; constraint probes; Compose service/image inventory; migration and
bootstrap logs; authentication and launch actions; target journal; restart
process evidence; durable volume observation; final Run/Execution/comparison
state; catalog-wide PASS/FAIL/BLOCKED report; and reconciled docs/build SHA.

**Non-goals.** No feature rescue through a new architecture, no new evaluator
or dashboard capability, no release-flow framework, no deferred roadmap item,
and no weakening of acceptance to meet a release date.

**Exit criteria.** ACC-MIG-001 and ACC-DOCKER-001 PASS; every applicable v1
catalog scenario is PASS with no required BLOCKED item; fresh and representative
upgrades preserve exact history; one controlled evaluation completes once and
survives web/worker/composition restart; only web, worker, PostgreSQL, and the
test-only fake target participate; source and contractual documentation agree;
the final diff/status is understood and release evidence names the exact SHA.

**Open dependencies.** Any still-unavailable required target/provider or
product-owner decision is reported as BLOCKED for its exact release claim. It
cannot be hidden by deterministic offline evidence.

## Schema and migration introduction map

This map identifies first introduction, not a final SQL design. Each milestone
creates only the fields and constraints needed by its capability and includes a
version-controlled migration plus clean and populated-previous-state checks.

| Concept | First milestone | Migration intent |
| --- | --- | --- |
| Local User/auth application role state | M0 | Exactly ADMIN/OPERATOR; secure bootstrap and sessions use Django auth mechanics. |
| Product | M1 | Stable product-neutral identity. |
| Environment | M1 | Stable logical context independent of Product. |
| EvaluationTarget | M1 | Stable Product/Environment target identity. |
| TargetRevision | M1 | Immutable endpoint, credential reference, adapter capability, policy, declared-build fallback. |
| Question | M1 | Stable identity, kind, lifecycle, controlled domain, tags, rationale. |
| QuestionVersion | M1 | Exact immutable temporal definition and change attribution. |
| BindingDefinition and HistoricalFixture | M1 | Minimal versioned inputs; fixture is context, not a snapshot/oracle. |
| LegacyImportBatch, row/cell mapping, LegacyObservation | M2 | Source checksum/mapping identity, raw provenance, explicit unknowns and legacy separation. |
| EvaluationRun and frozen manifest membership | M3 | One target revision, one stable selection, actor/policy/build launch snapshot. |
| Execution and ResolvedBinding | M3 | Exact request/response/evidence/timing/identity observation and binding values. |
| BuildSnapshot, TargetSnapshot, runtime metadata observation | M3 | Admin/runtime sources retained; unknown permitted; later changes cannot rewrite history. |
| Claim/lease/heartbeat or reconciliation state | M4 | Unique ownership, attempt phase, safe recovery, target-wide capacity. |
| HumanReview and ReviewTracking | M5 | Append-only judgment/correction and separate attributed attention state. |
| Comment and ExecutionValidityDecision | M5 | Append-only context and VALID/INVALID history/projection. |
| AutomatedEvaluationResult and LLMJudgeResult envelopes | M5 | Minimal immutable independent records needed to prove review orthogonality. |
| Baseline and membership | M6 | Immutable observed run reference plus attributed active designation. |
| Comparison and exact ComparisonItem | M6 | Comparability, exact result, change/review state, exact inputs and causes. |
| Semantic comparator result/version details | M7 | Append-only semantic outcome, identity, rationale/error and input references. |
| ConversationScenario and ConversationTurn | M8 | Version-bound ordered scenario definition. |
| ConversationAttempt/session link | M8 | One non-secret session and ordered turn Executions per attempt. |
| Evaluator/judge invocation configuration and complete result details | M9 | Versioned mechanism/provider/model/prompt/context and failure state. |

Every later schema migration is tested over representative existing history.
No migration may fabricate missing identity, reviewer, timestamp, binding,
judgment, or source semantics, or rewrite immutable evidence. A forward-only
migration states that consequence explicitly.

## Acceptance traceability matrix

Every initial catalog scenario has exactly one primary milestone below. A
scenario may be developed incrementally and rerun later, but its row identifies
the first milestone whose exit requires the complete scenario to PASS. All 35
are v1 obligations; none is silently deferred to v2/v3.

| Scenario ID | Short title | Primary milestone | Requirement/invariant | Acceptance layer | Required before milestone exit? |
| --- | --- | --- | --- | --- | --- |
| ACC-AUTH-001 | First ADMIN bootstrap | M0 | Secure, unique first ADMIN; no plaintext secret | Request/service + PostgreSQL | YES |
| ACC-AUTH-002 | Login and user state | M0 | Authenticated access; invalid/inactive/session flows denied safely | Django request | YES |
| ACC-RBAC-001 | OPERATOR read-only | M10 | Every product mutation denied server-side with unchanged state | Service/request + PostgreSQL | YES |
| ACC-RBAC-002 | ADMIN and exactly two roles | M0 | Authorized ADMIN actions; no extra role through Django flags/groups | Service/request + PostgreSQL | YES |
| ACC-QVER-001 | Exact temporal QuestionVersion | M3 | Old executions retain exact version/text; no temporal overlap/adoption | Service + PostgreSQL | YES |
| ACC-RUN-001 | Frozen prompt run manifest | M3 | One target, exact eligible selection/policy/bindings, prompt launch | Service/request + PostgreSQL | YES |
| ACC-RETRY-001 | New retry/rerun history | M5 | New linked Run/Execution/request; source stays terminal and identical | Service + worker/adapter + PostgreSQL | YES |
| ACC-IMM-001 | No terminal evidence rewrite | M10 | All supported later operations append facts; stale completion cannot overwrite | Service + PostgreSQL + worker | YES |
| ACC-BASE-001 | Immutable warning-based baseline | M6 | Observed membership fixed; incompleteness warns but does not approve/block | Service/UI + PostgreSQL | YES |
| ACC-BASE-002 | BAD baseline is not truth | M7 | Equivalent BAD history does not synthesize GOOD; transitions require reviews | Comparison/service | YES |
| ACC-COMP-001 | Controlled exact inputs | M6 | Replay freezes QuestionVersion, bindings, and concrete question | Comparison/service + PostgreSQL | YES |
| ACC-COMP-002 | Invalid prerequisites non-comparable | M6 | No substitution or semantic call; causes and orthogonal flags retained | Comparison/service + PostgreSQL | YES |
| ACC-REVIEW-001 | Orthogonal review and results | M5 | Review state, human judgment, automation, and execution outcome stay separate | Service/UI + PostgreSQL | YES |
| ACC-VALID-001 | Invalid preserves evidence | M6 | Attributed validity history; evidence retained; baseline/comparison history fixed; metrics exclude INVALID | Service/metrics + PostgreSQL | YES |
| ACC-SEM-001 | Harmless change equivalent | M7 | Exact bypass; versioned EQUIVALENT unequal pairs become UNCHANGED | Comparator/service | YES |
| ACC-SEM-002 | Material change requires attention | M7 | MATERIAL_CHANGE produces CHANGED and REQUIRED, not quality judgment | Comparator/service | YES |
| ACC-SEM-003 | Uncertainty cannot hide change | M7 | UNCERTAIN/ERROR/outage/malformed never UNCHANGED and always surface attention | Comparator/service | YES |
| ACC-ADAPT-001 | Complete raw-preserving capture | M3 | Exact Unicode/raw/evidence/correlation/version and metadata source/unknown | Adapter + fake target + PostgreSQL | YES |
| ACC-ADAPT-002 | Normalized target failure | M3 | ERROR/TIMEOUT classification; incomplete 200 not SUCCESS; no BAD | Adapter + fake target | YES |
| ACC-ADAPT-003 | Redact before persistence | M10 | Secret variants absent from DB, logs, UI, errors, and exports | Adapter/trust boundary + browser | YES |
| ACC-WORKER-001 | Unique two-worker claims | M4 | One owner/request/terminal observation; no lock during remote call | PostgreSQL + worker process + fake target | YES |
| ACC-WORKER-002 | Sequential and target caps | M4 | One in flight sequential; aggregate target maximum across parallel runs | Worker process + fake target + PostgreSQL | YES |
| ACC-WORKER-003 | Partial failure preserved | M4 | Independent outcomes/evidence and correct aggregate/progress | Worker/adapter + PostgreSQL | YES |
| ACC-WORKER-004 | Safe restart and ambiguity | M4 | Safe reclaim once; ambiguous acceptance no resubmit; terminal race immutable | Worker process + fake target + PostgreSQL | YES |
| ACC-CONV-001 | Ordered one-session conversation | M8 | Ordered turns, continuation/errors, complete new retry, derived human result | Adapter/worker/service + fake target | YES |
| ACC-JUDGE-001 | Independent versioned judge | M9 | Versioned append-only signal/failure; human authority and disagreement visible | Judge double/service + PostgreSQL | YES |
| ACC-IMPORT-001 | Non-destructive reconciled import | M2 | Workbook hash/count/provenance/ambiguity/idempotency and no invented truth | Import + real workbook + PostgreSQL | YES |
| ACC-UNSAFE-001 | Untrusted output does not execute | M10 | Safe rendered evidence with exact raw preservation | Request + Playwright + PostgreSQL | YES |
| ACC-METRIC-001 | Exact metric sets and drill-down | M10 | Counts/denominators/filters/pages match independently enumerated IDs | Query/request/browser + PostgreSQL | YES |
| ACC-EXPORT-001 | Complete secret-free exports | M10 | Unicode/raw/state/type round trip without usable credentials | Export/request + PostgreSQL | YES |
| ACC-PERF-001 | Versioned performance evidence | M10 | Exact latency boundaries, quality independence, timeout separation, and immutable telemetry | Service + PostgreSQL + fake target | YES |
| ACC-PERF-002 | Controlled latency comparison | M10 | Controlled pair retains raw deltas, regression rule, band transition, and answer independence | Service + PostgreSQL | YES |
| ACC-EFF-001 | Target-reported efficiency evidence | M10 | Token/runtime metadata, unknown behavior, deltas, export, and malformed-telemetry isolation | Adapter + export + PostgreSQL | YES |
| ACC-MIG-001 | Representative upgrade preservation | M11 | Clean/upgrade graph, constraints, exact history, no fabricated identity | Migration + PostgreSQL | YES |
| ACC-DOCKER-001 | Durable deployable composition | M11 | Web/worker/db evaluation survives process and volume lifecycle | Docker + fake target + PostgreSQL | YES |

The matrix has 35 unique scenario IDs and 35 rows. Export is optional in the
product specification only while its cost is unknown; this plan includes it in
M10 because the retained v1 data makes the documented CSV/JSON forms a bounded
increment. If implementation evidence shows it is not inexpensive, removing it
from v1 requires an explicit product-owner scope reconciliation and updates to
this plan/catalog rather than marking ACC-EXPORT-001 PASS or silently deferring
the row.

## v1 requirement coverage audit

| Product/roadmap obligation | First usable milestone | Completion gate |
| --- | --- | --- |
| Docker web/worker/PostgreSQL and explicit migrations | M0 | M11 |
| Local authentication, bootstrap, exactly ADMIN/OPERATOR | M0 | M10 full mutation matrix |
| Product, Environment, Target, TargetRevision and execution policy | M1 | M10 actual adapter certification |
| Stable Questions, temporal versions, domain/tags/rationale/lifecycle | M1 | M3 exact execution identity |
| Lightweight historical fixtures | M1 | Progressive/non-blocking; binding behavior M3/M6 |
| Non-destructive corpus and legacy evidence import | M2 | M2 |
| One/many/all-matching selection against one target | M3 | M10 UI/filter regression |
| Browser-independent sequential execution | M3 | M4 process acceptance |
| Safely bounded parallel execution and restart | M4 | M4 |
| Exact question/bindings/answer/evidence/timing/identity capture | M3 | M10 immutability/redaction |
| OpsSteward API adapter, health, errors, optional metadata | M3 normalized boundary | M10 confirmed supported wire paths |
| Human GOOD/BAD, independent review state, comments, validity | M5 | M5 |
| Retry/rerun creates new immutable history | M5 | M5 |
| Named immutable baselines and visible completeness | M6 | M6 |
| Controlled comparison and exact equality | M6 | M6 |
| Conservative semantic comparison | M7 | M10 safe readiness/status; real provider/calibration optional |
| Ordered conversation scenario and complete retry | M8 | M10 supported wire path |
| Independent automated evaluator and judge records when configured | M5 records/M9 invocation | M9; real activation capability-gated |
| Dashboard, review workstation, comparisons and URL filters | M3/M5/M6 incrementally | M10 |
| Chronological GOOD/BAD and basic performance context | Raw timing M3 | M10 |
| Indefinite preserved history | M3 onward | M10 immutability + M11 upgrade/restart |
| CSV/JSON export if inexpensive | M10 | M10 or explicit scope reconciliation |

This coverage deliberately does not add Kubernetes, CI-triggered evaluation,
release gating, MCP, public execution API/CLI, scheduled runs, multi-target
fan-out, object storage, comprehensive answer oracles, external-event snapshots,
complex RBAC/audit/OIDC, bulk historical regrading, or random-question
generation.

## Cross-cutting implementation controls

### Target adapter and runtime identity sequence

1. M1 stores only normalized technical capabilities, external credential
   references, execution policy, and admin-declared build fallback.
2. M3 accepts the product-neutral adapter contract and fake-target path,
   preserves adapter version, and snapshots declared/runtime/unknown identity.
3. Actual OpsSteward v1/v2 discovery produces approved wire fixtures. One
   negotiating adapter is allowed only if the schemas truly share safe behavior;
   otherwise use explicit versioned adapters behind the same interface.
4. M8 activates real conversation support only for a confirmed session API.
5. M10 certifies required supported question paths and optional metadata;
   live tests remain opt-in and bounded. Metadata absence never blocks execution.

No stage adds MCP or queries GitHub to reconstruct deployed identity.

### Comparator and judge sequence

Semantic comparison proceeds as normalized exact equality in M6, a comparator
interface and deterministic double in M7, then optional explicit provider/model
selection, integration, and calibration before a production semantic claim. The
exact path is usable while provider selection is open; `NOT_CONFIGURED` must
remain a visible review-required state rather than a fake production result.

Judge work proceeds as immutable result envelopes in M5, interface/schema and
deterministic fake invocation in M9, then optional real provider/model/prompt
selection and calibration. A real judge is not a prerequisite for human
baseline work. Human disagreement behavior is mandatory regardless of provider.

### Harness growth and ownership

Application development tests remain under the conventional test tree near
their behavior. Reusable fake services, scenario documents, and process/Docker
orchestration enter `harness/` only when first executable. No empty future
scaffolding is created. Every fake-target increment validates its own scenario
preconditions and journal before product assertions use it.

The development skill governs implementation and developer tests. The QA skill
governs independent PASS/FAIL/BLOCKED evidence. The same person or session may
run both only if the acceptance posture and failure attribution remain explicit;
developer tests are not substituted for mapped acceptance.

### UI and brand sequence

Every milestone exposes a server-rendered, authorized operational surface:
login/navigation in M0, catalog in M1, import report in M2, run progress/evidence
in M3, worker state in M4, review in M5, baseline/comparison in M6, triage in M7,
conversation transcript in M8, evaluator signals in M9, and final dashboard/
trends/export in M10. HTMX is bounded progressive enhancement; canonical URLs,
forms, CSRF, and full-page behavior remain testable.

Until approved source artwork arrives, use the wordmark and documented concept/
color semantics without inventing an SVG. Record temporary assets and their
replacement path. Approved final masters and variants may land in M10 before UI
polish; functional milestones do not wait for them.

### Commit and branch strategy

Normal short-lived feature branches merged into `main` are sufficient. Do not
introduce GitFlow or milestone-long integration branches. A milestone may use
several coherent commits: schema/state-machine changes, service behavior, UI,
tests/harness, and documentation should be independently reviewable when that
improves risk review. Keep the migration with the behavior that needs it; do not
combine unrelated future capability. Merge only after the milestone gate, or
clearly mark a non-user-visible prerequisite commit whose dependent gate is
still open.

## Implementation stop conditions

Stop and obtain product-owner and/or architecture review before proceeding when:

- satisfying a milestone appears to require violating an accepted ADR or
  adding SQLite, Redis, RabbitMQ, Celery/RQ/Dramatiq, Kafka, a SPA/service split,
  Kubernetes, or another durable system;
- a canonical product, domain, evaluation, import, adapter, or UI requirement
  is contradictory rather than merely difficult;
- the PostgreSQL worker cannot classify ambiguous remote completion without
  silent resubmission, evidence overwrite, or fabricated continuity;
- an OpsSteward v1/v2 API cannot support the documented complete-answer,
  correlation, or conversation interaction and no honest normalized mapping is
  possible;
- the corpus differs from its checksum/inventory or cannot be mapped without
  deciding unresolved semantics by inference;
- a comparator/provider cannot conservatively surface uncertainty or produces
  unacceptable dangerous false equivalence;
- a required migration would delete, rewrite, normalize destructively, or
  fabricate historical evidence/identity/attribution;
- usable credentials would need to enter application records, evidence, logs,
  comments, diagnostics, or exports;
- cancellation is requested after lifecycle implementation without a reviewed
  state/evidence design and acceptance scenario; or
- work depends on a v2/v3 capability such as CI-triggered evaluation, MCP,
  automatic gating, or external operational-system snapshots.

## What not to implement first

Do not begin v1 with dashboard polish, charts, LLM-judge provider integration,
semantic-comparator model integration, advanced exports, visual-branding polish,
MCP, CI/CD, Kubernetes, or a user-facing CLI. These either depend on trusted
history/execution or are outside v1. The first authorized implementation task is
M0 only: runnable PostgreSQL/Django/Docker foundations, secure local identity,
the exact two-role boundary, and their mapped acceptance evidence.

## Definition of v1 feature complete and release accepted

**Feature complete** occurs only when M10 exits: all major documented v1
capabilities exist, all M0–M10 primary acceptance scenarios pass, required
OpsSteward question integration is certified or explicitly BLOCKED, optional
semantic-comparator and judge providers are honestly represented as configured
or not configured, any advertised conversation capability is honestly
supported, and remaining work is limited to defects, UX polish, documentation,
migration/deployment hardening, and catalog-wide acceptance closure.

**Release accepted** occurs only when M11 exits. It additionally requires clean
and representative upgrade acceptance, durable Docker smoke, complete applicable
catalog PASS, and no required BLOCKED item. Feature complete is therefore not a
release claim.
