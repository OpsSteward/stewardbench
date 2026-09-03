# Question corpus and import specification

Status: Authoritative mapping approach; workbook structure inspected, with
source semantics and row-level mappings still requiring explicit review.

## Source availability

The source [v2 development troubleshooting workbook](reference/v2-dev-troubleshooting.xlsx)
is preserved in the repository. It was inspected read-only on 2026-09-03; it
was not modified, normalized, transformed, or imported.

Inspection identity:

- filename: `v2-dev-troubleshooting.xlsx`;
- SHA-256: `559ad19500eae888c250c38d3c7213bdf38912d611cd0dbc4dfa2556fa6ec8ff`;
- workbook creator/last modifier: `Jeronimo Bezerra`;
- workbook-created timestamp: `2026-09-02T14:48:17Z`;
- workbook-modified timestamp: `2026-09-02T20:59:19Z`; and
- embedded Microsoft information-protection label name: `Internal or Private
  Data`.

File metadata is provenance, not evidence of target, build, execution, review,
or question-version time. An implementation must preserve and handle the source
according to its information-protection classification.

Do not invent absent columns, timestamps, identifiers, groupings, or semantics.

## Import objectives

The import must:

- establish stable first-class Questions and exact QuestionVersions;
- preserve useful historical answers, expectations, acceptability, comments,
  timing, and token observations;
- distinguish controlled StewardBench Executions from incomplete legacy/manual
  observations;
- retain source sheet/row traceability and missing metadata honestly;
- avoid destructive normalization or accidental deduplication; and
- avoid treating legacy Expected Answer text as universal ground truth.

The workbook is an input dataset, not the StewardBench domain model.

## Inspected workbook inventory

`Meaningful rows` below excludes a header row and rows with no stored formula or
nonblank value. Worksheet dimensions can be larger because Excel retained cell
formatting.

| Exact sheet name | Exact columns | Meaningful rows | Blank/structural behavior | Initial role |
| --- | --- | ---: | --- | --- |
| `known questions` | `Question`, `Answer`, `Expected Answer`, `Acceptable`, `Comments` | 39 data rows, worksheet rows 2–40 | No blank/separator data rows | Secondary Questions plus legacy observations |
| `knowledge base - rag questions` | `Question`, `Answer Size`, `Comment`, `Token`, `Total time`, `Acceptable`, `Comments` | 4 data rows, worksheet rows 2–5 | Rows 6–57 and cells H:AD are formatted but blank | One repeated Question plus four legacy experiment records; not a generic parameter model |
| `Interface Issues` | `Issue`, `Description` | 17 issue rows, worksheet rows 2–18 | No blank/separator data rows | Auxiliary source issue log, not automatically question corpus data |
| `random question` | `Question`, `Answer`, `Expected Answer`, `Acceptable`, `Comments` | 13 data rows, worksheet rows 2–14 | Rows 15–27 are formatted but blank | Secondary generalization/multilingual Questions plus legacy observations |
| `target questions` | No header; populated values occur only in unnamed column A | 186 nonblank cells, worksheet rows 2–202 | Row 1 is unused; 15 internal blank rows visually separate 16 unlabeled blocks | Primary canonical Question candidates, subject to row-level review |

All five worksheets are visible. Inspection found no hidden rows or columns,
merged cells, formulas, or formula-error cells. The internal blank rows in
`target questions` are 7, 18, 26, 37, 49, 64, 77, 88, 105, 116, 130, 142, 157,
167, and 183. Because the blocks have no labels or domain column, their visual
grouping does not prove a taxonomy.

### Column coverage and raw values

- `known questions` has `Question` and `Answer` in all 39 data rows. `Expected
  Answer` and `Acceptable` occur in 38 rows (both are absent in row 32).
  `Comments` occurs in 22 rows.
- `random question` has `Question`, `Answer`, and `Acceptable` in all 13 data
  rows. `Expected Answer` occurs in 10 rows and is absent in rows 5, 6, and 10.
  Its `Comments` column has no data values.
- `knowledge base - rag questions` has all seven columns populated in each of
  its four data rows. It has no `Answer` column.
- `Interface Issues` has both `Issue` and `Description` in all 17 issue rows.
- `target questions` has no answer, expected-answer, acceptability, reviewer,
  comment, timing, token, domain, identifier, scenario, or binding column.

