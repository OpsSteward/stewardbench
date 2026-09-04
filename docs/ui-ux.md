# UI/UX specification

Status: Authoritative v1 interaction specification. It defines information
architecture and behavior without choosing a frontend or web framework.

## Design goal

StewardBench is a desktop-first operations application. It should feel familiar
to users of Nautobot-style object management and Zabbix-style operational
status/trending without cloning either product. The primary screen-level
question is usually:

> What requires the administrator's attention?

Use persistent navigation, breadcrumbs, dense but readable tables, compact
badges, clear filters, bordered cards/panels, direct operational actions, and
charts only where a trend matters. Decorative aggregate metrics and oversized
empty layouts should not displace actionable information.

OPERATOR sees the same evidence and navigation needed for read-only work but no
mutation controls. Hiding controls is not authorization; the server still
enforces every permission.

## Navigation

Recommended persistent left navigation:

1. Dashboard
2. Questions
3. Runs
4. Baselines
5. Comparisons
6. Products
7. Environments
8. Targets
9. Users (ADMIN only)

Evaluator configuration may appear under an ADMIN settings area when actually
implemented. Do not expose empty future-feature navigation.

Every object detail page has breadcrumbs, stable identity, status, relevant
actions, and deep links. List filter state should be URL-addressable so attention
counters, bookmarks, and shared links open the same view. Prefer normal query
parameters with predictable multi-value and date encoding; final encoding is a
framework-phase detail.

## Common status vocabulary

Keep state dimensions visually distinct:

| Dimension | Badges/values | UI rule |
| --- | --- | --- |
| Execution outcome | SUCCESS, ERROR, TIMEOUT (plus in-progress states) | Never label SUCCESS as GOOD. |
| Human judgment | GOOD, BAD, Not reviewed | GOOD/BAD reserved for human authority. |
| Automated outcome | PASS, FAIL, CANNOT CONCLUDE, evaluator error | Include evaluator identity; do not merge mechanisms. |
| Review state | NONE, REQUIRED, REVIEWED | REQUIRED is an attention badge, not a failure judgment. |
| Validity | VALID, INVALID | INVALID remains viewable and is excluded from normal quality metrics. |
| Change state | UNCHANGED, CHANGED, NON-COMPARABLE | CHANGED is not labeled regression. |

Green is primarily semantic GOOD/PASS. Errors/BAD should be clearly distinct;
REQUIRED, CHANGED, uncertain, and NON-COMPARABLE need non-green attention colors
with text/icons so color is never the only cue.

## Dashboard

The landing page is an attention-management interface. Avoid duplicating the
same metric in multiple visual blocks without purpose.

### Primary run panel

Show the latest relevant EvaluationRun with:

- target, environment, product, version, Git SHA/build (unknown visibly stated),
  and execution timestamp;
- run status and requested mode/actual concurrency;
- GOOD, BAD, ERROR, TIMEOUT, and REVIEW REQUIRED counts;
- progress if active: total, completed, running, pending, errors/timeouts, and
  elapsed time; and
- total duration/basic latency when complete.

### Selected-baseline comparison panel

When a baseline comparison exists, show:

- selected baseline and its build/time;
- UNCHANGED;
- CHANGED answer;
- GOOD → BAD;
- BAD → GOOD;
- NON-COMPARABLE; and
- pending REQUIRED review.

Every count that represents an object set or action is a link to the exact
pre-filtered run/execution/comparison rows. Examples:

- `6 Review Required` opens those six current executions;
- `4 GOOD → BAD` opens those four comparison items;
- `2 Errors` opens the two failed executions; and
- `7 Non-comparable` opens the seven items with explanations.

Zero-count cards may be non-interactive if there is no useful list, but their
meaning remains visible.

### Performance trend

Include compact chronological latency and run-duration views. M10 also exposes
p50/p90/p95, throughput, and token medians in accessible tables when captured
data supports them. Sequential/parallel mode, target, and concurrency must be
visible in tooltip/filter context so unlike runs are not misleadingly compared.

## Questions list

Columns should include stable ID, current question text (truncated safely),
domain, tags, lifecycle, current version, most recent execution/result, human
judgment, review state, and last executed time where practical.

