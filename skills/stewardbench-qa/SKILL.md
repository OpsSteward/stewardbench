---
name: stewardbench-qa
description: Independently review and validate StewardBench behavior against repository product and architecture contracts. Use for feature acceptance, regression review, trust-boundary review, migration and worker validation, UI/RBAC acceptance, and release-readiness assessment; not for implementing features or the future acceptance harness.
metadata:
  short-description: Prove StewardBench correctness
---

# StewardBench QA and acceptance

Independently determine whether StewardBench satisfies its documented contracts.
This skill defines how to prove behavior; it does not describe how to implement
behavior and does not authorize application fixes, deployments, live-target
calls, or destructive database operations.

The central acceptance question is:

> Does StewardBench reliably execute, preserve, compare, review, and report
> evaluation observations according to its documented invariants without
> silently corrupting, hiding, or misclassifying historical evidence?

Prioritize the trustworthiness of historical evaluation state over convenience.
Implementation intent is not proof of implementation correctness.

## Establish acceptance authority

Before designing acceptance, inspect Git status and read
[AGENTS.md](../../AGENTS.md), the [README](../../README.md), and the
[documentation index](../../docs/README.md). Read the accepted
[ADRs](../../docs/adr/README.md) and the authoritative documents relevant to the
behavior under review:

- [Product definition](../../docs/product-definition.md)
- [Architecture](../../docs/architecture.md)
- [Domain model](../../docs/domain-model.md)
- [Evaluation methodology](../../docs/evaluation-methodology.md)
- [UI/UX](../../docs/ui-ux.md)
- [Framework selection](../../docs/framework-selection.md)
- [Question corpus import](../../docs/question-corpus-import.md)
- [Target adapter contract](../../docs/target-adapter-contract.md)
- [Roadmap](../../docs/roadmap.md)
- [Open questions](../../docs/open-questions.md)

Use this acceptance authority hierarchy:

1. repository product, architecture, and accepted ADR authority;
2. observable StewardBench behavior;
3. persisted PostgreSQL state;
4. repeatable test evidence;
5. scoped logs and diagnostics; and
6. implementation code as supporting evidence.

Repository authority wins over this skill. Treat open questions as unresolved;
do not turn an ambiguity into a PASS or silently choose product behavior. The
[development skill](../stewardbench-development/SKILL.md) describes how to
build StewardBench and is not correctness authority.

Match acceptance scope to the roadmap. Do not fail v1 for an explicitly
deferred feature, mistake an open decision for a requirement, or require
Kubernetes, CI gating, MCP, a public execution API/CLI, scheduling, multi-target
fan-out, object storage, broad answer-oracle infrastructure, or other deferred
work to prove the documented v1 behavior.

## Apply an independent evidence posture

Do not accept any of these as sufficient evidence by itself:

- the code looks right;
- the developer added a test or says tests pass;
- a migration succeeded once locally;
- a UI control is visible or hidden;
- the worker should recover or appears to use a lock;
- the comparator or judge uses an LLM; or
- a mock returned the expected value.

Translate each requirement into an observable criterion. Prefer corroborating
evidence across the narrowest applicable layers: HTTP behavior, rendered UI,
persisted rows and constraints, worker ownership/lease state, timestamps,
captured outcomes and evidence, review and baseline records, target/build
snapshots, and logs scoped to one operation. Inspect implementation after the
expected behavior and observables are understood, primarily to explain evidence
or find additional risk.

Use repeatable, disposable environments and deterministic fixtures when
possible. Use controlled fake HTTP targets for target failure modes; do not
depend on live OpsSteward unless the task authorizes it. PostgreSQL behavior,
especially transactions, locking, constraints, and concurrency, must be tested
against supported PostgreSQL, never SQLite or an in-memory substitute. Mocks
alone cannot establish those semantics.

## Required acceptance workflow

For each review:

