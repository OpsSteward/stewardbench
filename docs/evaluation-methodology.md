# Evaluation methodology

Status: Authoritative v1 evaluation and comparison specification.

## Objective

StewardBench evaluates the externally observable answers of AI-driven
network-operations products. Its v1 method deliberately combines immutable
observations, authoritative human review, independent automated signals, and
conservative change detection. It does not derive comprehensive network truth
or reproduce the evaluated product's reasoning system.

The method is designed for a changing operational network. A different answer
may be legitimate; similarity to an old answer may preserve an old defect.

## Trust hierarchy

1. **Original product response/evidence is the observation.** Store it exactly
   and indefinitely.
2. **Human GOOD/BAD is authoritative when present.** It is the accepted quality
   judgment for v1.
3. **Deterministic/policy evaluator results are independent signals.** They are
   authoritative only within their narrowly defined, reliable contracts; they
   do not overwrite human history.
4. **LLM-judge results are advisory automated signals.** Preserve their model,
   prompt, version, and structured dimensions.
5. **Semantic comparison controls attention, not correctness.** It decides
   whether an answer appears meaningfully changed.
6. **A Baseline is historical comparison, not truth.** It can contain GOOD, BAD,
   unreviewed, errored, or later-invalidated observations.
7. **Comments preserve operational interpretation.** They add context without
   rewriting evidence.

No proprietary composite StewardBench score collapses these layers.

## Separate evaluation dimensions

### Execution outcome

PENDING, RUNNING, SUCCESS, ERROR, and TIMEOUT describe interaction processing.
Target unreachable, authentication failure, malformed response, and unsupported
behavior are classified under ERROR. SUCCESS means a complete answer was
captured; an HTTP 200 alone is insufficient and no success implies GOOD.

### Automated answer evaluation

Each configured evaluator produces its own immutable versioned record. A
successful deterministic/policy evaluator may report PASS, FAIL, or
CANNOT_CONCLUDE. An evaluator exception/unavailability reports evaluator ERROR
with no product outcome. Lack of an evaluator never prevents v1 execution.

### Human judgment

An admin records GOOD or BAD with reviewer, time, and optional comment. There is
no manual 1–5 score, voting, independent-review panel, or adjudication. Human
judgment is authoritative whenever present; disagreeing automated results remain
visible for calibration.

### Review state

Review state answers an attention/workflow question and is not judgment:

- NONE: no change-driven review is currently needed;
- REQUIRED: attention remains outstanding;
- REVIEWED: the required review was performed.

An initial baseline review may record GOOD/BAD even when change-driven state is
NONE. Conversely, REQUIRED has no implied BAD. REVIEWED may accompany either
GOOD, BAD, or no judgment when an infrastructure/error item was triaged without
a usable answer.

### Validity

VALID means the benchmark observation is eligible for ordinary quality metrics.
An admin may mark it INVALID when StewardBench's attempt is not trustworthy.
Invalidity is not product quality, does not delete anything, and requires no
structured reason; an optional comment is sufficient. Baselines containing a
newly invalidated execution are visibly flagged.

### Change state

UNCHANGED, CHANGED, and NON_COMPARABLE describe only baseline relationship.
Execution failures and human-result transitions are displayed separately. Do
not create an enormous combined state enum.

## Initial baseline workflow

1. Import and inspect the corpus; activate intended QuestionVersions.
2. Configure an OpsSteward target, its adapter, fixed/dynamic binding choices,
   and conservative execution policy.
3. Select one, many, or all eligible questions matching the current filter.
4. Launch a background EvaluationRun against exactly one target.
5. Resolve bindings, submit exact questions, and capture response/evidence,
   timing, and identity for every attempt.
6. Review executions sequentially in the workstation.
7. Mark relevant valid answers GOOD or BAD; add comments for operational context.
8. Mark broken benchmark observations INVALID and retry through new runs where
   appropriate.
9. Inspect completion summary and promote the completed run to a named baseline
   when sufficiently useful.

Promotion displays at least total, successfully answered, human reviewed,
unreviewed, invalid, error, and timeout counts. v1 warns but does not prohibit
promotion solely because review is incomplete. The admin owns that decision.

Example display:

```text
Questions:       198
Human reviewed:  194
Not reviewed:      4
Invalid:           2
```

The first baseline is accepted calibration work. It is not presented as
automatically verified ground truth.

## Controlled subsequent workflow

1. Deploy the new patch, commit, or build.
2. Launch the same selected question set against one target and select the
   intended baseline.
3. For each comparison, use the same QuestionVersion, exact binding values, and
   concrete submitted question as the baseline.
4. Capture the current product observation and current runtime/build identity.
5. Compare raw-preserving normalized answers exactly; invoke semantic comparison
   only if unequal.