Filters:

- text search;
- controlled domain;
- one or more tags; and
- DRAFT/ACTIVE/RETIRED lifecycle.

### Selection semantics

- A row checkbox selects one question.
- Normal multi-select spans rows/pages while the current filter remains stable.
- `Select all matching` means every eligible active Question matching the
  current filter at launch time, not merely the visible page and not the entire
  unfiltered corpus.
- The UI shows the resolved count and filter summary before launch.
- Changing filters after selecting all clears or explicitly recomputes the
  selection; never silently launch a different set.
- A no-filter `Select all matching` selects all eligible active questions.
- One launch chooses exactly one target and sequential or parallel mode.

A production target and/or large run may trigger a concise confirmation showing
target, count, execution mode, maximum/actual concurrency setting, timeout, and
estimated operational caution. This is not an approval workflow.

ADMIN actions include create question, new QuestionVersion, activate/retire,
run selected, and run one. OPERATOR gets view/filter/export affordances only.

## Question detail

This is the permanent longitudinal view of one operator capability. Show:

- stable Question ID and current exact text;
- kind and DRAFT/ACTIVE/RETIRED lifecycle;
- controlled domain and tags;
- current QuestionVersion, `valid_from`, nullable `valid_to`, optional change
  classification/reason, and rationale;
- declared variable/binding requirements;
- latest execution/outcome and target/build/timestamp;
- latest human GOOD/BAD, independent automated results, and review state;
- execution history with links to Execution detail; and
- complete QuestionVersion history.

ADMIN has an obvious `Run this question` action leading to target/mode/binding
confirmation. For a conversation scenario, show ordered turns and run the whole
scenario.

### Longitudinal chart

Chronological execution time is the x-axis. Plot human GOOD/BAD/unreviewed and
relevant execution/evaluator outcomes without pretending that absent review is
GOOD. Each point's tooltip/detail exposes product, target, product version, Git
SHA/build, QuestionVersion, and timestamp.

QuestionVersion boundaries are explicit vertical markers/bands. Filtering can
narrow target/product/build, but software version is never the only x-axis.
Results across materially different versions may be displayed for history while
visually warning that they are not directly comparable.

## Runs list

Columns include run ID, target/environment/product, observed version/build,
started time/by, state, mode/concurrency, total/progress, GOOD/BAD (when reviewed),
errors/timeouts, review-required, duration, and baseline/comparison indicator.

Filters:

- target;
- product version/build identity;
- sequential/parallel mode;
- run state; and
- date range.

Rows link to run detail. ADMIN actions include launch new run and rerun selected
or all from a completed source. Rerun actions always preview a new run; they do
not mutate the source.

## Run detail

The header exposes target revision, product/build snapshot and metadata source,
started/completed times, launching admin, state, requested mode, configured
maximum concurrency, actual concurrency setting, timeout, optional delay, and
source retry/rerun links.

For a running run, a polling-updated progress panel shows:

- total planned;
- completed;
- currently running;
- pending;
- errors/timeouts; and
- elapsed time.

WebSockets are not required. The page may be left and revisited without losing
state. Cancellation and pause/resume are not shown because they are deferred
from v1.

The execution table provides selection, filters, attention-first sorting,
human/evaluator/change/review/validity columns, and links to the review
workstation. Run-level comments appear in a simple chronological append-only
list with ADMIN add control.

After completion, show transparent summary denominators, timing, baseline
comparison action, export if available, rerun selected/all, and baseline
promotion for ADMIN.

## Execution detail / review workstation

This is the primary human-review surface. The first viewport answers:

> What did the product answer, why was this flagged, and is it GOOD or BAD?

### Primary review area

Show prominently:

- exact question and QuestionVersion;
- resolved bindings;
- product/target/build/timestamp;
- execution outcome and any safe error summary;
- current normalized/display answer without hiding access to raw answer;
- independent automated result(s);
- LLM-judge result and dimensions when available;
- comparison/change status and reason;
- current review state;
- authoritative human judgment if present; and
- ADMIN GOOD/BAD controls plus optional comment.

When an answer changed, place the baseline answer and current answer side-by-side
or directly adjacent in this same view, with labels, target/build/time, and
baseline human judgment. No navigation should be required to see the baseline.
Sophisticated sentence-level highlighting is not a v1 requirement.

