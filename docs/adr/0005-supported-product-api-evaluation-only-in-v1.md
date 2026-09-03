# ADR 0005: Supported product API evaluation only in v1

- Status: Accepted
- Date: 2026-09-03

## Context

OpsSteward's web UI consumes a question API. Browser automation would test
frontend behavior outside StewardBench's primary purpose and add a fragile
execution surface. OpsSteward v2 may later offer MCP, but v1 does not have a
concrete MCP evaluation requirement.

## Decision

StewardBench v1 evaluates supported evaluated-product APIs through target
adapters. It does not automate browser/UI behavior. The initial OpsSteward
adapter handles question submission and, where supported, conversations, health,
complete-answer capture, evidence, errors/timeouts, and optional runtime
metadata.

MCP is deferred. If implemented later, it is another interaction adapter for the
same Product identity and may measure tool correctness separately from
conversational/API answer quality.

## Consequences

- OpsSteward frontend correctness remains in OpsSteward's UI tests.
- v1 avoids browser drivers, screenshot evidence, and UI-specific question
  coupling.
- New products may use other supported API adapters without changing canonical
  questions.
- MCP evaluation requires a later contract and roadmap decision; no MCP fields
  or services are built speculatively.

See [Target adapter contract](../target-adapter-contract.md) and
[Roadmap](../roadmap.md).