1. Identify the exact repository requirement or invariant and its authority.
2. Define observable PASS criteria before examining implementation details.
3. Identify the required environment, build identity, data, actors, target
   behavior, and preconditions.
4. Inspect the implementation only after expected behavior is understood.
5. Create or select the smallest test that exposes the behavior and its
   persisted effects.
6. Run the validation and retain exact commands/actions and relevant outputs.
7. Inspect resulting PostgreSQL state, including related and historical rows.
8. If behavior differs, inspect operation-scoped logs/diagnostics and adjacent
   state transitions.
9. Classify the failure domain using the defect-attribution model below.
10. Reproduce with a smaller boundary or independent mechanism when needed.
11. Report StewardBench FAIL only when evidence establishes a product contract
    violation.
12. Record a harness/test defect separately; do not relabel it as product FAIL.
13. Require the narrowest remediation for the proven failure domain.
14. Rerun the failed acceptance after remediation.
15. Run nearby regression coverage, including a negative or adversarial path.
16. Report the requirement-to-evidence mapping and conclusion.

Do not patch application code merely because one test failed. Diagnosing or
reviewing does not authorize implementation changes. If remediation is
separately requested, preserve the evidence and hand the narrow proven defect
to the development workflow.

## Use a small result vocabulary

Keep QA results for StewardBench itself distinct from the benchmark data it
stores:

- `PASS`: repeatable acceptance evidence demonstrates that the requirement is
  satisfied.
- `FAIL`: observable StewardBench behavior violates repository authority.
- `BLOCKED`: acceptance cannot be established because required environment,
  data, dependency, authority, or a trustworthy test mechanism is unavailable.

Never call `BLOCKED` a PASS. A harness defect is not a StewardBench FAIL unless
an independent observation also demonstrates the product violation. Partial
coverage does not justify a broader PASS than the evidence supports.

## Attribute defects independently

Build small observable failure domains. Change one boundary at a time, use
correlation IDs or unique fixture identifiers, compare before/after state, and
capture only the logs for the failing operation. Do not infer root cause from a
single failing test.

Classify at least these domains:

| Failure domain | Evidence that can distinguish it |
| --- | --- |
| StewardBench application/runtime defect | Repeatable wrong service, HTTP/UI, or persisted behavior with valid prerequisites and dependencies |
| Acceptance harness/test defect | Product behavior is correct through an independent probe, while assertion, timing, cleanup, driver, or orchestration is wrong |
| Fixture/data defect | Malformed, stale, ambiguous, or authority-incompatible setup explains the result; corrected fixture changes it |
| Database/migration defect | Actual PostgreSQL schema, constraint, migration history, query plan, lock, or preserved-row evidence violates requirements |
| Worker lifecycle/concurrency defect | Claim owner/token/lease, transaction/lock timing, dispatch count, recovery, or terminal-write evidence violates worker semantics |
| Target-adapter defect | Controlled target wire behavior is mapped, captured, timed out, authenticated, or redacted incorrectly at the adapter boundary |
| OpsSteward/evaluated-target defect | Valid request leaves StewardBench correctly, and the target independently returns/fails with the observed behavior |
| LLM judge/evaluator defect | Product observation is intact but the identified versioned evaluator fails, is malformed, or produces the disputed advisory result |
| Semantic-comparator defect | Comparable immutable inputs are correct, but the identified comparator misclassifies, hides uncertainty, or records unusable output |
| Environment/configuration/infrastructure defect | Missing service, wrong build/config, network/DNS/TLS, resource exhaustion, clock, credential injection, or unsupported environment prevents acceptance |

When evidence spans domains, report each separately and state what remains
unknown. A target failure must not become human BAD; an evaluator failure must
not become product FAIL; a comparator outage must not become UNCHANGED; and an
environmental failure must not be disguised as a code regression.

## Core invariant acceptance

Every affected invariant needs explicit positive and forbidden-path evidence.
For persistent behavior, inspect both the intended new records and the
historical records that must remain untouched.

