# OpsSteward Evaluation Lab

## Status

**Decision:** Create the OpsSteward Evaluation Lab as a repository independent from the OpsSteward application repository.

**Working repository name:** `opssteward-eval`

The Evaluation Lab is intended to remain valid across changes to OpsSteward's implementation, including changes to LLMs, prompts, routing, vector databases, graph databases, source-of-truth systems, APIs, and deployment architecture.

It complements, but is distinct from, `OpsSteward-Sec`, which focuses on adversarial/security evaluation such as prompt injection and other vulnerabilities.

---

## 1. Purpose

OpsSteward Evaluation Lab provides an implementation-independent framework to answer:

> Can OpsSteward correctly, usefully, and efficiently answer the network-operations questions that matter?

The evaluation target is the externally observable product behavior and the supporting evidence, not a particular implementation.

The target-question corpus therefore represents an enduring product contract.

A question such as:

> Which services would be affected if this physical component failed?

must remain answerable regardless of whether a future OpsSteward version uses:

- a different LLM;
- no single monolithic LLM;
- a different vector database;
- a different graph database;
- different source-of-truth systems;
- a different planner/router;
- MCP or another tool protocol;
- different prompt architecture;
- different deployment/runtime architecture.

Implementation changes may change *how* OpsSteward obtains the answer. They should not silently remove required operator capabilities.

---

## 2. Scope

The Evaluation Lab evaluates four broad properties.

### 2.1 Functional correctness

Can OpsSteward answer the question using authoritative evidence?

Examples:

- inventory and attributes;
- L0/L1/L2/L3 topology;
- EVC/service relationships;
- Service Profiles and desired state;
- disjointness policy;
- blast radius;
- power dependencies;
- BGP/BFD/interface events;
- historical topology;
- provenance;
- MOP and Knowledge Base relationships.

### 2.2 Semantic and conversational correctness

Does OpsSteward understand what the operator is asking?

Examples:

- paraphrases;
- unexpected wording;
- multilingual questions;
- temporal expressions;
- follow-up references;
- ambiguous entities;
- questions requiring clarification;
- questions requiring multiple sources.

### 2.3 Operator usefulness

Does the answer actually help a network operator?

Evaluation includes:

- directness;
- useful conclusions;
- appropriate evidence;
- source provenance;
- no unnecessary internal implementation terminology;
- correct cannot-conclude behavior;
- useful next steps where appropriate.

### 2.4 Performance and efficiency

Track over time:

- end-to-end latency;
- p50/p90/p95 latency;
- interpretation latency;
- tool/data-access latency;
- retrieval latency;
- synthesis latency;
- token usage where applicable;
- error rate;
- timeout rate.

Performance is not allowed to substitute for correctness.

---

## 3. Repository Boundary

`opssteward-eval` MUST be independent from the OpsSteward product implementation.

The repository may contain adapters for specific OpsSteward API versions, but the canonical test definitions must not depend on private implementation functions.

Preferred boundary:

```text
Target Question Specification
          |
          v
Evaluation Runner
          |
          v
OpsSteward Public/Supported API
          |
          v
Captured Response + Evidence
          |
          +----------------------+
          |                      |
          v                      v
Deterministic Evaluators     LLM Judge
          |                      |
          +----------+-----------+
                     v
              Evaluation Run DB
                     |
                     v
             Trends / Dashboard
```

Security evaluation remains independently owned by `OpsSteward-Sec`.

---

## 4. Canonical Question Corpus

The target-question corpus is the central asset of this repository.

Questions are derived from operator requirements and network-operations use cases, not from whatever implementation currently exists.

The initial expanded corpus contains approximately 185 target questions spanning:

- service traversal;
- L0 topology;
- L1 topology;
- L2 topology;
- L3 topology;
- Service Profiles;
- Vera Rubin / Rubin LHN;
- disjointness;
- capacity;
- blast radius;
- power;
- temporal/historical reasoning;
- RCA;
- provenance;
- documentation/RAG;
- MOPs;
- visualization;
- conversational follow-ups.

The original source questions should remain immutable. Expanded/concrete questions should be derived from them.

---

## 5. Question Specification

Each executable question should contain metadata such as:

```text
id
domain
question_template
concrete_question
variable_bindings
resolver_strategy
expected_sources
expected_capability
ground_truth_type
expected_behavior
conversation_scenario
prerequisites
temporal_semantics
evaluation_method
```

Execution results are separate from the specification.

Suggested result fields:

```text
run_id
question_id
resolved_question
resolved_bindings
started_at
completed_at
latency_ms
answer
evidence
source_selection
planner_intent
tools_used
normalized_time_window
product_sha
api_image_sha
model_identity
prompt/config identity
deterministic_score
llm_judge_scores
human_score
human_comments
```