6. Leave confidently equivalent answers UNCHANGED with no change-driven review.
7. Surface errors/timeouts, material changes, uncertain/error comparisons,
   non-comparable items, and meaningful human transitions.
8. Let the admin review only the attention set and record GOOD/BAD/comments.
9. Preserve all outputs and, when useful, promote a completed run to another
   baseline.

If a frozen object is no longer valid, do not choose a replacement. Mark the
comparison NON_COMPARABLE. A separate generalization run may intentionally use
fresh dynamic bindings, but it is not controlled against that baseline item.
An INVALID baseline/current observation or ERROR/TIMEOUT without two usable
answers is likewise NON_COMPARABLE for answer-change analysis, while validity
and failure remain separate prominent dimensions.

An explicitly controlled replay copies the baseline version, bindings, and
concrete question into its immutable run plan. A normal run that intentionally
uses a newer current QuestionVersion remains valid history, but the differing
item cannot be claimed as a controlled baseline comparison.

## Semantic comparison contract

### Purpose and safety bias

The semantic comparator reduces needless review of punctuation, formatting,
equivalent wording, harmless reordering, and stylistic improvements. Its most
dangerous error is false equivalence: hiding a materially changed answer.
Therefore v1 accepts false-positive review alerts and treats uncertainty as
REQUIRED.

The comparator detects change; it does not establish current network facts,
infer root cause, or label regression.

### Inputs

- exact QuestionVersion identity and question text/template;
- exact concrete submitted baseline and current questions;
- resolved baseline and current bindings;
- baseline raw and normalized/display answer;
- current raw and normalized/display answer;
- relevant non-secret evaluator context/evidence permitted by configuration;
- baseline/current execution outcomes; and
- comparator identity/configuration/version.

Comparability is checked before semantic interpretation. Raw answers are retained
regardless of normalization.

### Outputs

The semantic result is one of:

- EQUIVALENT: no meaningful factual/conclusion/content change found;
- MATERIAL_CHANGE: meaningful content changed;
- UNCERTAIN: equivalence cannot be established safely; or
- ERROR: comparator did not produce a usable result.

Record versioned rationale/evidence sufficient for admin understanding, without
pretending it is a network-causality explanation. Confidence may be retained if
the chosen method supplies it, but sophisticated calibration is not required for
the first implementation.

### Explainable pipeline

1. Verify same QuestionVersion, exact bindings, and concrete question. Otherwise
   NON_COMPARABLE.
2. Compare deliberately conservative normalized representations. Exact equality
   yields UNCHANGED without an expensive semantic call.
3. If unequal, invoke the versioned semantic comparator.
4. EQUIVALENT is recorded as a separate semantic result. The immutable M6
   exact result remains CHANGED, but semantic triage may resolve only the
   exact-change-only review requirement.
5. MATERIAL_CHANGE remains a semantic result alongside exact CHANGED and
   retains/requires review.
6. UNCERTAIN or ERROR does not yield equivalence; surface REQUIRED and preserve
   the comparator failure/uncertainty without rewriting exact evidence.

Normalization may standardize safe rendering and insignificant whitespace but
must not erase facts, entity names, malformed output, unsupported claims, or
implementation leakage.

### Changes normally safe to consider equivalent

- punctuation or inconsequential whitespace;
- harmless formatting differences;
- equivalent wording;
- reordered statements preserving meaning and relationships; and
- stylistic improvement without changed facts, conclusion, or completeness.

### Changes normally surfaced

- different entities, relationships, counts, times, or conclusions;
- newly missing operator-relevant information;
- new unsupported claims;
- changed cannot-conclude behavior;
- malformed, nonsensical, or incomplete response;
- internal implementation/code leakage;
- crash, adapter error, or timeout compared with prior success; and
- any substantial semantic change or uncertain judgment.

This list guides calibration; it is not a comprehensive automatic oracle.

## Baseline quality and result transitions

Baseline similarity and answer quality are independent:

| Baseline human | Current similarity/result | Interpretation |
| --- | --- | --- |
| BAD | Semantically equivalent, unreviewed | The current answer is not GOOD merely because it reproduced history; display BAD → unreviewed context. |
| BAD | Changed, current human GOOD | BAD → GOOD improvement plus changed answer. |
| GOOD | Changed, current human GOOD | Legitimate change or equivalent quality after network change; it is not a regression. |
| GOOD | Current human BAD | GOOD → BAD regression-like transition requiring priority, regardless of similarity. |

Transitions require actual human judgments on both sides. Do not infer a current
BAD from ERROR/TIMEOUT; show the failure independently and prominently.

