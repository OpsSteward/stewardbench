# Target adapter contract

Status: Authoritative v1 boundary; wire-level OpsSteward contracts remain an
open integration question. This document specifies behavior, not code or a
framework interface.

## Purpose

A target adapter isolates evaluated-product API details from StewardBench's
execution engine. The same canonical QuestionVersion can therefore be executed
against different compatible products or different API versions without
embedding product routes, payloads, session rules, or error shapes into the
question.

The initial implementation will need an OpsSteward adapter supporting the v1
and v2 question APIs. Compatibility may be supplied by one adapter with
negotiated variants or separately versioned adapters after the actual wire
contracts are confirmed. Either shape must satisfy this normalized contract and
remain behind the selected Django application's adapter boundary.

## Responsibilities

The adapter must be able to:

1. perform a bounded connectivity/health check;
2. submit an exact concrete question and retrieve the complete answer;
3. preserve the raw response before normalization;
4. return answer and evidence/provenance in a normalized envelope;
5. create/reuse/close or abandon a conversation/session identity where the
   target supports it;
6. retrieve optional runtime build metadata when supported;
7. enforce/carry request timeout and cancellation signals available from the
   coordinator;
8. classify failures without losing safe diagnostics; and
9. expose adapter identity/version and technical capabilities.

The adapter must not:

- decide whether an answer is GOOD/BAD or semantically equivalent;
- query GitHub for deployed identity;
- query Neo4j, Nautobot, Kytos, Kafka, or similar systems as answer oracles;
- encode domain-capability flags such as `supports_bgp` or `supports_rubin`;
- persist usable credentials in requests, evidence, logs, or errors; or
- implement MCP in v1.

## Technical capability declaration

Each configured TargetRevision declares adapter interaction capabilities rather
than claimed product knowledge:

| Capability | Meaning |
| --- | --- |
| QUESTION_API | A single concrete question can be submitted and a complete answer returned. Required for normal v1 execution. |
| CONVERSATION_SESSION | Multiple ordered turns can share a target conversation/session identity. Required only for conversation scenarios. |
| RUNTIME_METADATA | The running target can report optional deployed-build identity. |
| HEALTH_CHECK | A distinct bounded health/connectivity operation is available; otherwise connectivity may be inferred cautiously. |

Capability mismatch is a benchmark-infrastructure/configuration problem, not a
product answer FAIL. For example, selecting a conversation scenario for a target
without `CONVERSATION_SESSION` should be rejected before launch or recorded as
unsupported infrastructure behavior—not attributed as a bad OpsSteward answer.

## Normalized operations

The names below are conceptual; no programming-language signature is selected.

### Describe adapter

Input: none beyond adapter configuration.

Output: adapter name/version, supported technical capabilities, supported
configuration schema/version, and diagnostic display name.

This lets a TargetRevision record exactly which integration behavior it expects.

### Health check

Input:

- effective endpoint/configuration;
- externally resolved credential handle; and
- timeout/deadline.

Output:

- status such as REACHABLE, UNREACHABLE, AUTHENTICATION_FAILED, DEGRADED, or
  UNKNOWN;
- observed time and latency;
- sanitized details; and
- optionally the raw non-secret diagnostic response.

Health is generally advisory at launch. It never substitutes for per-execution
outcomes.

### Submit question

Input:

- immutable execution/request ID for correlation;
- exact concrete Unicode question after binding resolution;
- non-secret request context explicitly supported by the adapter;
- deadline/question timeout; and
- effective target configuration plus runtime-only credential handle.

Output envelope on successful capture:

- adapter name/version;
- request started/completed timestamps (or enough data for StewardBench to
  record them consistently);
- protocol/HTTP status where meaningful;
- raw target response bytes decoded/preserved according to an explicit content
  type and safe size policy;
- exact extracted answer;
- structured or textual evidence/provenance returned by the product;
- target request/correlation ID if non-secret;
- optional response metadata; and
- warnings about partial/unknown fields.

The execution engine, not the adapter, derives the display/normalized answer and
runs evaluators. A nominal HTTP 200 with malformed or incomplete payload is a
MALFORMED_RESPONSE adapter error, not SUCCESS.

The exact OpsSteward endpoint, request keys, complete-answer indicator or polling
behavior, and response extraction paths require inspection of the real v1/v2
contracts. The adapter must wait for the product's complete response within the
deadline; it must not record a streaming fragment as the final answer.

### Conversation/session operations

Conceptual behavior:

1. open or establish a conversation session and return a non-secret session ID;
2. submit every turn in declared order using that ID;
3. capture each turn through the same normalized response/error envelope; and
4. close the session if supported, treating close failure as adapter diagnostics
   rather than rewriting turn observations.

One ConversationAttempt owns one session identity. A failed turn is recorded
and the adapter still attempts later turns when the protocol permits. It must
not silently open a fresh session mid-scenario. If the target invalidates the
session and continuing is impossible, remaining turn attempts receive explicit
session/infrastructure errors.