These counts describe source cells, not final Question or LegacyObservation
counts. In particular, `target questions` rows 155 and 156 contain the two text
fragments `Which validation findings affect this device, interface, adjacency,
service,` and `or infrastructure segment?`. They may be one accidentally split
question, which would explain the blueprint's approximate count of 185, but the
workbook does not prove that interpretation. Preserve both rows and require an
explicit mapping decision.

## Import classification

Every non-blank candidate source row receives one of these migration roles after
inspection:

1. **QUESTION_DEFINITION** — creates or links a stable Question and its initial
   QuestionVersion.
2. **LEGACY_OBSERVATION** — preserves an observed answer/evidence/timing/
   acceptability record without pretending it is a fully controlled run.
3. **QUESTION_AND_OBSERVATION** — supplies both a definition and historical
   evidence, common in `known questions`.
4. **STRUCTURAL** — title, heading, blank separator, note, or grouping row kept in
   import provenance but not made executable.
5. **NEEDS_MANUAL_MAPPING** — ambiguous duplicate, conversation dependency,
   placeholder, or semantics that cannot be inferred safely.

No row is discarded silently. Structural rows can be omitted from Questions
while their existence/type remains in the inspection/import report.

## Proposed import records

A LegacyImportBatch records:

- source filename and cryptographic checksum;
- source file metadata available without treating it as truth;
- imported at/by;
- importer/mapping version;
- sheet inventory and row counts;
- warnings/errors; and
- immutable copy/reference policy chosen at implementation time.

Each source row/cell mapping records sheet name, one-based worksheet row, source
cell coordinates for meaningful values, raw values, formulas versus displayed
values where relevant, classification, created/linked domain IDs, and mapping
warnings. This supports traceability without requiring provenance as ordinary
Question metadata.

A LegacyObservation linked to a QuestionVersion may retain:

- observed answer;
- expectation/guidance text;
- legacy acceptability value and mapped legacy human assessment when
  unambiguous;
- comments;
- timing/token observations and units as found;
- answer-size/experiment setting exactly as found;
- any source timestamp, target, build, or binding only when actually present;
- explicit unknown/missing identity markers; and
- sheet/row provenance.

LegacyObservation is not automatically an EvaluationRun/Execution. If required
target, build, timestamp, binding, and run grouping are absent, fabricating them
would make comparison misleading. Legacy data remains visible as imported
history and is excluded from controlled baselines/metrics by default.

## Field mapping principles

### Question text

The source Question value becomes the initial QuestionVersion's exact Unicode
template after only non-destructive technical decoding. Preserve a raw source
cell value alongside it. Do not silently correct spelling, punctuation,
Portuguese accents, placeholders, or wording during import.

Any intentional correction creates a later QuestionVersion with appropriate
change classification/reason.

### Stable Question identity

Generate a StewardBench stable ID according to an implementation-time ID policy;
do not derive permanent identity solely from row number or mutable question
text. Preserve a source alias such as workbook checksum + sheet + row for
traceability.

Rows across sheets are not automatically the same Question because text matches,
nor automatically different because wording differs. Deduplication is a review
decision.

### QuestionVersion

Initial exact question text, variable declarations confirmed during mapping,
and narrowly applicable guidance map to QuestionVersion. Set `valid_from` to the
controlled import/activation time unless a trustworthy source effective date
exists. Do not infer historical validity dates from row order or file timestamps.
`valid_to` is `NULL` for the imported current version unless deliberately
superseded.

Imported creation does not need a change classification; later relevant changes
use the controlled values.

### Domain, tags, rationale

Map a domain only from an identifiable controlled source column or explicit
manual mapping. Domain is required before activation, not necessarily during
raw staging. Do not infer it from sheet name without a reviewed mapping rule.

Use lightweight tags for source-independent cross-cutting traits confirmed by
content, such as `Portuguese`, `conversation`, `RCA`, `control`, or `canary`.
Source-sheet membership belongs in provenance and may optionally be a temporary
import tag only if the product owner finds it useful; it should not become the
domain taxonomy. Map rationale only from a clearly corresponding field/manual
decision.

### Observed Answer