GOOD/BAD submission records reviewer/time, marks relevant REQUIRED work REVIEWED,
and offers an immediate next-attention action. A correction appends history and
must not silently edit the prior review.

For ERROR/TIMEOUT with no usable answer, emphasize retry, diagnostics, and
validity rather than implying the admin must assign BAD. A human judgment is not
automatically synthesized from transport failure. ADMIN can mark the attention
item REVIEWED without a GOOD/BAD judgment and add an optional comment.

### Sequential review

Use a stable filtered review queue:

```text
Previous ←    37 of 194    → Next
```

The queue context and filter are retained in the URL/session-safe navigation.
After review, an admin can move automatically or with one action to the next
item still requiring review. Previous remains available for verification.
Concurrent changes to the queue must not cause an execution to be silently
skipped; use stable IDs and recompute position visibly.

### Collapsed diagnostics

Below the review area, collapsed by default:

- evidence/provenance;
- raw response and exact raw answer;
- sanitized raw request;
- timing/latency;
- target revision and build metadata, including source/unknown values;
- evaluator and comparator details/versions/errors;
- LLM judge prompt/model identity and structured output;
- append-only comments;
- validity history and ADMIN mark VALID/INVALID action; and
- related/source retry executions.

Raw content is escaped/safely rendered. Large JSON should be readable/copyable
without executing markup. Secret redaction must occur before persistence, not
only in this view.

## Baselines

### Baselines list

Show name, active/inactive, product/target/build/time, source run, total,
reviewed, unreviewed, GOOD, BAD, invalid, errors/timeouts, created at/by, and
attention flag. Multiple baselines may be active if useful; do not imply one
global official baseline.

### Baseline detail

Explain visibly that this is observed historical performance, not ground truth.
Show immutable source run/membership and completeness. If a member execution is
later INVALID, display a persistent admin-attention warning and link to it; do
not remove it from history.

Later reviews/comments/validity decisions are shown as appended history. They do
not alter the baseline's frozen answers, bindings, question versions, or build
identity.

ADMIN can promote an eligible completed run after a completeness summary and
warning. Incomplete review does not automatically block promotion. ADMIN can
activate/deactivate the designation with attribution. There is no approval
workflow or baseline deletion through normal UI.

## Comparison page

The page asks:

> What changed between this run and the baseline, and what requires attention?

### Summary

Show total, UNCHANGED, CHANGED, GOOD → BAD, BAD → GOOD, errors, timeouts,
NON-COMPARABLE, and pending REQUIRED. Each count links to the corresponding
filtered rows.

### Triage table

Default priority:

1. crashes/errors/timeouts;
2. GOOD → BAD;
3. material/uncertain changed answers requiring review;
4. BAD → GOOD;
5. NON-COMPARABLE;
6. UNCHANGED.

Columns include Question, baseline result, current result, execution outcome,
change state/semantic outcome, human transition, review state, target/current
build, and actions. Change and correctness remain separate columns. Clicking a
row opens the Execution review workstation with baseline/current answers already
adjacent.

NON-COMPARABLE rows explain the violated prerequisite (different version,
binding unavailable, concrete question mismatch, or missing baseline
observation). The UI never suggests that a replacement object was chosen.

## Products, environments, and targets

### Products

List/detail pages show stable identity, description, active state, known builds,
targets, and run history. OpsSteward appears as ordinary data. Build display
distinguishes release version from Git SHA/build identifier.

### Environments

List/detail pages show logical context, targets, active state, and linked run
history. AmLight Production is data, not a built-in environment type.

### Targets

List/detail pages show product, environment, classification, active/retired
state, current endpoint/configuration summary, adapter/version, technical
capabilities, current execution policy, admin-declared metadata, latest observed
runtime metadata, health warning, and revision history.

ADMIN can create a new revision to change endpoint/configuration, adapter,
credential reference, or limits. The UI warns that changes affect future runs
only. It never permits editing historical snapshots. Credential values are
injected externally and are never displayed; at most show a non-secret reference
name/status.

