# Question corpus and import specification

Status: StewardBench workbook mapping v1 approved and implemented for M2.

## Source availability

The source [v2 development troubleshooting workbook](reference/v2-dev-troubleshooting.xlsx)
is preserved in the repository. It was inspected without write-back on
2026-09-03 and imported through M2 without modifying, normalizing, transforming,
or resaving the source workbook.

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

## Approved mapping v1

The repository-controlled interpretation fixture is
`import_mappings/v2_dev_troubleshooting_v1.json`. It is explicitly approved as
**StewardBench workbook mapping v1**, has mapping version `1`, and is bound to
the source SHA-256 above. A future interpretation change requires a new mapping
version rather than an in-place historical rewrite.

The target-question source workbook uses blank structural separators without
textual labels. StewardBench workbook mapping v1 therefore supplies the Domain
taxonomy as an explicit product-owner semantic mapping over the 16 ordered
source blocks. These names are `PRODUCT_OWNER_MAPPING` provenance; they are not
source-cell metadata.

| Source rows | Controlled Domain | Code |
| --- | --- | --- |
| 2–6 | Service Traversal | `TRAV` |
| 8–17 | L0 Topology | `L0` |
| 19–25 | L1 Topology | `L1` |
| 27–36 | L2 Topology | `L2` |
| 38–48 | L3 Topology | `L3` |
| 50–63 | Vera Rubin / Rubin LHN | `RUBIN` |
| 65–76 | Disjointness | `DISJ` |
| 78–87 | Capacity and Resource Sharing | `CAP` |
| 89–104 | Blast Radius | `BLAST` |
| 106–115 | Power | `POWER` |
| 117–129 | Temporal / Historical Reasoning | `TEMP` |
| 131–141 | Root-Cause Analysis | `RCA` |
| 143–156 | Provenance and Validation | `PROV` |
| 158–166 | Documentation / RAG / MOPs | `DOC` |
| 168–182 | Visualization | `VIZ` |
| 184–202 | Service Profiles and Conversational Follow-ups | `PROFILE` |

Target stable IDs use `<CODE>-NNN`, numbered in source order within each block.
Rows 155–156 are approved as one `PROV-013` Question with canonical text
`Which validation findings affect this device, interface, adjacency, service,
or infrastructure segment?`; both source rows retain provenance. Rows 193–202
remain standalone `PROFILE` Questions and receive one
`CONVERSATION_GROUPING_DEFERRED` warning; M2 creates no conversation objects.

The random sheet maps to Domain `Generalization`, code `GEN`, IDs
`GEN-001`–`GEN-013`, and deterministic tag `generalization`. Its paraphrases and
Portuguese text remain distinct and exact. The four exact repeated KB/RAG rows
map to one `KB-001` Question in `Knowledge Base / RAG` and four distinct legacy
observations. `Interface Issues` is intentionally ignored as issue-tracking
material and is reported, but no Question, observation, or issue record is
created from it.

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
| `known questions` | `Question`, `Answer`, `Expected Answer`, `Acceptable`, `Comments` | 39 data rows, worksheet rows 2–40 | No blank/separator data rows | Unlinked legacy observations unless a separately approved deterministic canonical link exists |
| `knowledge base - rag questions` | `Question`, `Answer Size`, `Comment`, `Token`, `Total time`, `Acceptable`, `Comments` | 4 data rows, worksheet rows 2–5 | Rows 6–57 and cells H:AD are formatted but blank | One repeated Question plus four legacy experiment records; not a generic parameter model |
| `Interface Issues` | `Issue`, `Description` | 17 issue rows, worksheet rows 2–18 | No blank/separator data rows | Auxiliary source issue log, not automatically question corpus data |
| `random question` | `Question`, `Answer`, `Expected Answer`, `Acceptable`, `Comments` | 13 data rows, worksheet rows 2–14 | Rows 15–27 are formatted but blank | Canonical generalization/multilingual Questions plus legacy observations |
| `target questions` | No header; populated values occur only in unnamed column A | 186 nonblank cells, worksheet rows 2–202 | Row 1 is unused; 15 internal blank rows visually separate 16 unlabeled blocks | Primary canonical Questions under the approved mapping v1 taxonomy |