`known questions` and `random question` populate `Answer` for every data row.
Many values summarize presentation, such as `Table with several entries`,
rather than proving that the cell contains the exact raw product response.
Preserve the exact cell value as a legacy observed-answer value/description and
do not claim stronger evidence fidelity than the workbook establishes. It is
not a current answer and does not replace execution against a target.

`knowledge base - rag questions` has no `Answer` field. Its singular `Comment`
column describes what appeared in the answer, but must not be silently promoted
to an exact observed response.

### Expected Answer

`Expected Answer` occurs only in `known questions` (38 of 39 rows) and `random
question` (10 of 13 rows). Preserve exact text and identify it as
`LEGACY_EXPECTATION` or evaluation guidance. The cells mix terse output-shape
descriptions, historical/dynamic claims, desired behavior, and critique of an
observed answer. The workbook supplies no scope, freshness, or authority field.
It is not automatically:

- universal ground truth;
- a deterministic evaluator rule;
- a baseline answer;
- an assertion that the live network should still match; or
- a resolved binding.

Later question-by-question review may promote precise, stable expectations into
versioned evaluator configuration.

### Acceptable

Preserve the original value exactly. Observed values are:

- `known questions`: `Yes` (19), `No` (16), `NO` (1), `Partially` (1), and
  `Yes for now.` (1; the source cell also has trailing whitespace), with row 32
  blank;
- `random question`: `Yes` (3) and `No` (10); and
- `knowledge base - rag questions`: `Yes` (3) and misspelled `Partialy.` (1).

The workbook does not define this field, name a reviewer, or record a review
timestamp. At least some values are conditional or non-binary, and some
`known questions` rows combine `Yes` with comments that still describe an
incorrect or unresolved result. Consequently, even apparent affirmative and
negative values remain raw legacy assessments until a source owner/admin
approves a mapping rule. Do not automatically translate them to StewardBench
GOOD/BAD.

Create a canonical historical HumanReview only if source evidence supplies (or
an explicitly approved legacy-import rule can honestly represent) the reviewer
and review time required by that entity. Otherwise the assessment remains on
LegacyObservation with unknown original attribution; the importing admin is not
fabricated as the historical reviewer.

Because these are imported manual decisions, label their source and do not imply
the full controlled conditions of a StewardBench execution. Do not translate
acceptability into deterministic PASS/FAIL.

### Comments

`known questions` has `Comments` in 22 rows; `random question` has none.
`knowledge base - rag questions` populates both `Comment` and `Comments` in all
four rows, with singular `Comment` describing answer behavior and plural
`Comments` generally recording review or performance concerns. These apparent
roles are not formally defined. Preserve original text. If manual review ties a
value clearly to one legacy observation, map it as an imported append-only
observation comment; if it describes the question definition/expectation,
retain it as legacy guidance or an import note. Do not silently split, rewrite,
or infer a structured reason taxonomy.

### Timing and token information

Only `knowledge base - rag questions` has dedicated timing/token columns. Its
four `Token` numeric cells are 1668, 2467, 2616, and 3936. Its four `Total time`
numeric cells are 12.7, 14.8, 14.2, and 14.8. The workbook defines neither the
token category (input, output, total, or another measure) nor the time unit or
clock boundary. `Interface Issues` row 16 also mentions 5382 tokens and 16.6s
inside prose; those are not structured columns.

Preserve raw values exactly as found. Map to typed timing/token fields only
after confirming units and semantics. Imported token counts are secondary
metrics and do not imply a generic token benchmark model.

### Answer-size and other experiment settings

The four `knowledge base - rag questions` rows repeat the exact question
`Explain what OpsSteward is` with `Answer Size` values `Small`, `Normal`,
`Longer`, and `Research`. Retain these values as legacy observation context.
Do not build a generic experiment-parameter framework solely for this sheet. If
current corpus execution actually requires a non-question parameter, evaluate a
narrow versioned request context during implementation/product review.

## Per-sheet mapping

### `target questions`

- Treat the 186 nonblank column-A cells as primary canonical Question
  candidates pending row-level review. There is no header or explicit ID/domain.
- Treat the 15 internal blank separator rows as STRUCTURAL, not empty Questions;
  retain their row positions without assigning meaning to the unlabeled blocks.
