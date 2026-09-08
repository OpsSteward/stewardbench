# Target adapter contract

Status: Authoritative v1 boundary. OpsSteward v1.0.4 Production is
`LIVE_CERTIFIED` from retained real-target evidence; this document specifies
behavior, not code or a framework interface.

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

## Current OpsSteward certification status

Source inspection and live probes established the supported API shape.
Certification remains target-specific: a product-neutral fake target cannot
certify a real deployment. The real v1.0.4 Production target has now met the
evidence requirements below; v2 has a verified Development adapter contract but
is not `LIVE_CERTIFIED`.

| Target | Adapter / contract status | Authentication | Runtime metadata | Conversation |
| --- | --- | --- | --- | --- |
| OpsSteward v1.0.4 production | `LIVE_CERTIFIED`. Real session-cookie requests to the external `/api` prefix successfully captured `/api/chat` table and summary answers, observed `/api/version`, external latency, optional telemetry, and unknown telemetry without fabrication. | `opssteward_session` server-side session cookie | `GET /api/version`: product, version, source_sha, build_time | API accepts `conversation_id`, but source does not establish an M8-compatible open/reuse/close lifecycle; unsupported/not certified. |
| OpsSteward v2 development | CONTRACT_IMPLEMENTED_NOT_LIVE_CERTIFIED. A Development live probe verified `/api/chat`, `/api/version`, the supported chat envelope, and a structured table response. | `opssteward-2-0-session` server-side session cookie | `GET /api/version`: product, version, source_sha, build_time | Same normalized limitation; unsupported/not certified. |

For both generations, `POST /chat` (concretely `POST /api/chat` for the
certified v1 Production and verified v2 Development deployments) accepts a
`ChatRequest` whose required core field is `message`; StewardBench sends
`{conversation_id: null, message, mode: "auto", source: "auto"}`. Successful `ChatResponse` includes
`conversation_id`, `interaction_id`, `text`, `evidence`, and `metadata`.
401/403 map to authentication failure; other non-2xx responses remain adapter
errors; urllib deadline expiry maps to timeout. v1.0.4 optionally reports
`metadata.performance.ollama`; current source prefers
`metadata.performance.model_serving` (and retains an Ollama-compatible alias).
Those blocks can report prompt/completion/total tokens, model/provider, and
internal stage timing. They are target-reported diagnostics, never a substitute
for StewardBench external latency.

Authentication is explicit per adapter generation: `opss-v1-chat` sends the
`opssteward_session` cookie, while `opss-v2-chat` sends
`opssteward-2-0-session`. Both use the same runtime-only symbolic credential
reference mechanism; neither credential values nor cookie headers are retained
in request evidence.

### Certified structured operator answer

The certified v1 live table response had `answer_type: "text"`, heading text,
`response_kind: "table"`, and a `response_payload` object containing ordered
`columns` and ordered `rows`. This payload is semantically part of the operator
answer; the heading alone is not a complete observation. A separate certified
v1 response had `response_kind: "summary"` with generated text, citations, and
knowledge-base metadata. StewardBench supports plain text, `table`, and
`summary` operator-facing responses: a summary renders its escaped human-readable
`text` without assuming a payload schema, while its complete payload remains
immutable structured evidence rather than being collapsed to text.

The adapter preserves the redacted raw response unchanged and also stores a
versioned immutable `operator_answer` object in Execution response metadata:

```json
{
  "schema_version": "opss-structured-answer-v1",
  "answer_type": "text",
  "text": "Device inventory for production network devices:",
  "response_kind": "table",
  "response_payload": {"columns": ["..."], "rows": [["..."]]}
}
```

The observed rectangular table is rendered through StewardBench-owned table
markup with all target strings escaped. A supported `summary` renders its
escaped text alone in the primary answer; its variable-shaped payload remains
available through collapsed raw evidence. Neither is treated as target-supplied
HTML. Exact comparison canonically includes every stored structured value;
semantic comparison, evaluators, and the LLM judge receive the same complete
data-only representation. Unknown future `response_kind` values and malformed
table shapes remain preserved evidence and are displayed as escaped JSON rather
than silently dropped or guessed into markup. Plain-text responses without
structured fields retain their prior text behavior.

### Explicit normalized telemetry mapping

StewardBench does not recursively scrape target responses. Its source-derived
mapping is deliberately narrow and optional:

| OpsSteward source field | StewardBench execution evidence | Notes |
| --- | --- | --- |
| v1 `metadata.performance.ollama.prompt_tokens` | `input_tokens` | Target-reported; absent/malformed remains unknown. |
| v1 `metadata.performance.ollama.completion_tokens` | `output_tokens` | Target-reported; never estimated. |
| v1 `metadata.performance.ollama.total_tokens` | `total_tokens` | Preserved only as OpsSteward defines it. |
| v1 `metadata.performance.ollama.provider`, `.model` | `runtime_telemetry.provider_or_runtime`, `.model` | Context, not correctness authority. |
| v2 `metadata.performance.model_serving.prompt_tokens`, `.completion_tokens`, `.total_tokens` | `input_tokens`, `output_tokens`, `total_tokens` | Current v2 model-serving metrics; the documented Ollama alias remains accepted where supplied. |
| v2 `metadata.performance.model_serving.providers[0]`, `.models[0]` | `runtime_telemetry.provider_or_runtime`, `.model` | Only the target's explicitly reported primary values are mapped. |
| Numeric top-level values in `metadata.performance` or explicit internal-timing block | `internal_timing_metadata` | Target diagnostics; distinct from externally observed latency. Valid nested `ollama` and `model_serving` envelopes are mapped as telemetry, not mislabeled as malformed scalar timings. |

`Execution.latency_ms` / exported `observed_latency_ms` is measured by
StewardBench around the complete adapter request. It includes network and
target response processing, excludes worker queue wait and runtime metadata
discovery, and is the sole source for the versioned performance band.

When approved evidence is supplied, document the concrete facts separately for
v1 and v2 and implement one versioned adapter per materially different contract.
Do not infer a route or build identity from the UI, GitHub, a health endpoint,
or the other product version.

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

## Supported OpsSteward runtime metadata

The source-derived read-only version route is `GET /version` relative to an
adapter endpoint. The certified Production endpoint is therefore
`GET /api/version`. A successful response provides the following currently
supported shape (fields other than `product` may be absent):

```json
{
  "product": "OpsSteward",
  "version": "2.0.0-dev",
  "source_sha": "0123456789abcdef",
  "build_time": "2026-09-03T00:00:00Z"
}
```

Contract requirements:

- `product` is required if the endpoint responds successfully;
- `version`, `source_sha`, and `build_time` are nullable/optional;
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

1. An OpsSteward v1 target with an unavailable version endpoint still
   executes questions; version/SHA may remain unknown or admin-declared.
2. The native OpsSteward `/chat` API does not establish M8-compatible session
   lifecycle behavior merely by accepting `conversation_id`; this adapter
   correctly refuses to advertise conversation support.
3. A 401/403 produces AUTHENTICATION_FAILED without persisting credentials and
   without a human BAD result.
4. A 200 response lacking the documented answer is MALFORMED_RESPONSE rather
   than an empty successful answer.
5. A timeout preserves timestamps and safe diagnostics and is prominent in
   comparison with a formerly successful baseline execution.
6. A new adapter version changes parsing without changing the canonical question
   and without rewriting old executions.