---

## 6. Dynamic AmLight Resolvers

Questions should use real AmLight objects rather than fabricated identifiers.

Stable entities may be fixed in the specification.

Examples already useful in testing include:

- `MIA-MI1-SW14`
- `MIA-MI1-RT04`
- `ATL-LUM-RT01`
- `SCL-CIR-SW03`
- `ATL-LUM-SW02`
- `MIA-MI1-PDU11`
- Vera Rubin / Rubin LHN

Objects that should normally be resolved dynamically include:

- L0Adjacency;
- L1Adjacency;
- L2Adjacency;
- InfrastructureSegment;
- Cable;
- BreakoutCable;
- BreakoutCable leg;
- PatchPanelPort;
- Transceiver;
- SitePowerCircuit;
- NodeVirtualTopoPort;
- VRF;
- EVC.

Resolvers should deliberately choose useful objects.

Example:

For:

> If Cable X is damaged, which L1Adjacencies and services are affected?

the resolver should prefer a Cable that participates in an L0 path supporting at least one L1 adjacency and at least one service.

This prevents meaningless evaluation based on arbitrary objects with no relationships.

---

## 7. Ground-Truth Classes

Not every question should be graded the same way.

### 7.1 Deterministic

There is an authoritative factual answer.

Example:

> Which EVCs use L2Adjacency X?

Prefer deterministic comparison with authoritative source data.

### 7.2 Policy

The answer is determined by an OpsSteward-defined policy.

Example:

> Is Service A disjoint enough for Tier 1 policy?

The evaluator must compare observed state against the stored `DisjointnessPolicy`. The LLM must not invent policy semantics.

### 7.3 Analytical

The answer requires evidence synthesis and may not have one exact wording.

Example:

> What is the likely root cause of packet loss on Service A?

The evaluator should assess grounding, reasoning quality, and operator usefulness.

### 7.4 Expected Cannot-Conclude

The authoritative evidence required to answer is absent.

Example:

> Which EVC paths are oversubscribed?

For this question, oversubscription is defined using observed average business-hours utilization. OpsSteward currently lacks that evidence.

The correct result is therefore an explicit inability to conclude, including what evidence is missing.

A fabricated negative answer is a failure.

---

## 8. Temporal Semantics

Relative-time questions are intentionally retained because interpreting them correctly is an important OpsSteward capability.

They must not be converted exclusively into fixed-date tests.

### 8.1 Semantic tests

Example:

> Which interfaces flapped the most last month?

The test evaluates whether OpsSteward normalized the natural-language interval correctly.

Canonical rules:

```text
last month     = previous calendar month
past 30 days   = rolling 30 x 24 hours
yesterday      = previous local calendar day
past 24 hours  = rolling 24 hours
last week      = previous calendar week
past 7 days    = rolling seven days
this month     = current calendar month through now
```

Ambiguous phrases such as `last night` require a documented product convention or clarification.

For month-only historical topology requests, clarification is preferred. If a deterministic default is used, the assumption should be explicit, e.g. `YYYY-MM-01 00:00:00 UTC`.

### 8.2 Temporal evaluation

Each temporal run should record:

```text
run_at
operator_timezone
expected_semantic_type
expected_start
expected_end
opss_interpreted_start
opss_interpreted_end
semantic_time_pass
```

A correct zero-result answer can PASS when there genuinely were no events.

### 8.3 Frozen golden windows

Temporal semantic tests are paired with fixed historical regression windows known to contain relevant events.

Example:

```text
Dynamic semantic question:
Which BGP sessions changed state last month?

Frozen factual regression:
Which BGP sessions changed state between
<known-start> and <known-end>?
```

The first evaluates temporal interpretation.

The second evaluates factual event retrieval.

Maintain a historical-window library containing, when available:

- BGP flap window;
- BFD flap window;
- interface flap window;
- Rubin-impact event window;
- topology/path-change window;
- quiet/no-event window.

Positive and negative windows are both valuable.

---

## 9. L0 Physical Semantics

For:

> Build an L0 topology for a device-to-device path.

the expected physical trace includes all relevant components, including:

```text
device
→ interface
→ transceiver
→ patch-panel port
→ cable/breakout
→ infrastructure segment
→ far-end cable/patching
→ transceiver
→ interface
→ device
```

The exact chain depends on the authoritative model.

For questions asking which component should be `cleaned, scoped, or tested`, `scoped` means optically inspected for contamination/dirt.

---

## 10. L0 → L1 Derivation

Questions such as:

> Which L1Adjacencies are derived from L0Adjacency X?

test the explicit derivation relationship:

```text
L0 physical evidence
        ↓
derived L1 adjacency
```

Endpoint similarity alone is insufficient.

---

## 11. Oversubscription Semantics