- Keep rows 155 and 156 as NEEDS_MANUAL_MAPPING until a reviewer decides whether
  they are one split question or two source rows.
- Preserve source order for migration review but do not make order permanent
  question identity or priority.
- Identify placeholders and binding needs manually/programmatically; fixed
  canary/admin values are valid v1 mappings.
- Any adjacent follow-up wording that depends on earlier turns is flagged for
  conversation review rather than assumed standalone.

### `known questions`

For each of the 39 data rows, seed/link a Question and QuestionVersion from
`Question`. Preserve `Answer` as a LegacyObservation value/description,
`Expected Answer` as legacy guidance, `Acceptable` as an unmapped raw legacy
assessment pending an approved interpretation, and `Comments` with their
apparent scope. It becomes a historical HumanReview only under the attribution
rule above. Missing target/build/binding/time remains unknown.

This sheet most closely resembles StewardBench's review loop but must not define
the platform's architecture or turn its Expected Answer column into an oracle.

### `random question`

Import the 13 substantive questions as normal executable Questions. Preserve
paraphrase and multilingual wording exactly and use reviewed lightweight tags
such as `Portuguese` or `generalization` where helpful. Row 7 is the only
explicitly Portuguese question found: `Quantos transceivers no total estão em
uso?` Row 8 is a related English question but is not proven to be an exact
translation. v1 does not generate random questions automatically.

Paraphrases remain separate Questions unless a reviewer intentionally maps them
to a common stable capability model. Do not collapse them merely because their
intended meaning seems similar: their wording is part of what they evaluate.

### `knowledge base - rag questions`

The four data rows contain one exact repeated question with four different
answer-size settings. Identify one candidate executable question definition
without discarding any row. The settings, token counts, timing, acceptability,
and two comment fields may become four separate LegacyObservations linked to the
QuestionVersion when that link is approved. No exact answer is available in
this sheet.

Preserve experimental context exactly. Standard v1 execution remains a
question/answer workflow; do not generalize this sheet into arbitrary experiment
configuration before direct corpus/API evidence requires it.

### `Interface Issues`

Treat all 17 rows as an auxiliary issue log, not automatically as Question
definitions or controlled Executions. Descriptions mention evaluated questions,
UI behavior, authentication, knowledge-base uploads, product configuration, and
occasionally timing/token observations in prose. Preserve sheet/row provenance
if these notes are retained with the import batch. Create links to question or
legacy-observation records only through explicit review; quoted question text
inside a description is not itself a corpus row.

Issue row 2 supplies useful context for the duplicate `known questions` rows 32
and 33: it states that accumulated `Recent Questions` caused an apparent empty
answer until that cache was cleared. This is a source note about possible
session/context contamination, not proof of a StewardBench conversation
scenario or target/build identity.

## Blank rows, separators, formulas, and duplicates

- Wholly blank rows and visual separators do not become Questions. In `target
  questions`, preserve the exact 15 separator row positions listed in the
  inventory. Trailing formatted blank ranges in the KB/RAG and random sheets do
  not count as data rows.
- Section labels/headings are structural unless a real question field says
  otherwise; this workbook has no section-label cells in `target questions`.
- This workbook has no formulas or merged cells. A future source revision must
  still report both formula and calculated value where present.
- Exact duplicates are reported, not automatically merged.
- Same text with different expectation/history may link to one Question only
  after review.
- Paraphrases and translations are normally separate first-class questions
  because they test generalization/language behavior.
- Source row order is retained as provenance, not priority.

The inspected exact question-text repetitions are:

- `known questions` rows 24 and 25;
- `known questions` rows 32 and 33, whose other fields differ;
- `knowledge base - rag questions` rows 2–5, whose settings/metrics differ;
- `known questions` row 27 and `target questions` row 199; and
- `random question` row 4 and `target questions` row 188.

Candidate paraphrase families include `random question` rows 9, 11, and 12
(serial-number wording); `known questions` rows 10–19 (entity/time-window
variants); and the Rubin profile/desired-state questions in `target questions`
rows 184–192. These examples are not an exhaustive semantic deduplication and
must not be merged automatically.

## Conversations