Valid classifications are production, development, staging, lab/test, and
external. Historical deployments are inactive/retired targets, not a historical
classification.

## Users

ADMIN-only management provides create/deactivate users, assign ADMIN or OPERATOR,
and appropriate password initialization/reset under the selected authentication
implementation. Do not expose password hashes. No granular permissions,
super-admin, external role mapping, or anonymous user exists.

## Execution filters

Major execution lists should provide URL-addressable combinations of:

- text/question search;
- target;
- version/build/Git SHA;
- domain;
- human GOOD/BAD/not reviewed;
- automated evaluator result and evaluator identity where needed;
- review state;
- validity;
- execution outcome;
- comparison state/transition; and
- date range.

Use object-specific filters and sensible pagination. v1 has no generic report
builder or saved-view subsystem. Bookmarkable URLs cover the immediate sharing
need.

## Conversation presentation

Question/scenario detail shows ordered versioned turns. A ConversationAttempt
detail displays the complete transcript in turn order, shared non-secret session
identity, per-turn outcome/answer/evidence/latency/evaluations/review, and derived
overall human result. Failures remain in place and later turns remain visible.

Retry is labeled `Retry complete conversation` and creates a new run from turn
1; there is no retry-one-dependent-turn action.

## Charts and longitudinal context

Chronological execution time is always the canonical x-axis. Initial useful
trends:

- GOOD/BAD/unreviewed over time;
- REQUIRED count over time;
- answer-change rate over time;
- question latency over time; and
- total run duration over time;
- latency p50/p90/p95; and
- median input/output/total target-reported tokens where available.

Run-level throughput is presented alongside, never in place of, per-question
latency. Every point retains product, target, version, Git SHA/build, timestamp,
QuestionVersion, run mode, and concurrency as applicable through tooltip,
label, filters, or linked detail. Charts must expose missing identity as unknown
rather than grouping it under fabricated values.

## Export

Export is subordinate to the review loop. If inexpensive:

- CSV exports the filtered tabular view with at least question ID/text/version,
  target/build, executed time, execution/automated/human/review/change states,
  observed latency, performance policy/band/delta, target-reported tokens,
  runtime/model context, and validity; and
- JSON exports a complete run with run/target/build identity, exact question and
  bindings, raw and display answers, raw response, evidence, all evaluator/judge
  identities and results, human reviews, comparison state, comments, validity,
  timing, performance-policy assessment, target-reported telemetry, and
  baseline performance/efficiency comparison evidence.

JSON preserves Unicode and structured types. Both formats exclude usable
credentials and clearly mark unknown/legacy fields. No PDF, email, scheduled,
custom-report, or elaborate ZIP export exists in v1.

## Visual identity

Use the approved StewardBench Benchmark Mark concept: gauge + check + connected
network nodes, expressing benchmark/compare/improve. The wordmark is
StewardBench. Navy and blue anchor navigation and identity; green remains
primarily GOOD/PASS semantics. Typography follows a clean sans-serif direction
similar to Inter/Source Sans.

Final source art has not been provided and must not be improvised. Required
future variants are specified in [Brand assets](assets/brand/README.md).

## Usability and safety details

- Desktop operations and keyboard-efficient review are the priority; smaller
  screens may reflow but need not drive layout.
- Do not rely on color alone for any status.
- Preserve readable focus order, labels, table headings, and controls for common
  accessibility needs.
- Confirm consequential ADMIN actions such as large production launch,
  invalidation, baseline promotion, and deactivation with precise object names
  and effects.
- Never use destructive wording for immutable actions: `Retry` and `Rerun`
  explicitly create new records.
- Detailed evidence is collapsed by default but always reachable.
- Unknown data is displayed as `Unknown`, not blank in a way that suggests a
  known empty value.

## M10 performance presentation

Operational views label answer and performance badges explicitly, so two
different meanings of GOOD cannot be confused. Dashboard and list links expose
URL-addressable performance-band, regression, band-degradation, and token
availability sets. Run and question history show p50/p90/p95 external latency,
sample count, throughput separately from per-question latency, and target token
medians where reported. Comparison views show baseline/current latency, band,
raw delta, percentage, tokens, and runtime/model context side by side. Charts
remain supplementary to accessible tables.
