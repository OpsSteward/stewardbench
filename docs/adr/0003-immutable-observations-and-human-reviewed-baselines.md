# ADR 0003: Immutable observations and human-reviewed baselines

- Status: Accepted
- Date: 2026-09-03

## Context

The original evaluation-lab direction contemplated broad authoritative-source
answer derivation. Reproducing an AI network-operations product's routing and
reasoning inside StewardBench would create a second system whose correctness
must also be established. Meanwhile, the immediate need is to stop manually
repeating and comparing roughly 200 questions after every patch.

The operational network changes over time, so answer equality is not correctness
and answer difference is not automatically regression.

## Decision

Terminal EvaluationRuns/Executions are immutable historical observations.
Retries and reruns create new runs. Exact question/version, bindings, raw and
normalized answer, evidence, timing, target revision, and build snapshot are
retained indefinitely.

Admins perform simple GOOD/BAD review. Human judgment is authoritative when
present. Automated evaluators and LLM judges remain independent, immutable,
versioned signals, including their errors.

An admin may promote a completed run to a named immutable Baseline. A Baseline
represents observed product/build performance and may contain BAD or unreviewed
answers; it is not ground truth. Promotion warns about completeness without a
complex approval gate.

Controlled comparison uses the same QuestionVersion, resolved bindings, and
concrete question. Exact then conservative semantic comparison detects change;
uncertain/error results require human review. Similarity and current quality are
separate dimensions. Invalid observations remain preserved and are excluded
from normal quality metrics.

## Consequences

- The initial baseline requires substantial human work by design.
- Subsequent runs can focus attention on failures and meaningful/uncertain
  changes while retaining operator authority.
- BAD baseline answers are not targets to reproduce.
- Comprehensive authoritative-source evaluators are not a v1 prerequisite;
  narrow reliable evaluators can be added later.
- Reviews, comments, evaluator results, validity decisions, and comparison
  results append history instead of modifying captured product evidence.
- Raw evidence permits future regrading without rerunning the product, but v1
  has no bulk historical-regrading UI.

See [Evaluation methodology](../evaluation-methodology.md) and
[Domain model](../domain-model.md).
