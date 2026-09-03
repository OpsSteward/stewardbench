# Historical and reference material

This directory preserves the original design/corpus inputs supplied for the
StewardBench foundation:

- [OpsSteward Evaluation Lab blueprint](OPSS_EVALUATION_LAB_BLUEPRINT.md) —
  historical architecture and evaluation direction;
- [v2 development troubleshooting workbook](v2-dev-troubleshooting.xlsx) —
  source question corpus, legacy observations, and interface-issue notes.

Both artifacts were inspected during the 2026-09-03 documentation
reconciliation. They remain source material: do not rewrite the blueprint to
make it agree with current decisions, and do not normalize or transform the
workbook in place. Workbook-derived facts and unresolved interpretations are in
[Question corpus import](../question-corpus-import.md).

## Authority

Current accepted ADRs and the authoritative StewardBench product, domain,
architecture, evaluation, and UI specifications take precedence. The roadmap
then controls v1/v2/v3+ release boundaries. These original artifacts explain
design provenance and provide corpus data, but do not silently override later
decisions.

## Blueprint reconciliation

StewardBench retains the blueprint's independent evaluation-repository
boundary, enduring implementation-independent question corpus, external
supported-API focus, immutable/versioned longitudinal evidence, conversation
sessions, and separation of deterministic, semantic/LLM, and human evaluation.

The authoritative StewardBench specifications deliberately change or simplify
the blueprint in several ways:

- a human-reviewed baseline is the primary v1 accepted reference;
- comprehensive authoritative-source answer oracles are deferred;
- dynamic resolvers are optional, while fixed and baseline-frozen bindings are
  sufficient for v1;
- external-event correlation and infrastructure snapshots are deferred;
- historical regrading is enabled by retained evidence but has no v1 UI;
- the user CLI is deferred to v3+;
- CI-triggered evaluation and Kubernetes are deferred to v2; and
- MCP is a future target interaction adapter, not a v1 requirement or separate
  product identity.

These are explicit scope decisions intended to deliver the operational review
loop quickly, not accidental omissions.

The blueprint's suggested repository tree and milestone ordering are proposals,
not implementation commitments. In particular, they do not authorize
application scaffolding or framework selection during this foundation phase.