All five worksheets are visible. Inspection found no hidden rows or columns,
merged cells, formulas, or formula-error cells. The internal blank rows in
`target questions` are 7, 18, 26, 37, 49, 64, 77, 88, 105, 116, 130, 142, 157,
167, and 183. The workbook cells do not prove or contain a taxonomy; the 16
Domain labels above are the separately recorded product-owner mapping decision.

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
service,` and `or infrastructure segment?`. Mapping v1 resolves them as one
accidentally split Question while preserving both raw cells and row identities.

## Import classification

Every non-blank candidate source row receives one of these migration roles after
inspection:

1. **QUESTION_DEFINITION** — creates or links a stable Question and its initial
   QuestionVersion.
2. **LEGACY_OBSERVATION** — preserves an observed answer/evidence/timing/
   acceptability record without pretending it is a fully controlled run.
3. **QUESTION_AND_OBSERVATION** — supplies both a definition and historical
   evidence, as used by `random question` and the approved KB/RAG mapping.
4. **STRUCTURAL** — title, heading, blank separator, note, or grouping row kept in
   import provenance but not made executable.
5. **NEEDS_MANUAL_MAPPING** — represented in M2 by a structured warning for an
   ambiguous duplicate, conversation dependency, placeholder, or semantics that
   cannot be inferred safely; the underlying row is still preserved under one
   of the roles above.

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

Mapping v1 assigns target IDs as `<DOMAIN-CODE>-NNN` in approved block order,
generalization IDs as `GEN-NNN`, and the repeated KB question as `KB-001`.
These become StewardBench identities and do not derive solely from raw row
number or mutable question text. Workbook checksum + sheet + row remains
separate provenance.

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
manual mapping. Mapping v1 uses the approved product-owner taxonomy above for
the 16 target blocks, `Generalization` for random questions, and `Knowledge Base
/ RAG` for the shared KB question. Domain is required before activation. Do not
infer another taxonomy from sheet names or question text.

Mapping v1 creates only the deterministic `generalization` tag. Source-sheet
membership and conversation candidates belong in provenance/warnings and do
not become speculative tags. Map rationale only from a clearly corresponding
field/manual decision; mapping v1 imports no rationale.

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
question` (10 of 13 rows). Mapping v1 preserves exact text only as
`LEGACY_EXPECTATION` on LegacyObservation; it does not populate QuestionVersion
guidance. The cells mix terse output-shape
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
incorrect or unresolved result. Mapping v1 now supplies the approved narrow
rule: exact `Yes` maps to legacy `GOOD`; exact `No` and `NO` map to legacy
`BAD`. Blank, `Partially`, `Partialy.`, and `Yes for now. ` remain unknown.
Every original cell value is retained. These values are legacy evidence only;
they do not create PASS/FAIL or future live HumanReviews.

No canonical historical HumanReview is created because the source supplies no
reviewer or review time. The assessment remains on LegacyObservation with
`IMPORTED_LEGACY` source and unknown original attribution; the importing admin
is not fabricated as the historical reviewer.

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

- Map the 186 nonblank column-A cells to 185 canonical Questions under the
  approved 16-block taxonomy. There is no workbook header, explicit ID, or
  Domain cell; IDs and Domains come from mapping v1.
- Treat the 15 internal blank separator rows as STRUCTURAL, not empty Questions;
  retain their row positions and report that the Domain labels are
  product-owner-supplied rather than blank-cell values.
- Merge rows 155 and 156 into `PROV-013`, preserving both row/cell records.
- Preserve source order in provenance. Numbering within the approved blocks
  establishes stable v1 IDs; later workbook row movement does not rename them.
- Warn on approved lexical placeholder candidates but create no inferred
  BindingDefinitions.
- Import rows 193–202 as standalone `PROFILE` Questions and record
  `CONVERSATION_GROUPING_DEFERRED`; create no conversation grouping in M2.