The workbook has no scenario ID, conversation ID, turn-order, parent-question,
or session column. Several target rows use deictic language such as `this path`,
`this event`, `those EVCs`, `them`, and `that router`. Rows 193–202 are a
particularly strong adjacent follow-up candidate. The historical blueprint also
illustrates a six-turn Rubin conversation using questions represented at target
rows 187, 190, and 193–196, but it does not settle how every workbook row should
be grouped.

If an approved mapping identifies scenario and turn order, create/link one
Question of kind CONVERSATION, an exact QuestionVersion, a ConversationScenario,
and ordered ConversationTurns. Preserve all source rows.

If grouping depends on interpretation of pronouns, adjacency, blank rows, or
answer context, classify the rows NEEDS_MANUAL_MAPPING. Do not import dependent
follow-ups as unrelated standalone Questions and do not guess grouping/session
semantics.

## Variables and resolved bindings

The workbook has no variable declaration, placeholder syntax, resolver, or
binding-value columns. `target questions` embeds template-like prose tokens,
including `Interface X`, `NodeVirtualTopoPort X`, `L1Adjacency X`,
`InfrastructureSegment X`, `Cable X`, `BreakoutCable X`, `BreakoutCable leg X`,
`PatchPanelPort X`, `Transceiver X`, `Router X`, `Switch X`, `Device X`, `VRF X`,
`EVC X`, `Object X`, `Policy X`, `Service A`/`Service B`, `Site A`/`Site B`,
`Interface A`/`Interface B`, paths A/B, `PDU A`, and `T1`/`T2`. These lexical
patterns are candidates, not proof of a formal grammar or of equivalent
semantics across rows.

For each confirmed placeholder, manual mapping must specify:

- variable name and safe display type;
- whether the question template includes it literally;
- allowed v1 resolution mode (fixed/admin, optional dynamic, baseline frozen);
- initial fixed/control value if supplied; and
- whether source answers/expectations assume a historical value.

Do not infer concrete bindings from an Expected Answer. Do not replace source
placeholder text destructively. Controlled runs always store both binding values
and final submitted question.

## Import workflow

1. Open the preserved workbook read-only and verify its checksum against the
   inspected source identity.
2. Programmatically inventory sheets, dimensions, hidden content, merged cells,
   formulas, headers, types, and non-blank row counts without modifying it.
3. Produce a mapping report containing every source row classification,
   candidate duplicate, placeholder, ambiguity, and proposed domain/tag.
4. Have an admin review manual mappings, especially duplicates, Acceptable
   semantics, conversations, placeholders, and domains.
5. Import into a transactionally identifiable batch with idempotency based on
   source checksum + mapping version; never duplicate silently on rerun.
6. Validate counts and sample raw values against the workbook.
7. Keep imported Questions DRAFT until required domains, versions, bindings, and
   obvious mappings are reviewed; activate explicitly.
8. Display legacy observations separately from controlled StewardBench history.

The importer itself is future implementation work and is not part of this
documentation session.

## Import validation report

Before acceptance, report per sheet and total:

- physical and substantive row counts;
- structural/blank rows;
- candidate Questions created/linked;
- LegacyObservations created;
- duplicate/paraphrase groups;
- mapped/unmapped Acceptable values;
- rows with observed/expected answers, comments, timings, tokens, settings;
- placeholder/binding candidates;
- conversation candidates and unresolved groupings;
- missing required domain/manual decisions; and
- all skipped/error rows with reasons.

Reconcile generated records back to source sheet/row samples. No successful
import should have unreported dropped substantive rows.

## Remaining mapping decisions

Structural inspection is complete for this source version. Source-owner/admin
review must still decide or supply evidence for:

- `Acceptable` semantics, reviewer attribution, and review time;
- whether `Answer` cells are summaries or exact product output on each row;
- the meaning/unit and clock boundary of `Token` and `Total time`;
- whether target rows 155–156 form one question;
- explicit conversation membership and turn order;
- formal variable declarations and concrete binding/resolver policy;
- controlled domains and optional tags for target-sheet blocks;
- relationships, if any, between repeated/paraphrased/cross-sheet questions;
- treatment of `Interface Issues` beyond preserved auxiliary provenance; and
- historical target, build, execution time, and runtime context, which have no
  dedicated workbook fields.

These ambiguities are not reasons to invent a broader domain model or convert
legacy material into controlled StewardBench history.