For this evaluation corpus, service/path oversubscription is defined using observed average business-hours traffic utilization.

It is NOT defined as merely:

```text
sum(reserved bandwidth) > link capacity
```

Until OpsSteward contains suitable historical utilization evidence, the expected result is:

```text
CANNOT_CONCLUDE
```

with a clear explanation of the missing utilization data.

---

## 12. Disjointness Policy

Tier 1/2/3/4 refer to OpsSteward Service Profile policy tiers.

Questions such as:

> Is the service disjoint enough for Tier 1 policy?

must evaluate observed topology against the stored `DisjointnessPolicy`.

The LLM may explain the evaluation but must not define its own standard of sufficient disjointness.

---

## 13. Root-Cause Analysis

Questions such as:

> What is the likely root cause of packet loss on Service A?

must permit an evidence-based inability to conclude.

A valid answer may be:

> There is insufficient evidence to establish a likely root cause.

Hypotheses should only be ranked when supporting evidence exists.

Evaluation should reward calibrated uncertainty rather than forced diagnosis.

---

## 14. Conversation Scenarios

Follow-up questions must preserve conversation state.

Example:

```text
RUBIN-CONV-01.1
What is the Vera Rubin desired state?

RUBIN-CONV-01.2
Which EVCs support that desired state?

RUBIN-CONV-01.3
Show me those EVCs.

RUBIN-CONV-01.4
Which devices carry them?

RUBIN-CONV-01.5
Show me their primary and backup paths.

RUBIN-CONV-01.6
Are they disjoint?
```

The runner must reuse the same conversation/session identity.

Independent execution of these follow-ups is not an equivalent test.

---

## 15. Evaluation Strategy

Evaluation should be layered.

### Deterministic evaluator

Use whenever ground truth can be calculated from authoritative data.

Examples:

- counts;
- device attributes;
- memberships;
- path components;
- adjacency derivation;
- policy compliance;
- time normalization.

### Dedicated local LLM judge

Use for dimensions that require semantic judgment:

- analytical correctness;
- answer completeness;
- evidence grounding;
- directness;
- operator usefulness;
- clarity;
- calibrated uncertainty;
- language quality.

The LLM judge must not replace deterministic checking where deterministic checking is possible.

### Human reviewer

Initially serves as the gold standard for a representative sample.

The local judge should be calibrated against human evaluation before being trusted for unattended scoring.

Long term, human review should focus on:

- judge disagreements;
- low-confidence evaluations;
- regressions;
- random samples;
- new capability classes.

---

## 16. LLM Judge Contract

The future judge should receive:

```text
question
expected capability
ground-truth type
expected behavior
resolved variables
expected temporal semantics
authoritative evidence where available
OpsSteward source/tool trace
OpsSteward answer
```

It should return structured dimensions rather than one opaque score.

Example:

```json
{
  "intent_correct": true,
  "factually_correct": 4,
  "grounded": 5,
  "operator_useful": 4,
  "direct": 4,
  "language_correct": true,
  "cannot_conclude_correct": null,
  "confidence": 0.91,
  "reason": "..."
}
```

The judge model/version and judge prompt/version must be recorded for every evaluation run.

---

## 17. Longitudinal Tracking

Every test execution is an immutable evaluation run.

Do not overwrite prior results.

Minimum identity dimensions include:

```text
evaluation_run_id
timestamp
OpsSteward Git SHA
deployed API/image SHA
UI SHA if relevant
model identity
embedding model
planner/routing version
prompt/config version
data snapshot/freshness
question-spec version
judge model version
judge prompt version
```

This enables comparison across product changes.

---

## 18. Quality Metrics

Track at minimum:

### Functional

- deterministic correctness rate;
- policy correctness rate;
- cannot-conclude correctness;
- temporal-normalization correctness;
- conversational follow-up correctness;
- multilingual correctness;
- fresh/generalization success rate.

### Answer quality

- grounding;
- completeness;
- directness;
- operator usefulness;
- hallucination rate;
- unsupported-claim rate.

### Performance

- p50 latency;
- p90 latency;
- p95 latency;
- interpretation latency;
- graph/tool latency;
- retrieval latency;
- synthesis latency;
- timeout rate.

### Efficiency

Where models expose usage:

- input tokens;
- output tokens;
- total tokens;
- model invocations per question;
- unnecessary fallback/tool invocation rate.

One composite score should not replace these dimensions.

---

## 19. Regression Analysis

The Evaluation Lab should eventually answer questions such as:

> Did build X improve Rubin reasoning?

> Did a new model improve generalization but increase p95 latency?

> Did a routing change improve correctness while causing more unnecessary RAG calls?

> Did a graph-schema change regress blast-radius questions?

> Did Portuguese accuracy improve?