Use `regression` cautiously. Strong regression-like evidence includes a new
crash/timeout after baseline success, malformed/nonsensical output, code leakage,
human GOOD → BAD, or reliable deterministic PASS → FAIL. A factual CHANGED state
alone is not a regression.

## Automated evaluators

Evaluation mechanisms are configured and recorded independently:

- deterministic evaluator;
- policy evaluator;
- expected-cannot-conclude evaluator;
- LLM judge; and
- human review.

For a narrow deterministic evaluator, document its inputs, assumptions,
authoritative data source if any, PASS/FAIL/CANNOT_CONCLUDE semantics, and
version. Do not require such an evaluator for every question and do not build
StewardBench access to operational systems solely to emulate OpsSteward.

Historical expected-answer workbook text begins as guidance/legacy expectation,
not an executable universal rule. Question-by-question evidence may later
justify a deterministic evaluator.

## LLM judge

An LLM judge may return distinct dimensions such as:

- grounding;
- completeness;
- directness;
- operator usefulness;
- calibrated uncertainty; and
- language quality.

Retain original judged answer/evidence references, model/provider identity,
judge version, prompt/version, raw structured output where safe, parsed
dimensions, timestamps, and errors. Never overwrite a prior judge result.

If the judge and a human disagree, the human GOOD/BAD is accepted and the judge
result remains visible. This disagreement is calibration evidence. Judge
unavailability or malformed output is evaluator ERROR, not product BAD.

## Conversation evaluation

A ConversationScenario is run in full from turn 1 through its final turn using
one target conversation/session identity. Each turn is an atomic Execution with
its own:

- exact question and resolved bindings;
- answer and raw response;
- evidence/provenance;
- latency and execution outcome;
- automated evaluator and LLM-judge records; and
- optional human GOOD/BAD.

A failed turn does not stop later turns. This preserves evidence about recovery
and contextual behavior. If protocol failure makes later turns impossible,
record explicit turn-level infrastructure errors rather than pretending they
were answered.

The UI shows the complete ordered transcript. Overall human conversation result
is GOOD only when every required turn is human GOOD. Any required BAD yields
overall BAD; otherwise it is incomplete/unreviewed. A retry always reruns the
complete scenario in a new run and session.

## Review prioritization

Comparison triage should order attention approximately:

1. execution crashes/errors/timeouts;
2. authoritative GOOD → BAD transitions;
3. material or uncertain changed answers requiring review;
4. BAD → GOOD transitions;
5. NON_COMPARABLE items;
6. UNCHANGED items.

This order is a UI priority, not a single severity enum. Every actionable count
opens the corresponding filtered list.

## Metrics

Normal product-quality metrics exclude INVALID executions and clearly state the
denominator. Prefer transparent reporting, for example:

> 168 / 181 evaluable questions passed — 92.8%

The display must identify whether `passed` means human GOOD or the result of a
named automated evaluator; it must never mix mechanisms in one numerator.

Relevant measures include:

- human GOOD/BAD/unreviewed;
- independent evaluator PASS/FAIL/CANNOT_CONCLUDE and evaluator errors;
- execution ERROR/TIMEOUT;
- REQUIRED/REVIEWED counts;
- UNCHANGED/CHANGED/NON_COMPARABLE;
- human result transitions;
- run duration and latency average/p50/p90/p95; and
- questions/minute, questions/second, error rate, timeout rate, and parallel
  efficiency when sufficient data and like-for-like execution conditions exist.

Never compare sequential and parallel performance, different targets, or other
materially different run conditions without displaying those dimensions.

v1 has no configurable pass/fail threshold framework and no proprietary
aggregate score. Each independent evaluator defines and versions its own narrow
semantics; human review remains GOOD/BAD.

## Live-network interpretation

StewardBench preserves what it observed but does not snapshot the whole AmLight
network for each run. When an answer changes, an admin may consult external
operational systems and record the conclusion in run/execution comments. v1 has
no structured taxonomy for maintenance, deployments, data synchronization,
outages, or legitimate network changes and no external-event correlation
subsystem.

Stable control/canary objects may be represented through fixed bindings and tags
such as `control` or `canary`. They do not receive special v1 machinery.

Known historical event/quiet windows may be retained as lightweight
HistoricalFixtures containing an environment, interval, and fixed parameters or
bindings. These fixtures are inputs, not infrastructure snapshots or answer
oracles. OpsSteward 1.0.4 may help identify useful windows over time; lack of
useful v2 history and an incomplete fixture library do not block StewardBench
v1.

## Historical reevaluation

Raw answers, evidence, evaluator context, and version identities are retained so
a future Judge v2 or comparator can operate without rerunning the product. Such
work must append versioned results. v1 does not include historical bulk
regrading, and future regrading never changes what the original evaluator or
human recorded.
