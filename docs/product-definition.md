# Product definition

Status: Authoritative v1 product specification

Product: StewardBench

Descriptor: AI Network Operations Evaluation Platform

## Purpose

StewardBench is an implementation-independent evaluation and benchmarking
platform for AI-driven network-operations systems. It evaluates externally
observable product behavior through supported APIs. It is not part of the
evaluated product and must not reproduce that product's internal reasoning
architecture.

OpsSteward is the first evaluated **Product**. AmLight Production is the first
logical **Environment**. The initial **Evaluation Targets** are:

| Target | Current endpoint at project inception | Initial observed release | Classification | Environment |
| --- | --- | --- | --- | --- |
| OpsSteward Production | `http://dgx.amlight.net:30081` | `1.0.4` | production | AmLight Production |
| OpsSteward Development | `http://dgx.amlight.net:30084` | `2.0.0-dev` | development | AmLight Production |

These values are seed configuration, not domain constants. Versions and
endpoints will change. Product, environment, target, and build identities must
be represented independently.

Users may navigate results conceptually as Product → Build/Version → Evaluation
Target → EvaluationRun → Execution. That is a reporting path, not containment:
stable Target identity and Build identity are independent, so one target may run
many builds over time and one build may be deployed more than once.

## Operational problem and success criterion

Manual OpsSteward evaluation takes hours: submit approximately 200 questions,
wait, inspect, classify, document, repeat after a deployment, and determine by
hand what changed.

StewardBench v1 succeeds when an administrator can:

1. load and activate the existing question corpus;
2. select one or all matching questions and one OpsSteward target;
3. execute sequentially or with safely bounded parallelism;
4. review answers as GOOD or BAD and create a named human-reviewed baseline;
5. rerun the same controlled questions after a patch, commit, or build;
6. immediately identify failures, material changes, uncertain comparisons, and
   result transitions that require attention; and
7. review that reduced set without losing any original evidence or history.

The first baseline remains labor-intensive by design. v1 automates repetition
and change detection; it does not eliminate network-operator judgment.

## Product principles

1. **Evaluate observable behavior.** Canonical questions express enduring
   operator capabilities. An internal LLM, graph, RAG, planner, prompt, or data
   architecture change does not redefine the question.
2. **Remain product-independent.** Question specifications, run orchestration,
   evaluation records, and comparison semantics cannot contain OpsSteward- or
   AmLight-specific assumptions. Product API differences belong in adapters.
3. **Preserve observations.** Exact submitted questions, bindings, responses,
   evidence, timestamps, build identity, evaluations, reviews, and comments are
   retained indefinitely by default.
4. **Separate facts from judgments.** Execution outcome, automated evaluation,
   human judgment, answer-change state, review state, and validity are
   orthogonal dimensions.
5. **Treat the live network as mutable.** A materially changed factual answer
   may be correct because the network changed. Changed does not mean regressed.
6. **Use humans as v1 accepted authority.** Human GOOD/BAD is authoritative
   when present. Baselines are historical observations, not answer keys.
7. **Conserve human attention safely.** Exact and semantic comparison may
   suppress harmless change, but uncertainty becomes REVIEW REQUIRED. Hiding a
   meaningful change is worse than requesting some extra review.
8. **Keep v1 small.** Optional infrastructure, integrations, evaluators, and
   reports must not delay the core loop.

## Users and authorization

Authentication is required; there is no anonymous access. v1 has exactly two
roles:

| Capability | ADMIN | OPERATOR |
| --- | --- | --- |
| View dashboard; products/environments/targets; questions/versions; runs/executions; answers/evidence; automated and LLM-judge results; human judgment/review state; comments; baselines/comparisons; and trends | Yes | Yes |
| Manage users and assign either v1 role | Yes | No |
| Manage products, environments, targets, and target execution settings | Yes | No |
| Create/version/activate/retire questions | Yes | No |
| Launch, retry, or rerun evaluations | Yes | No |
| Record GOOD/BAD reviews and mark review work complete | Yes | No |
| Add append-only comments or change execution validity | Yes | No |
| Create, activate, or deactivate baselines | Yes | No |
| Manage evaluator configuration when available | Yes | No |

All authorization is enforced server-side. All admins are equivalent; v1 has
no super-admin, project-owner role, granular permissions, approval queue, or
operator submission workflow.