### Historical immutability and identity

Prove that:

- terminal Execution observation fields cannot be silently rewritten through
  services, worker completion races, direct supported UI/API paths, or retry;
- completed EvaluationRuns are not reopened to append work;
- retry and rerun create new Runs and Executions with source links;
- the original submitted question, bindings, answer, response, evidence,
  timing, adapter identity, target revision, and build snapshot remain intact;
- historical target/build identity survives later target revisions and build
  changes, with missing identity recorded as unknown rather than invented; and
- comments, reviews, validity decisions, comparisons, and evaluator results
  append or create attributed records without rewriting the product response.

For question identity, prove each Execution references the exact
QuestionVersion used, version boundaries remain explicit, historical runs do
not adopt the current version, and controlled run manifests preserve exact
frozen baseline bindings and concrete submitted questions.

### Baseline, review, comparison, and validity semantics

Prove that:

- a Baseline is an immutable reference to observed historical performance and
  may contain GOOD, BAD, unreviewed, errored, or later-invalidated observations;
- matching a BAD baseline never synthesizes current GOOD, and BAD historical
  answers remain BAD history;
- activating/deactivating a baseline does not delete or mutate its run or
  membership;
- later invalidation of a baseline member raises visible attention without
  rewriting baseline history or prior comparison records;
- review state and human judgment are distinct, including REVIEWED+GOOD,
  REVIEWED+BAD, and REVIEWED without judgment for infrastructure triage;
- human GOOD/BAD is authoritative when present while automated evaluations and
  disagreements remain visible and unchanged;
- comparison first requires the same QuestionVersion, exact frozen bindings,
  concrete question, and usable VALID answer pair;
- an unavailable/invalid frozen binding, version mismatch, question mismatch,
  invalid observation, or unusable answer pair yields NON_COMPARABLE rather
  than substitution;
- answer change remains independent from regression and current quality;
- semantic uncertainty/error produces REQUIRED attention and never UNCHANGED;
- INVALID retains all observation evidence and attributed/timestamped decision
  history while ordinary product-quality metrics exclude it; and
- metric denominators and result labels identify the mechanism used and do not
  collapse execution, automated, human, review, validity, or change dimensions.

### RBAC and secrets

Exercise every affected mutation as ADMIN and OPERATOR. Verify server-side
denial—not only hidden controls—for direct POSTs or equivalent requests to run
launch/retry/rerun, review, comment, validity, baseline, question, target, and
user mutations. Confirm role changes take effect on subsequent authorization
decisions and that framework staff/superuser/group flags do not create extra
StewardBench product roles.

Seed recognizable canary secrets in every relevant input and upstream error
path. Search persisted requests/responses/evidence, exports, generated system
comments, normal operator-visible logs, and user-visible errors for exact and
encoded/structured variants. Verify credentials remain runtime-only references
and that redaction happens before persistence, not merely during rendering.
Avoid exposing real credentials while testing redaction.

## Worker acceptance

Worker acceptance requires PostgreSQL-backed integration evidence with a
controlled target that records request start/end, concurrency, and correlation
identity. Observe database rows and locks during execution; mocks or unit tests
alone are insufficient.

Cover, as applicable:

- durable run manifest, work intent, progress, and claim state independent of
  browser or web-process lifetime;
- unique claim ownership/token plus lease, heartbeat, or equivalent
  reconciliation metadata;
- short claim transactions and released PostgreSQL locks before any remote
  target call;
- completion permitted only for the current matching claim;
- sequential mode with one in-flight target request;
- parallel mode bounded by the requested run limit and target maximum;
- aggregate concurrency across simultaneous runs against the same target;
- actual mode/concurrency, timeout, delay, and timestamps retained accurately;
- per-question timeout and target-unreachable behavior;
- worker restart before claim, after safe claim, during target call, after
  response, and around terminal persistence;