### `known questions`

For each of the 39 data rows, create an unlinked LegacyObservation. Preserve
`Question` as source question text, `Answer` as a value/description, `Expected
Answer` as legacy guidance, raw and narrowly normalized `Acceptable`, and
`Comments` with their apparent scope. Mapping v1 does not create Questions from
this sheet or guess cross-sheet canonical links. Missing
target/build/binding/time/reviewer identity remains explicitly unknown.

This sheet most closely resembles StewardBench's review loop but must not define
the platform's architecture or turn its Expected Answer column into an oracle.

### `random question`

Import the 13 substantive questions as DRAFT canonical Questions in
`Generalization`, with IDs `GEN-001`–`GEN-013` and tag `generalization`.
Preserve paraphrase and multilingual wording exactly. Row 7 is the only
explicitly Portuguese question found: `Quantos transceivers no total estão em
uso?` Row 8 is a related English question but is not proven to be an exact
translation. v1 does not generate random questions automatically.

Paraphrases remain separate Questions unless a reviewer intentionally maps them
to a common stable capability model. Do not collapse them merely because their
intended meaning seems similar: their wording is part of what they evaluate.

### `knowledge base - rag questions`

The four data rows contain one exact repeated question with four different
answer-size settings. Mapping v1 creates one DRAFT `KB-001` Question and four
LegacyObservations linked to its initial QuestionVersion. The settings, token
counts, timing, acceptability, and two comment fields remain distinct. No exact
answer is available in this sheet.

Preserve experimental context exactly. Standard v1 execution remains a
question/answer workflow; do not generalize this sheet into arbitrary experiment
configuration before direct corpus/API evidence requires it.

### `Interface Issues`

Mapping v1 intentionally excludes all 17 rows as an auxiliary issue log. They
are counted with the ignored reason in the reconciliation report and workbook
inventory, but create no Question, LegacyObservation, issue, or source-row
record. Quoted question text inside a description is not itself a corpus row.

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

Mapping v1 intentionally keeps rows 193–202 as standalone canonical Questions
and records `CONVERSATION_GROUPING_DEFERRED` for the whole range. It does not
assert membership, order, parentage, or session semantics. M8 may add scenario
membership without changing these M2 stable Question identities.

M8 adds the repository-controlled
[`conversation-scenarios-v1` mapping](../import_mappings/conversation_scenarios_v1.json).
It maps the one conversation explicitly illustrated by the retained blueprint:
`RUBIN-CONV-01` uses source rows 187, 190, and 193–196 in that exact order
(`PROFILE-004`, `PROFILE-007`, and `PROFILE-010`–`PROFILE-013`). The mapping
retains each source row and canonical Question ID. Rows 197–202 remain explicitly
unresolved: neither the workbook nor the blueprint settles whether they extend
that session, begin another scenario, or stay standalone. They require a
product-owner grouping/turn-order decision and are not silently included.

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

1. Open the preserved workbook without write-back and verify its checksum
   against the inspected source identity.
2. Programmatically inventory sheets, dimensions, hidden content, merged cells,
   formulas, headers, types, and non-blank row counts without modifying it.
3. Produce a mapping report containing every source row classification,
   candidate duplicate, placeholder, ambiguity, and proposed domain/tag.
4. Load the approved, repository-controlled mapping v1 decisions; unresolved
   duplicates, conversations, and placeholders remain warnings.
5. Import into a transactionally identifiable batch with idempotency based on
   source checksum + mapping version; never duplicate silently on rerun.
6. Validate counts and sample raw values against the workbook.
7. Keep imported Questions DRAFT until an ADMIN reviews and explicitly activates
   them; import never implies activation.
8. Display legacy observations separately from controlled StewardBench history.

The implemented management command defaults to a non-mutating reconciliation:

```bash
python manage.py import_stewardbench_workbook --dry-run
```

An apply requires an existing ADMIN username and is transactional:

```bash
python manage.py import_stewardbench_workbook --apply --actor admin
```