The first admin is created through a deployment/administrative bootstrap
command. Later users are managed in the UI. Local username/password
authentication is deliberately isolated behind an authentication boundary so
it can be replaced later if operational need justifies it.

## Primary workflows

### Initial human-reviewed baseline

1. An admin imports and activates canonical questions.
2. The admin configures one target and conservative execution limits.
3. The admin filters/selects questions or selects all questions matching the
   current filter, then launches one run against that target.
4. A durable background process resolves bindings, executes the questions, and
   captures results while the browser may navigate away.
5. The admin reviews executions efficiently in sequence, recording GOOD or BAD
   and comments where useful.
6. Benchmark failures can be marked INVALID and retried through new runs.
7. The admin promotes the completed run to an immutable named baseline after
   considering its visible review-completeness warning.

Baseline promotion is not an approval workflow. A baseline may contain GOOD,
BAD, unreviewed, or later-invalidated executions. The UI shows its completeness
and health; it does not silently reinterpret or repair it.

### Patch or commit evaluation

1. A new product build is deployed to a target.
2. The admin launches the same selected questions and chooses a baseline.
3. Controlled comparison reuses each baseline execution's exact
   QuestionVersion, resolved bindings, and concrete submitted question.
4. The run captures current answers, evidence, timing, and observed build
   metadata.
5. Exact comparison is attempted first; unequal answers go to a conservative
   semantic comparator.
6. Equivalent answers need no change review. Errors, timeouts, material changes,
   and uncertain comparisons are surfaced. Human result transitions are shown
   independently when current review exists.
7. The admin reviews required items, records GOOD/BAD and optional comments,
   and may later promote the completed run as another named baseline.

### Retry and rerun

- Retrying one execution creates a new one-question EvaluationRun and new
  Execution linked to the source execution/run.
- Rerun selected and rerun all each create a new EvaluationRun.
- Completed runs are never reopened and existing executions are never replaced.

### Conversation scenario

An admin runs a complete ordered scenario from turn 1. All turns share one
target conversation/session identity. A failed turn is recorded but does not
stop later turns. Retry reruns the whole scenario from turn 1. The full
transcript and per-turn answer, evidence, latency, automated evaluation, and
human review remain available. Overall conversation GOOD requires every
required turn to be GOOD.

## v1 scope

v1 includes:

- Docker-based deployment and PostgreSQL-only persistence;
- local authentication and ADMIN/OPERATOR authorization;
- product, environment, target, target-revision, and execution-policy management;
- question corpus import, stable Questions, temporal QuestionVersions, domains,
  tags, rationale, and DRAFT/ACTIVE/RETIRED lifecycle;
- one/many/all-matching selection against one target per run;
- sequential and bounded-parallel background API execution;
- initial OpsSteward API adapter, raw/normalized response capture, target errors,
  and optional runtime metadata discovery;
- single-turn questions and ordered conversation scenarios;
- independent automated evaluator and LLM-judge records when configured;
- admin human GOOD/BAD review and append-only comments;
- named immutable baselines and controlled baseline comparison;
- conservative exact/semantic answer-change detection;
- NONE/REQUIRED/REVIEWED workflow independent of judgment;
- VALID/INVALID handling without deletion;
- dashboard, questions, runs, execution-review, baseline, comparison, target,
  environment, product, and user views;
- longitudinal result and basic performance tracking;
- indefinite history retention; and
- CSV/JSON export only if inexpensive after the core loop works.

See [Roadmap](roadmap.md) for sequencing within and after v1.

## Explicit v1 non-goals

StewardBench v1 does not include:

- reproduction of OpsSteward's reasoning, routing, RAG, or planner architecture;
- comprehensive independent authoritative-answer generation;
- browser/UI automation of OpsSteward;
- MCP evaluation;
- Kubernetes deployment;
- CI/CD-triggered evaluation or automatic deployment blocking;
- public/anonymous access, OIDC, Authentik, LDAP, SAML, MFA, or external role mapping;
- granular RBAC, review voting, adjudication, or baseline approval workflows;
- scheduled evaluation, multi-target fan-out, or prerequisite suite management;
- sophisticated dynamic resolver, throttling, queue, or workload-orchestration systems;
- first-class external-event correlation or per-run operational-system snapshots;
- a general audit subsystem, saved report builder, PDF/email/scheduled reports,
  or elaborate evidence packages;