- ambiguous remote-call completion recorded as explicit benchmark
  infrastructure error without silent re-execution;
- idempotent/racing terminal writes with no duplicate terminal observation;
- partial progress preserved and one failure not erasing completed siblings;
  and
- terminal run state and UI progress projections matching persisted work.

Use synchronization barriers or a deliberately blocking controlled target to
make transaction and concurrency states observable rather than relying on
sleep-only timing assertions. Record lock/transaction observations, target-side
request counts, claim rows, and final Execution/Run state together.

## Database and migration acceptance

For every persistent schema change:

- apply migrations from the supported prior state to a disposable supported
  PostgreSQL instance and inspect the resulting schema and migration history;
- seed representative existing historical observations before migration, then
  verify exact preservation afterward;
- exercise constraints against documented valid and invalid states rather than
  trusting migration source;
- inspect indexes and representative query plans for the operational queries
  the change is intended to support, when relevant;
- identify locks, table rewrites, deployment ordering, downtime, and forward/
  rollback implications, even when reversal is intentionally unsupported;
- verify data migrations do not fabricate missing identity, attribution,
  timestamps, bindings, judgments, or semantics; and
- verify legacy evidence is neither silently reinterpreted nor destructively
  normalized.

A clean migration on an empty database does not establish preservation. A
source review without applying it does not establish resulting schema behavior.

## Target-adapter acceptance

Test the adapter separately with a controlled HTTP target before attributing
end-to-end failures. Validate:

- bounded connectivity/health behavior and authentication;
- exact Unicode submitted question and complete raw-response capture;
- exact extracted answer, evidence, correlation, adapter identity/version, and
  normalized envelope;
- complete-answer waiting rather than persisting a streaming fragment;
- timeout, connection failure, target error, authentication error, malformed
  response, unsupported behavior, and safe diagnostics;
- conversation/session creation, reuse, ordered turns, and failure handling;
- runtime metadata retrieval, source attribution, conflict visibility, and
  non-fatal unavailable/unknown fallback; and
- secret redaction from requests, evidence, diagnostics, logs, and exports.

Keep adapter/transport failure distinct from answer quality. A 200 response is
not SUCCESS unless a complete valid envelope is captured; an OpsSteward API
failure must not become human BAD. Historical Executions remain tied to their
adapter and TargetRevision and are not destructively reparsed after upgrades.

## Human review and UI/RBAC acceptance

The first-baseline review loop deserves end-to-end coverage. Validate this
workflow through the UI plus HTTP and database evidence:

1. ADMIN opens an Execution and sees the exact question, current answer, and
   baseline answer beside it when comparison applies.
2. ADMIN records GOOD or BAD and an optional Unicode comment.
3. Reviewer identity and time persist; relevant state becomes REVIEWED.
4. Automated evaluator and judge records remain unchanged.
5. Disagreement remains visible.
6. Dashboard/list counters and filtered projections update correctly.
7. Previous/next navigation preserves a stable review queue and does not skip
   items silently.
8. OPERATOR sees evidence but cannot perform the same mutation through UI or a
   crafted request.

Also validate baseline promotion with visible completeness counts and warning,
without inventing an approval gate or requiring every observation to be GOOD.
For errors/timeouts without usable answers, verify an admin can triage REVIEWED
without a fabricated GOOD/BAD judgment.

Use Playwright selectively for high-value workflows: login, OPERATOR read-only
behavior, ADMIN launch, GOOD/BAD review, baseline creation, comparison
drill-down, and review-required navigation. Use Django request/service tests for
authorization/forms and PostgreSQL tests for state invariants; do not make all
acceptance depend on browser automation or screenshots.

Treat evaluated-target content and comments as untrusted. Submit HTML/script,
malformed JSON-like text, large content within supported bounds, and Unicode.
Verify raw evidence remains available while rendered pages escape or explicitly
sanitize content and never execute it.

## Dashboard, lists, filters, and metrics