`--path`, `--mapping`, and `--json` support explicit source/configuration paths
and machine-readable evidence. Apply fails on a source hash/structure mismatch
or conflicting manually managed Domain/Question and never partially overwrites
the catalog. An unchanged source hash + mapping identity/version reuses the one
immutable LegacyImportBatch and is a reported no-op.

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

## Mapping v1 reconciliation

The approved workbook deterministically reconciles to 344 physical rows: 259
meaningful rows, four header rows, and 81 blank/separator rows. Of the meaningful
rows, all 17 `Interface Issues` rows are reported as intentionally ignored. M2
persists 257 source-row records (242 imported substantive rows plus 15 target
separators) and 489 mapped source-cell records.

| Domain | Source rows | Meaningful cells | Merge | Questions | ID range |
| --- | --- | ---: | ---: | ---: | --- |
| Service Traversal | 2–6 | 5 | 0 | 5 | `TRAV-001`…`TRAV-005` |
| L0 Topology | 8–17 | 10 | 0 | 10 | `L0-001`…`L0-010` |
| L1 Topology | 19–25 | 7 | 0 | 7 | `L1-001`…`L1-007` |
| L2 Topology | 27–36 | 10 | 0 | 10 | `L2-001`…`L2-010` |
| L3 Topology | 38–48 | 11 | 0 | 11 | `L3-001`…`L3-011` |
| Vera Rubin / Rubin LHN | 50–63 | 14 | 0 | 14 | `RUBIN-001`…`RUBIN-014` |
| Disjointness | 65–76 | 12 | 0 | 12 | `DISJ-001`…`DISJ-012` |
| Capacity and Resource Sharing | 78–87 | 10 | 0 | 10 | `CAP-001`…`CAP-010` |
| Blast Radius | 89–104 | 16 | 0 | 16 | `BLAST-001`…`BLAST-016` |
| Power | 106–115 | 10 | 0 | 10 | `POWER-001`…`POWER-010` |
| Temporal / Historical Reasoning | 117–129 | 13 | 0 | 13 | `TEMP-001`…`TEMP-013` |
| Root-Cause Analysis | 131–141 | 11 | 0 | 11 | `RCA-001`…`RCA-011` |
| Provenance and Validation | 143–156 | 14 | 1 | 13 | `PROV-001`…`PROV-013` |
| Documentation / RAG / MOPs | 158–166 | 9 | 0 | 9 | `DOC-001`…`DOC-009` |
| Visualization | 168–182 | 15 | 0 | 15 | `VIZ-001`…`VIZ-015` |
| Service Profiles and Conversational Follow-ups | 184–202 | 19 | 0 | 19 | `PROFILE-001`…`PROFILE-019` |

The resulting imported catalog has 199 DRAFT Questions and initial
QuestionVersions: 185 target, 13 generalization, and one KB/RAG. It creates or
reuses 18 controlled Domains and one `generalization` Tag. It creates zero
BindingDefinitions and zero HistoricalFixtures. The 56 LegacyObservations are
39 known, 13 random, and four KB/RAG observations. Exact Yes/No normalization
produces 25 `GOOD`, 27 `BAD`, and four unknown legacy judgments.

Mapping v1 currently emits 62 deterministic warning records: 53 potential
binding reviews, four ambiguous canonical links, three sheet-level unknown
legacy-metadata notices, one deferred-conversation range, and one unsupported
KB token/time semantics notice.

## Remaining source limitations

No unresolved product-owner decision blocks M2. These source limitations remain
deliberately unknown or deferred rather than guessed:

- whether each `Answer` cell is exact raw output or a manual representation;
- reviewer attribution and review time;
- `Token` meaning and `Total time` unit/clock boundary;
- final M8 conversation membership and turn order;
- formal variable declarations and binding/resolver policy;
- semantic relationships between repeated/paraphrased/cross-sheet questions;
  and
- historical product, target, environment, build, execution time, bindings, and
  session identity.

These limitations do not justify a broader domain model or conversion of legacy
material into controlled StewardBench execution history.
