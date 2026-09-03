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

## Product-owner choice

4. **Run cancellation in v1.** A simple cooperative cancel could be useful for a
   long run, but introduces worker state and unstarted-item semantics. Decide
   through product-owner review whether it is sufficiently valuable for v1. If
   omitted, make the deferral explicit in UI copy. Pause/resume remains out of
   scope either way.

## Later technology decisions

5. **Semantic comparator implementation/model/provider.** Select only after
   obtaining representative response pairs and defining an evaluation set for
   dangerous false-equivalence behavior.
6. **LLM judge implementation/model/provider and initial rubric prompt.** The
   interface and retention requirements are set, but the provider/model are not.
7. **Final brand source artwork.** The identity is approved, but final vector
   geometry, spacing, variants, and palette reference values require approved
   source assets.

These questions do not reopen settled decisions such as PostgreSQL-only
persistence, Docker for v1, API-only evaluation, two roles, human authority,
or immutable historical observations.