Retry creates a new run, new ConversationAttempt, and new session beginning with
turn 1.

### Retrieve runtime metadata

Input: effective target configuration, runtime credential handle, deadline.

Output: a timestamped, source-marked metadata envelope with known fields and
optional raw non-secret payload.

Failure or absence is non-fatal. StewardBench uses admin-declared fallback and
retains unknown values rather than fabricating identity.

## Error contract

The adapter maps product/protocol behavior into a small normalized error
classification while retaining sanitized diagnostic details:

| Error | Meaning |
| --- | --- |
| AUTHENTICATION_FAILED | The target rejected supplied runtime credentials. |
| CONNECTION_FAILED | DNS, routing, refusal, TLS, or similar connectivity failure. |
| TARGET_TIMEOUT | The complete target answer was not obtained before the deadline. |
| MALFORMED_RESPONSE | A response arrived but could not satisfy the documented answer envelope. |
| UNSUPPORTED_BEHAVIOR | The configured API variant/capability cannot perform the requested operation. |
| SESSION_FAILED | Conversation session could not be established or consistently used. |
| ADAPTER_ERROR | Unexpected adapter defect; preserve safe diagnostic class/detail. |

The coordinator represents `TARGET_TIMEOUT` as Execution TIMEOUT and other
terminal adapter failures as Execution ERROR with the normalized class.
Authentication failure is not human BAD: a valid product answer was not
observed. Dashboards and comparisons still prioritize these failures.

Diagnostics may include status codes, safe target correlation IDs, response
content type, and redacted payload excerpts needed to troubleshoot malformed
responses. They must exclude authorization headers, passwords, tokens, secret
query parameters, session cookies, and deployment-secret values. Redaction
occurs before persistence or user-visible logging.

## Idempotency and correlation

Evaluation questions are expected to be read-only, but the target API may not
provide idempotency. The adapter should pass StewardBench's execution/request ID
as a correlation or idempotency field when supported. It must disclose whether
the target honors it.

If worker failure makes completion ambiguous, StewardBench records an
infrastructure error rather than silently assuming that resubmission is the same
attempt. User-visible retry always creates a new run and execution.

## API-version compatibility

Canonical QuestionVersions contain operator language and binding definitions,
not OpsSteward API-version fields. A TargetRevision selects an adapter identity
and configuration schema compatible with its deployment. Adapter versioning may
handle differences in:

- route and authentication behavior;
- request/response envelope;
- synchronous, streaming, or completion-polling mechanics;
- evidence field shapes;
- conversation/session lifecycle; and
- metadata availability.

Every Execution retains adapter identity/version. Upgrading target adapter
configuration creates a new TargetRevision. Historical responses remain bound
to the prior revision and are never reparsed destructively; later derived
normalizations/evaluations are appended with their versions if needed.

## Proposed optional OpsSteward runtime metadata contract

OpsSteward may later expose a small read-only endpoint. The route is deliberately
unselected pending product API review. A conceptual successful JSON payload is:

```json
{
  "schema_version": "1",
  "product": "OpsSteward",
  "product_version": "2.0.0-dev",
  "git_sha": "0123456789abcdef",
  "build_id": "build-2026-09-03.1",
  "image_sha": "sha256:optional"
}
```

Contract requirements:

- `schema_version` enables additive evolution;
- `product` is required if the endpoint responds successfully;
- `product_version`, `git_sha`, `build_id`, and `image_sha` are nullable/optional;
- unknown additional fields are tolerated and may be preserved as safe raw
  metadata;
- missing fields are not empty-string substitutes for known values;
- response values are informational identity, not credentials;
- a short bounded request is sufficient; and
- older releases with no endpoint, authorization failure, malformed payload, or
  endpoint outage do not block question execution.

StewardBench records each value's source as RUNTIME_DISCOVERED or
ADMIN_DECLARED, plus observation time. Runtime-discovered identity normally wins
for the run snapshot when it conflicts with the launch-time fallback, while the
conflict remains visible and both source observations are preserved. Historical
discovered metadata is immutable; corrections use comments/annotations.

The endpoint should report deployed identity directly. StewardBench does not
call GitHub to reconstruct it.

## Acceptance examples for later implementation

1. An OpsSteward v1 target with no metadata endpoint still executes questions;
   version/SHA may remain unknown or admin-declared.
2. An OpsSteward v2 target opens one session, attempts all conversation turns in
   order after a turn-level error, and retains the full transcript.
3. A 401/403 produces AUTHENTICATION_FAILED without persisting credentials and
   without a human BAD result.
4. A 200 response lacking the documented answer is MALFORMED_RESPONSE rather
   than an empty successful answer.
5. A timeout preserves timestamps and safe diagnostics and is prominent in
   comparison with a formerly successful baseline execution.
6. A new adapter version changes parsing without changing the canonical question
   and without rewriting old executions.