- a user-facing evaluation CLI or comprehensive public API;
- object storage or general visual-artifact persistence;
- bulk historical regrading UI or perfect automatic semantic interpretation;
- configurable composite scores, arbitrary pass thresholds, or question priority;
- target flags for operator capabilities such as L0, BGP, or Rubin; or
- use of GitHub to reconstruct deployed build identity.

## Evaluation philosophy and trust hierarchy

The practical v1 hierarchy is:

1. the immutable product response and returned evidence are the observation;
2. human GOOD/BAD is authoritative when present;
3. deterministic and policy evaluators are independent signals when available;
4. LLM-judge results are advisory, versioned signals;
5. the semantic comparator determines change/attention, not correctness;
6. a baseline supplies historical comparison, not universal truth; and
7. comments preserve operational context without rewriting history.

No composite StewardBench score obscures these signals. Transparent counts and
rates are preferred: GOOD/BAD, PASS/FAIL/CANNOT_CONCLUDE, execution errors and
timeouts, review required, changed, non-comparable, and latency statistics.

## Terminology

| Term | Definition |
| --- | --- |
| Product | An AI-driven network-operations system being evaluated, such as OpsSteward. |
| Environment | A logical operational environment or data context, such as AmLight Production. |
| Evaluation Target | A configured deployment/interface of a Product that StewardBench can query. |
| Target configuration revision | A temporally identifiable endpoint, credential reference, adapter choice, capabilities, and execution policy for a Target. |
| Build | The precise software identity observed for an execution, preferably including Git SHA or another build identifier. |
| Question | The stable identity of an operator capability/question. |
| QuestionVersion | The exact, temporally bounded definition used for execution. |
| Resolved Binding | A concrete value substituted for a question variable, such as a specific EVC. |
| Evaluation Run | One admin-triggered operation against one target, containing one or more Executions. |
| Execution | One attempt to submit one question or conversation turn and capture its response. |
| Execution outcome | Transport/process outcome such as SUCCESS, ERROR, or TIMEOUT; not answer quality. |
| Human Review | An admin's GOOD or BAD judgment, with reviewer and timestamp. |
| Baseline | A named immutable reference to observations in a completed run; not universal ground truth. |
| Changed Answer | A current answer materially different from its comparable baseline answer. It is not necessarily wrong. |
| Review Required | A state indicating that human attention is needed; separate from GOOD/BAD. |
| Invalid Execution | A preserved execution excluded from normal product-quality metrics because the benchmark observation is not trustworthy. |
| Regression | A conclusion used cautiously for evidence such as GOOD → BAD, a new crash/timeout, malformed output, leakage, or reliable deterministic failure—not a synonym for every answer change. |

## Relationship to the original blueprint

The historical [OpsSteward Evaluation Lab blueprint](reference/OPSS_EVALUATION_LAB_BLUEPRINT.md)
is preserved unchanged as reference material. It supplied the independent
repository boundary, enduring operator-question corpus, supported-API focus,
versioned immutable observations, conversation handling, layered evaluation,
and longitudinal comparison direction retained here.

The current specifications deliberately simplify that historical direction:
human-reviewed baselines are the primary v1 accepted reference instead of a
comprehensive answer-oracle architecture; dynamic resolvers are optional;
external-event correlation, bulk historical regrading, CLI, CI integration,
Kubernetes, and MCP are deferred. These are intentional later StewardBench
product decisions, not accidental omissions, and take precedence over the
blueprint's proposed milestones and repository structure.

See [Reference material](reference/README.md) and
[Evaluation methodology](evaluation-methodology.md).

## M10 performance and efficiency evidence

Human GOOD/BAD remains the operator's assessment of answer accuracy and
usefulness only. Each Execution also retains StewardBench-observed end-to-end
request latency, excluding worker queue wait, as immutable benchmark evidence.
`opss-performance-v1` classifies completed responses as TARGET (≤1 s), GOOD
(≤2 s), ACCEPTABLE (≤5 s), SLOW (≤10 s), or BAD (>10 s). Target-reported token
usage and runtime/model identity are first-class efficiency/context evidence
when supplied, but tokens have no global GOOD/BAD classification. Answer,
execution outcome, performance, efficiency, and baseline change remain
orthogonal.