Comparisons should be possible by:

- build;
- model;
- prompt;
- domain;
- question;
- capability;
- source/tool path.

---

## 20. Proposed Repository Structure

```text
opssteward-eval/
├── README.md
├── pyproject.toml
├── docs/
│   ├── architecture.md
│   ├── methodology.md
│   ├── temporal-semantics.md
│   ├── scoring.md
│   ├── local-llm-judge.md
│   └── adr/
├── specs/
│   ├── target-questions/
│   │   ├── target_questions.yaml
│   │   └── original_source_questions.*
│   ├── conversations/
│   └── temporal-windows/
├── resolvers/
│   ├── amlight/
│   └── base.py
├── adapters/
│   ├── opssteward/
│   │   ├── api_v1.py
│   │   └── api_v2.py
│   └── authoritative_sources/
├── runners/
│   ├── question_runner.py
│   └── conversation_runner.py
├── evaluators/
│   ├── deterministic/
│   ├── policy/
│   ├── cannot_conclude/
│   └── llm_judge/
├── storage/
│   ├── schema/
│   └── migrations/
├── reports/
│   ├── comparison.py
│   └── dashboard/
├── tests/
└── scripts/
```

Exact implementation may evolve, but canonical question specifications should remain isolated from OpsSteward-specific API adapters.

---

## 21. Relationship to OpsSteward-Sec

The repositories answer different questions.

### `OpsSteward-Sec`

Primary question:

> Can an adversary manipulate, exploit, escape, inject, or abuse OpsSteward?

Examples:

- prompt injection;
- malicious documents;
- tool abuse;
- privilege escalation;
- source poisoning;
- unsafe output/action behavior.

### `opssteward-eval`

Primary question:

> Does OpsSteward correctly and usefully perform the network-operations tasks we require?

Examples:

- factual correctness;
- topology reasoning;
- desired-state reasoning;
- temporal reasoning;
- RCA;
- multilingual understanding;
- answer usefulness;
- latency;
- regressions;
- model comparisons.

Results may be correlated in the future, but the repositories should remain independent.

---

## 22. Implementation Independence

The Evaluation Lab explicitly avoids coupling the product contract to current implementation choices.

The following may change without invalidating the evaluation corpus:

```text
LLM provider/model
embedding model
vector database
graph database
relational database
MCP implementation
planner
routing architecture
prompt architecture
RAG implementation
source-of-truth integration
deployment platform
```

If OpsSteward moves from Neo4j to another graph system, for example:

> Which services depend on physical component X?

remains a required capability.

Only the adapter/evidence-validation implementation should change.

---

## 23. Versioning the Evaluation Corpus

Question specifications are themselves versioned product artifacts.

Breaking changes require explicit documentation.

Examples:

- changing what `last month` means;
- changing Tier 1 disjointness semantics;
- changing oversubscription definition;
- removing a required operator capability.

A test should not simply be changed because OpsSteward fails it.

Evaluation-spec changes should distinguish:

```text
PRODUCT_REQUIREMENT_CHANGE
TEST_BUG_FIX
GROUND_TRUTH_UPDATE
DATA_MODEL_EVOLUTION
```

---

## 24. Initial Inputs

Initial repository inputs should include:

- expanded target-question workbook;
- machine-readable target-question export;
- temporal semantic decisions;
- known historical event windows once identified;
- API runner prototype;
- resolver prototype;
- existing Known Questions as a secondary regression suite;
- random/generalization questions as a secondary regression suite.

The target-question corpus becomes the long-lived primary operator-capability specification.

---

## 25. Initial Milestones

### Milestone 1 — Executable corpus

- repository created;
- target questions stored as structured specs;
- OpsSteward API adapter implemented;
- AmLight resolvers implemented;
- conversation execution supported;
- immutable run results stored.

### Milestone 2 — Deterministic scoring

- deterministic fact checks;
- policy checks;
- temporal checks;
- expected-cannot-conclude checks.

### Milestone 3 — Historical temporal fixtures

- positive BGP window;
- positive BFD window;
- positive interface-flap window;
- Rubin-impact window where available;
- quiet negative window.

### Milestone 4 — Local judge

- dedicated pinned local LLM;
- structured judge contract;
- human calibration corpus;
- judge-vs-human agreement measurements.

### Milestone 5 — Longitudinal dashboard

- build comparison;
- domain accuracy;
- question regressions;
- answer-quality trends;
- latency trends;
- model comparison;
- judge confidence/disagreement.

---

## 26. Success Criterion

The Evaluation Lab succeeds when an OpsSteward implementation can be replaced or substantially redesigned and we can still answer, objectively:

> Did the new implementation become better or worse at the network-operations capabilities that matter?

That is the primary reason for maintaining this as an independent repository.