Attention counters are claims about persisted sets, not decoration. For REVIEW
REQUIRED, GOOD to BAD, BAD to GOOD, ERROR, TIMEOUT, CHANGED, and NON_COMPARABLE
as applicable:

- create a known mixed-state dataset;
- independently query/count the qualifying PostgreSQL records;
- compare the rendered count and denominator;
- follow the counter and confirm the URL-addressable filter opens exactly that
  set;
- exercise pagination, combined filters, zero results, and all-matching
  selection; and
- verify no matching record is dropped, duplicated, or replaced by only the
  current page.

Confirm statuses remain separate and labels do not call SUCCESS good, CHANGED a
regression, REVIEWED good, or UNKNOWN an empty known value. For performance
views, verify target, mode, concurrency, build, and chronological execution
context prevent misleading unlike-for-like comparisons.

## Semantic-comparator acceptance

The comparator optimizes attention and is not correctness authority. Record and
assert comparator identity/version, exact inputs/references, semantic outcome,
reasoning/evidence, change state, and review state.

Maintain representative calibration cases for:

- equivalent changes: whitespace, punctuation, harmless formatting/reordering,
  and semantically equivalent wording;
- material changes: entity or relationship set, count, conclusion, omitted key
  information, new unsupported assertion, changed cannot-conclude behavior,
  malformed/incomplete output, and internal code/details leakage; and
- genuinely ambiguous equivalence.

The required safety behavior is `UNCERTAIN -> REVIEW REQUIRED`. Timeout,
unavailability, malformed output, or internal error must remain a comparator
ERROR/UNCERTAIN signal and must not yield UNCHANGED. Do not require perfect
semantic classification; bias acceptance toward preventing hidden meaningful
changes and report false equivalence as the highest-risk comparator defect.

## LLM-judge and evaluator acceptance

Use stored calibration examples and controlled success, outage, timeout, and
malformed-output responses. Validate that judge/evaluator results:

- persist independently from the product Execution and from one another;
- retain mechanism/provider/model, identity/version, prompt version where
  applicable, inputs/references, timestamp, parsed output, and safe raw details;
- record malformed output or outage as evaluator/judge failure with no product
  BAD/FAIL synthesized;
- never destroy or block an already captured product observation;
- remain unchanged and visible when a human review takes precedence; and
- append new versioned results rather than overwriting old ones.

Do not accept prompt inspection alone as evidence of LLM-judge quality. Use
behavioral calibration examples, while recognizing that the judge is advisory
when human review exists.

## Conversation acceptance

Validate a conversation as one ordered scenario, not as independent questions:

- one non-secret target conversation/session identity is used across turns;
- turn order, exact per-turn question/bindings, response/evidence, outcome,
  latency, and evaluations are retained;
- a BAD answer does not stop later turns, while a protocol failure that makes
  continuation impossible creates explicit later infrastructure errors;
- the complete transcript remains visible in order;
- retry creates a new Run, ConversationAttempt, and session from turn 1;
- baseline comparison preserves scenario/version, ordered turns, concrete
  questions, and frozen bindings; and
- overall human GOOD requires every required turn GOOD, any required BAD yields
  BAD, and otherwise the result remains incomplete/unreviewed with transport
  failures separate.

## Corpus-import acceptance

When an importer exists, validate it against the repository's real
[workbook](../../docs/reference/v2-dev-troubleshooting.xlsx) and the import
specification. Verify the source checksum before and after and never modify it.

Reconcile source sheet/physical/substantive counts and representative raw cells
to resulting PostgreSQL records and the import report. Confirm:

- blank/separator/structural rows are intentionally classified and no
  substantive row disappears silently;
- source sheet, row, cell, raw-value, formula/display, checksum, mapping version,
  warning, and batch provenance are retained where designed;
- Question and QuestionVersion candidates preserve exact Unicode text;
- known-question history remains visibly legacy/uncontrolled and distinct from
  canonical definitions and controlled Executions;
