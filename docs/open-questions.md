# Open questions

Most product behavior and the v1 application architecture are settled. The
following questions still require source-system evidence or product-owner
choice. None should be silently answered during implementation if it materially
changes the specified behavior.

## Deployment-specific integration evidence

1. **Exact OpsSteward v2 API contract.** OpsSteward v1.0.4 Production is live
   certified for session-cookie `/api/chat` and `/api/version`, including
   complete answers, structured table/summary preservation, and optional
   telemetry. Confirm the separate v2 request/response, health, error, and
   conversation/session semantics before making any v2 certification claim.
2. **OpsSteward v2 runtime metadata compatibility.** The v1 Production
   `/api/version` route and fields are observed. A future v2 target must still
   confirm its route, field names, authentication, and compatibility behavior.

## Resolved product-owner choices

- **Run cancellation is deferred from v1 (2026-09-03).** It is not an M0
  requirement and must not block M3. Pause/resume also remains out of v1. If
  later worker evidence shows safe cooperative cancellation is effectively free,
  adding it still requires reviewed lifecycle/evidence semantics and acceptance
  coverage before implementation.
- **StewardBench workbook mapping v1 is approved for M2 (2026-09-03).** It
  supplies the product-owner target-block taxonomy, merges target rows 155–156,
  maps deterministic legacy Yes/No values to imported GOOD/BAD evidence,
  imports random rows as Generalization Questions, links four KB/RAG experiments
  to one Question, excludes `Interface Issues`, and defers conversation grouping
  and formal bindings. Missing reviewer/time/target/build identity and unknown
  token/timing units intentionally remain unknown rather than open M2 blockers.

## Optional provider configuration (v1) and v1.x learning

3. **Semantic comparator implementation/model/provider.** Select only after
   obtaining representative response pairs and defining an evaluation set for
   dangerous false-equivalence behavior.
4. **LLM judge implementation/model/provider and initial rubric prompt.** The
   interface and retention requirements are set, but the provider/model are not.
5. **Final brand source artwork (v1.x).** The identity is approved, but final vector
   geometry, spacing, variants, and palette reference values require approved
   source assets.

## v1.x acceptance-harness implementation details

The harness architecture and initial scenario catalog are settled in
[Executable acceptance harness design](acceptance-harness-design.md). Later
implementation must select:

6. **Cross-platform worker process control.** Choose deterministic crash/barrier
   primitives that work for Linux CI, macOS development, and Docker.
7. **Fake-target implementation dependency.** Choose the minimal Python HTTP
   library and packaging command for the already-decided reusable service
   contract.
8. **Playwright browser matrix.** Decide the smallest supported matrix beyond
    the initial Chromium path, based on actual deployment needs.
9. **Docker smoke orchestration.** Decide whether Compose is invoked directly
    or coordinated through pytest while keeping independently reproducible
    steps.
10. **Structured acceptance output.** Choose the compact machine-readable
    format accompanying pytest/JUnit and its future CI artifact-retention rule.

These questions do not reopen settled decisions such as PostgreSQL-only
persistence, Docker for v1, API-only evaluation, two roles, human authority,
or immutable historical observations.

## Resolved for M10: performance evidence

The initial global policy is `opss-performance-v1`: TARGET ≤1000 ms, GOOD
≤2000 ms, ACCEPTABLE ≤5000 ms, SLOW ≤10000 ms, BAD >10000 ms. Future threshold
changes require a new policy version, never edits to v1 semantics. Token usage
is captured only when target-reported; per-domain efficiency thresholds and
estimated-token support remain future questions.
