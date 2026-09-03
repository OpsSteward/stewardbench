# Open questions

Most product behavior and the v1 application architecture are settled. The
following questions still require source-system evidence or product-owner
choice. None should be silently answered during implementation if it materially
changes the specified behavior.

## Integration evidence needed

1. **Exact OpsSteward v1 and v2 API contracts.** Confirm health, question
   request/response, authentication, complete-answer behavior, errors, and v2
   conversation/session semantics. Until confirmed, the adapter contract in
   this repository is normative only at the StewardBench boundary.
2. **Runtime metadata route and wire schema.** This documentation proposes a
   minimal optional payload, but OpsSteward must confirm the route, field names,
   authentication, and compatibility behavior.
3. **Corpus import interpretation and approval.** Workbook structure is now
   inventoried in [Question corpus import](question-corpus-import.md), but the
   source does not define `Acceptable`, reviewer attribution, `Token`/`Total
   time` semantics or units, target-sheet variable syntax, or conversation
   grouping. A source owner/admin must also decide whether target rows 155–156
   are one accidentally split question and how the `Interface Issues` sheet is
   retained. Do not resolve these by inference in an importer.

## Resolved product-owner choices

- **Run cancellation is deferred from v1 (2026-09-03).** It is not an M0
  requirement and must not block M3. Pause/resume also remains out of v1. If
  later worker evidence shows safe cooperative cancellation is effectively free,
  adding it still requires reviewed lifecycle/evidence semantics and acceptance
  coverage before implementation.

## Later technology decisions

4. **Semantic comparator implementation/model/provider.** Select only after
   obtaining representative response pairs and defining an evaluation set for
   dangerous false-equivalence behavior.
5. **LLM judge implementation/model/provider and initial rubric prompt.** The
   interface and retention requirements are set, but the provider/model are not.
6. **Final brand source artwork.** The identity is approved, but final vector
   geometry, spacing, variants, and palette reference values require approved
   source assets.

## Acceptance-harness implementation details

The harness architecture and initial scenario catalog are settled in
[Executable acceptance harness design](acceptance-harness-design.md). Later
implementation must select:

7. **Cross-platform worker process control.** Choose deterministic crash/barrier
   primitives that work for Linux CI, macOS development, and Docker.
8. **Fake-target implementation dependency.** Choose the minimal Python HTTP
   library and packaging command for the already-decided reusable service
   contract.
9. **Playwright browser matrix.** Decide the smallest supported matrix beyond
    the initial Chromium path, based on actual deployment needs.
10. **Docker smoke orchestration.** Decide whether Compose is invoked directly
    or coordinated through pytest while keeping independently reproducible
    steps.
11. **Structured acceptance output.** Choose the compact machine-readable
    format accompanying pytest/JUnit and its future CI artifact-retention rule.

These questions do not reopen settled decisions such as PostgreSQL-only
persistence, Docker for v1, API-only evaluation, two roles, human authority,
or immutable historical observations.