- `Expected Answer` is legacy guidance, not universal truth;
- raw legacy `Acceptable` values are preserved and map to human judgment only
  under an approved, attributable rule;
- comments, timing/token values and unknown units, answer-size context,
  duplicates, paraphrases, translations, and multilingual text are preserved;
- absent target/build/time/reviewer/binding identity remains unknown rather than
  fabricated; and
- conversation grouping, duplicate identity, placeholders, domains, and split
  rows are not guessed where the source is insufficient.

Exercise idempotent rerun with the same source checksum and mapping version and
report created/linked/skipped/error counts. A successful command exit without
source-to-database reconciliation is insufficient.

## Docker and release-readiness acceptance

Do not claim v1 release readiness without smoke validation of the actual Docker
topology: web container, worker container from the same application image, and
PostgreSQL with durable storage. Migrations are an explicit one-shot step.

From a clean environment, validate startup, migration, first-ADMIN bootstrap,
authentication, worker availability, run launch, persisted progress while the
browser navigates away and returns, container/process restart, worker recovery,
database persistence, configuration/secret injection, and absence of hidden
dependencies on a developer workstation. Confirm the topology adds no broker,
SPA service, SQLite, or Kubernetes dependency.

Release readiness aggregates requirement-specific evidence; one Docker smoke
test cannot replace invariant, migration, worker, RBAC, or trust-boundary
acceptance. Report unavailable external dependencies as BLOCKED for their
affected scope, not as an unconditional release PASS.

## Negative, adversarial, and trust-boundary review

Every material review should include at least one forbidden or failure path.
High-value cases include:

- OPERATOR direct mutation requests and CSRF/session misuse;
- invalid QuestionVersion or mutable historical-record update attempts;
- missing baseline binding and mismatched concrete question;
- duplicate claims, ownership loss, completion races, and worker death mid-call;
- malformed/partial target response, timeout, authentication failure, and
  secret-bearing upstream error text;
- comparator and judge unavailable or malformed;
- comment and evaluated answer containing unsafe HTML/JavaScript;
- pagination/filter boundary cases and concurrent review-queue changes; and
- migration over populated historical rows with unknown/legacy fields.

Give heightened scrutiny and, where practical, independent review to changes in
authentication, authorization, target credentials, secret redaction,
untrusted-output rendering, exports, worker claiming/concurrency, immutable
history, baseline mutation, execution validity, and migrations. This is robust
software acceptance, not expansion into OpsSteward-Sec.

## Relationship to the future harness

This skill defines acceptance principles, evidence, and reporting independent
of any runner. A future executable harness may automate many checks, but its
implementation and assertions must themselves be validated against repository
authority. Do not assume a harness command exists, hard-code this workflow to an
unapproved runner, scaffold harness infrastructure, or turn harness success
into proof broader than its mapped requirements. Manual subsystem validation
remains legitimate when it produces repeatable observable evidence.

## Report completion evidence

Every acceptance report must include:

- requirements/invariants evaluated and their authority;
- environment, database, target fixture, branch, and exact build/commit identity;
- acceptance method and why its evidence is sufficient;
- evidence collected, including relevant persisted state;
- exact commands/actions performed and results;
- PASS, FAIL, or BLOCKED per requirement and overall for the stated scope;
- failures and the smallest reproducible observable behavior;
- defect attribution with supporting and contrary evidence;
- unresolved ambiguity and unavailable validation;
- regression and negative-path scope checked; and
- any remaining risk.

Avoid conclusions such as `seems fine` or `tests pass`. Name which evidence
establishes which requirement. A failed acceptance report should make the
observable violation reproducible without assuming the reader accepts a code
interpretation.

Before finalizing the review, inspect the complete diff and final Git status,
run repository-provided checks appropriate to the scope, and run
`git diff --check`. Do not invent commands, report checks that did not run, or
expand a scoped acceptance task into implementation work.
