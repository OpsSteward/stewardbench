# Executable acceptance harness design

Status: Approved architecture and acceptance design for later implementation.
No harness or application implementation is supplied by this document.

Decision record: [ADR 0008](adr/0008-layered-executable-acceptance-harness.md)

## Purpose and acceptance posture

The executable acceptance harness will answer:

> Does this StewardBench build satisfy the documented product, data-integrity,
> worker, RBAC, comparison, review, adapter, import, and deployment contracts?

The harness is an independent source of repeatable evidence, not an alternative
implementation specification and not a claim that code inspection or one green
end-to-end test proves correctness. The
[QA/acceptance skill](../skills/stewardbench-qa/SKILL.md) defines its acceptance
posture. Repository authority defines truth. The
[development skill](../skills/stewardbench-development/SKILL.md) constrains how
application features and their development tests are built, but does not decide
acceptance outcomes.

Harness results use only PASS, FAIL, and BLOCKED:

- **PASS** means repeatable evidence establishes the mapped requirement.
- **FAIL** means observable StewardBench behavior violates repository authority
  after valid prerequisites have been established.
- **BLOCKED** means the required environment, data, dependency, authority, or
  trustworthy test mechanism is unavailable.

A harness, fixture, or environment failure is not automatically a StewardBench
FAIL. Every scenario declares prerequisites and a likely failure domain so a red
result starts diagnosis instead of assigning blame.

## Principles

### Small observable failure domains

Checks are grouped around one primary boundary. Authentication, target
transport, worker execution, comparison, persistence, UI rendering, and an LLM
judge are not all required to prove one rule. A high-value cross-system flow is
corroboration after narrower layers pass, not a substitute for them.

### Real PostgreSQL where semantics matter

All acceptance involving persistence uses a disposable supported PostgreSQL
instance. Transactions, constraints, JSONB, migrations, row locks,
SELECT FOR UPDATE SKIP LOCKED, claims, leases, and concurrency are exercised
against PostgreSQL. SQLite is prohibited. Mocks and in-memory substitutes do not
establish database or worker-concurrency semantics.

### Controlled external dependencies

Routine acceptance uses deterministic doubles for evaluated targets, semantic
comparators, evaluators, and judges. It does not require a live OpsSteward
deployment. Live OpsSteward checks form a separate, explicitly enabled layer and
cannot determine the result of the default offline suite.

### Evidence first

Each scenario defines observable expected evidence before implementation is
inspected. Evidence may include HTTP status and response content, persisted
rows and constraints, worker ownership state, independent fake-target request
records, safely rendered behavior, exported data, and operation-scoped logs.
The harness retains only the evidence needed to make the requirement and failure
domain understandable.

### Historical integrity

The harness aggressively compares before/after snapshots of terminal
Executions, completed Runs, bindings, build/target identity, responses, and
baseline membership. Retry, review, comment, invalidation, baseline promotion,
configuration revision, evaluation, and comparison must add new attributed
facts without rewriting captured history.

### Orthogonal conclusions

Harness assertions keep execution outcome, automated result, LLM-judge result,
human judgment, review state, validity, and change state separate. SUCCESS is
not GOOD, CHANGED is not regression, REVIEWED is not GOOD, evaluator failure is
not product failure, and INVALID is not deletion.

### Reproducible and disposable operation

Every run identifies its build, harness revision, database version, configuration
profile, fixture version, and scenario IDs. Tests create uniquely named data and
disposable resources. Parallel-safe cleanup never targets a shared developer or
production database.

## Harness architecture

The default deterministic path runs normal Django/application checks, distinct
web and worker processes when lifecycle evidence is required, real PostgreSQL,
and controlled external doubles. Optional live OpsSteward is outside that path.

~~~mermaid
flowchart TB
    Runner[pytest acceptance runner<br/>scenario and evidence coordinator]
    Browser[Selective Playwright browser]
    Client[Django request client<br/>or external HTTP client]
    Web[Django web process]
    Worker[Dedicated StewardBench worker process]
    DB[(Disposable PostgreSQL)]
    Target[Reusable fake target service]
    Double[Deterministic comparator,<br/>evaluator, and judge doubles]
    Artifacts[Structured results and<br/>scoped evidence artifacts]
    Live[Optional live OpsSteward<br/>explicit opt-in only]

    Runner --> Client
    Runner --> Browser
    Runner --> Worker
    Runner --> Target
    Runner --> Double
    Client --> Web
    Browser --> Web
    Web --> DB
    Worker --> DB
    Worker --> Target
    Worker --> Double
    Runner --> DB
    Runner --> Artifacts
    Browser --> Artifacts
    Target --> Artifacts
    Worker -. optional configured adapter .-> Live
~~~

The common runner is pytest with pytest-django. Tests use the narrowest
authoritative interface: pure functions for deterministic primitives,
application services and Django requests for use cases and RBAC, PostgreSQL
inspection for durable invariants, separate OS processes for crash/restart
semantics, Playwright for browser-only behavior, and Docker for deployable
composition.

## Layered responsibilities

### Layer A — Domain and service acceptance

This layer proves deterministic semantics without a browser or live target.
It covers QuestionVersion transitions, run-manifest creation, retry/rerun
creation, review versus human judgment, validity decisions, baseline semantics,
frozen bindings, comparison categorization, and metric exclusion rules.

Pure policies may use ordinary pytest. Any service that persists or transitions
state uses pytest-django against PostgreSQL. Application services are invoked
with explicit ADMIN and OPERATOR principals so authorization does not depend on
a view.

### Layer B — PostgreSQL invariant acceptance

This layer proves the resulting schema and state behavior, including exact
QuestionVersion references, relational/JSONB preservation, temporal and
uniqueness constraints, immutable-history support, baseline linkage, target and
build snapshots, migrations, claims, leases, and terminal-write races.

It uses real PostgreSQL and inspects rows before and after supported operations.
Direct invalid writes may be used only to demonstrate an intended database
constraint; they do not redefine service-level immutability as a requirement for
database triggers.

### Layer C — Worker lifecycle and concurrency acceptance

This layer runs the PostgreSQL-backed worker with the fake target and observes
both database state and target-side traffic. It covers:

- sequential and bounded-parallel runs;
- requested run and aggregate target concurrency limits;
- two workers competing for eligible work;
- claim uniqueness, current ownership, leases, heartbeat/reconciliation, and
  completion under the matching claim;
- restart before claim, after a demonstrably safe claim, during a remote call,
  after response, and near terminal persistence;
- stale claims and safe versus ambiguous recovery;
- timeouts, connection errors, malformed target responses, and partial runs;
- one execution error while siblings complete;
- process death after claim but before a remote call;
- interruption during a remote call and ambiguous target acceptance; and
- prohibition of silent duplicate submission or duplicate terminal evidence.

Synchronization barriers and fake-target control endpoints make states
observable. Sleep-only race tests are insufficient.

### Layer D — Target-adapter contract acceptance

Adapters are tested separately from orchestration against scripted target
behavior. The matrix includes success, authentication required/rejected,
timeout, refusal/unavailable, HTTP errors, malformed JSON, unexpected schema,
partial versus complete answers, full raw-response preservation, metadata
present/missing/malformed, conversation continuity, Unicode, and redaction.

Assertions cover the normalized envelope, exact answer and raw payload,
adapter/version identity, protocol status, correlation ID, evidence, timestamps,
and normalized error class. Transport correctness is independent of evaluated
answer quality: no adapter scenario synthesizes human GOOD/BAD.

### Layer E — Semantic comparator acceptance

A version-controlled static corpus contains immutable baseline/current inputs
and expected safety classifications:

- **Equivalent:** whitespace, punctuation, harmless formatting, equivalent
  wording, and reordered facts that preserve meaning and relationships.
- **Changed:** entity or relationship set changes, counts, conclusion, missing
  key facts, new unsupported claims, changed cannot-conclude behavior,
  malformed/incomplete content, and newly exposed internal code/details.
- **Uncertain:** deliberately ambiguous pairs for which equivalence cannot be
  established safely.

The deterministic comparator double returns scripted EQUIVALENT,
MATERIAL_CHANGE, UNCERTAIN, ERROR, timeout, and malformed responses. Every
record asserts comparator identity/version, exact input references, rationale or
error, change state, and review state. UNCERTAIN maps to REVIEW REQUIRED.
Comparator ERROR, outage, timeout, or malformed output never maps to UNCHANGED.

The same corpus can later calibrate a real LLM-backed comparator, but real-model
results are a separately reported calibration layer. This design does not
select a provider, model, prompt, threshold, or automatic correctness oracle.

### Layer F — LLM judge integration acceptance

Normal acceptance uses a deterministic fake judge and tests integration rather
than generic model intelligence. It verifies the structured context sent,
independent persistence, provider/model and judge identity/version, prompt
version, timestamps, parsed and safe raw output, malformed output, timeout and
outage handling, and append-only re-evaluation.

Human GOOD/BAD remains authoritative. A disagreement preserves both records;
judge failure creates a judge ERROR and never product BAD. A later optional
calibration suite may exercise a configured real judge and stored examples,
without becoming default offline acceptance.

### Layer G — Django request and RBAC acceptance

This layer proves server-side behavior with Django request tests and application
service checks. It covers anonymous denial; ADMIN and OPERATOR login; authenticated
GET access; direct OPERATOR mutation attempts; CSRF-sensitive requests; run
launch/retry/rerun; question/version, target, user, baseline, review, comment,
and validity management; and URL-addressable filtering.

UI button visibility is useful presentation evidence but never sufficient
authorization evidence. Every mutation is attempted directly as both roles,
including requests crafted without the product UI.

### Layer H — High-value browser acceptance

Playwright remains deliberately small. Its initial workflows are:

1. ADMIN logs in, selects one question, and launches a run.
2. ADMIN selects multiple questions and all matching a filter, confirms the
   resolved count, launches, leaves, returns, and observes durable progress.
3. ADMIN opens the review workstation, sees baseline/current answers together,
   records GOOD/BAD and a Unicode comment, then navigates to the next stable
   review-required item.
4. ADMIN promotes a completed run after seeing completeness, opens comparison,
   and follows an actionable dashboard counter to exactly filtered records.
5. OPERATOR logs in, reads evidence, sees no mutation affordance, and a paired
   request assertion confirms direct mutation is denied.
6. Unsafe target content is displayed as evidence without script execution.

Request tests carry the exhaustive authorization matrix. Browser tests prove
navigation, rendering, progressive enhancement/fallback behavior, and the few
cross-screen workflows whose risk cannot be established by direct requests.

### Layer I — Corpus import acceptance

Import acceptance uses the immutable
[v2 development troubleshooting workbook](reference/v2-dev-troubleshooting.xlsx)
and checks its SHA-256
559ad19500eae888c250c38d3c7213bdf38912d611cd0dbc4dfa2556fa6ec8ff
before and after every test session.

The harness inventories the exact five visible sheets, headers/dimensions,
formulas/merged/hidden content, substantive rows, structural rows, and exact raw
representative cells. It reconciles the documented 39 known-question rows,
4 KB/RAG rows, 17 interface-issue rows, 13 random-question rows, and 186
nonblank target-question cells, including the 15 target-sheet separators.

Assertions preserve Unicode, comments, raw Acceptable values, expected-answer
notes as legacy guidance rather than truth, source row/cell provenance,
duplicates, blanks, settings and unknown units. They ensure question definitions
are distinct from legacy manual observations, no missing identity is fabricated,
conversation grouping is not guessed, and all substantive rows are created,
linked, manually deferred, or reported with a reason. Rerunning the same source
checksum and mapping version must be idempotent and reconcile created, linked,
skipped, warning, and error counts.

### Layer J — Docker smoke acceptance

Docker smoke proves the deployable v1 topology: one application image with web
and worker roles, PostgreSQL, and an explicit one-shot migration step. In a
uniquely named disposable project it eventually verifies:

- containers start and PostgreSQL becomes ready;
- migrations apply and first-ADMIN bootstrap succeeds;
- web login works and the worker connects;
- an ADMIN launches a run against the deterministic fake target;
- terminal evidence survives browser/web restart;
- worker restart preserves terminal evidence and follows reconciliation rules;
- a PostgreSQL volume preserves data across clean composition shutdown/startup;
  and
- no broker, SPA service, SQLite, Kubernetes, or developer-workstation hidden
  dependency is required.

Docker smoke is corroborating deployment evidence. It does not replace focused
database, migration, worker, RBAC, comparison, or rendering acceptance.

### Layer K — Optional live OpsSteward integration

This layer is excluded unless all explicit live-test configuration is supplied.
It validates the real adapter's authentication, question submission, complete
response schema, runtime metadata, conversation/session API, and bounded timeout
behavior against a named target. It does not assume a stable answer except for
explicitly approved canary/frozen questions.

Safeguards require a positive opt-in flag, explicit target URL and classification,
runtime-injected credentials, an allow-listed small safe subset, conservative
concurrency and timeout, a displayed execution preview, and a unique test run
identity. A production classification requires an additional production-specific
opt-in. The layer never automatically runs the approximately 200-question corpus
and never defaults to dgx.amlight.net or any other live deployment.

## Reusable fake target service

The future fake target will be one reusable, minimal Python HTTP service rather
than separate mocks for worker, adapter, and Docker tests. The same behavior
contract will run in three forms:

- in the test process or as a child process for adapter-focused tests;
- as a separate local process for worker crash/restart and network-failure
  tests; and
- as a Docker service for composition smoke tests.

Its implementation library and packaging command are deliberately deferred
until dependency selection, but all forms consume the same scenario documents
and expose the same wire/control contract.

### Scripted behavior contract

Each scenario selects a sequence or per-request behavior using a synthetic
scenario ID. Supported behaviors include:

- immediate valid complete answer that echoes the immutable request ID and
  includes evidence and correlation metadata;
- authentication challenge, acceptance of one synthetic credential, and
  explicit rejection;
- delayed or barrier-blocked response;
- deadline-exceeding response;
- HTTP error;
- malformed JSON, wrong content type, unexpected schema, or incomplete answer;
- disconnect before request acceptance and disconnect after acceptance;
- accepted request with a deliberately ambiguous result and no usable response;
- unsafe HTML/script, internal-code-like text, very long bounded text, Markdown,
  JSON, and code blocks;
- fixed conversation creation, ordered session-bound turn responses, session
  invalidation, and close failure; and
- metadata endpoint present, absent, unauthorized, malformed, or delayed.

Tests configure behavior through a harness-only control interface before target
traffic begins. Control endpoints bind only to loopback or an isolated Docker
test network, require a per-run synthetic control token, and are never part of a
production target adapter.

### Independent duplicate-call instrumentation

Every outbound StewardBench attempt carries its immutable execution/request ID
where the selected adapter variant supports correlation. The fake target keeps
an independent append-only request journal with:

- journal sequence number and scenario/run ID;
- execution/request correlation ID;
- method/path and sanitized request fingerprint;
- accepted, response-started, response-completed, and disconnected timestamps;
- conversation/session ID and turn order where relevant;
- active-request count and observed maximum concurrency; and
- selected scripted disposition.

Harness endpoints can inspect journal entries, current in-flight calls, maximum
concurrency, and per-correlation request counts. Reset is allowed only before a
scenario and asserts that no request is active. The journal is the authority for
whether the target received a call; StewardBench logs alone are insufficient.

Acceptance proves that one intended Execution normally produces one target
submission, an ambiguous accepted call is not silently resubmitted during
reconciliation, and an explicit user retry creates a new Run, a new Execution
ID, and one deliberate new target request linked to the source.

## PostgreSQL worker-concurrency strategy

### Two-worker claim race

Seed N pending work items in one committed run, start two independent worker OS
processes behind a common release barrier, and let both claim until the run is
terminal. Assert N distinct request IDs in the fake-target journal, one terminal
Execution observation per planned item, no item completed by a non-current claim
token, and correct final progress. Inspect claim/lease rows and any ownership
history alongside the target journal.

### Target concurrency cap

Configure target maximum concurrency to 2, seed 10 barrier-blocked responses,
and run enough workers/dispatcher capacity to exceed the limit if enforcement is
wrong. The fake target independently reports its maximum simultaneous accepted
requests. Assert it never exceeds 2 across concurrent runs targeting the same
TargetRevision, then release responses and verify all items complete.

### Sequential mode

Seed several barrier-controlled delayed requests with dispatcher capacity above
one. Release each response only after observing it in the journal. Assert the
fake target never records more than one in flight and that stored actual mode
and concurrency are sequential/1.

### Worker death and ambiguous remote calls

Process-level control is mandatory for death/restart evidence:

1. **Before remote call:** stop a worker after committed claim but before the
   target is invoked. After lease/reconciliation, prove safe reclaim produces
   exactly one target journal entry.
2. **After target acceptance:** block after the fake target journals acceptance
   and terminate the worker before it persists a response. Reconciliation must
   record an explicit benchmark-infrastructure error without a second target
   request for that Execution.
3. **After response, near terminal write:** use a barrier around persistence,
   terminate or race completion, and prove one immutable terminal observation
   with no overwrite.

Thread-level tests are appropriate for pure dispatcher accounting and fast
lock/constraint probes. They are not sufficient for process death, broken
connections, OS signals, lease expiry, or restart. These scenarios use separate
worker processes, explicit barriers, bounded polling with diagnostic state, and
no timing-only correctness assertion.

## Migration acceptance strategy

Migration tests begin with the first schema and grow with history:

1. migrate a clean disposable PostgreSQL database from zero to the current leaf;
2. verify the migration graph, expected constraints, indexes, PostgreSQL types,
   and migration records;
3. retain representative upgrade fixtures keyed to meaningful prior migration
   states, not only serialized copies of the latest schema;
4. migrate each supported representative state forward with terminal history,
   unknown identities, Unicode, JSONB evidence, legacy imports, reviews,
   invalidity, and baselines already present;
5. compare exact preserved values and relationships before/after;
6. exercise intended constraints with documented valid and invalid records; and
7. verify corpus-import compatibility at the migration states where importer
   schema changes.

An empty latest-schema migration is necessary but never sufficient. Upgrade
fixtures are deliberately small and describe why each historical shape matters.
Invalid historical mutation is expected to fail where the schema owns the
constraint; where policy is service-enforced, the corresponding supported
operation must fail without changing the database. Rollback behavior is tested
only when a migration claims safe reversibility; forward-only implications are
reported explicitly.

## Immutability enforcement and evidence

Not every immutable field requires a database trigger. The harness classifies
the owning enforcement layer:

| Enforcement kind | Examples | Acceptance evidence |
| --- | --- | --- |
| Application/service enforced | terminal observation update rejection; completed-run reopening rejection; retry/rerun creates new history; append-only review/comment/validity/evaluation operations | Invoke every supported service and request path, compare complete before/after snapshots, and assert the old row is unchanged |
| Database constrained | foreign keys to exact versions/revisions; legal lifecycle values; unique memberships/claims/terminal records; current-version or other constraints chosen by schema design | Execute transactions against PostgreSQL and assert commit success/failure plus final rows |
| Historical policy, not absolute DB prohibition | no normal deletion UI; baseline name/membership and captured evidence treated as fixed; correction through appended events; target configuration changes create revisions | Exercise supported ADMIN operations and absence/rejection of mutation paths; inspect preserved history and attribution |

The canonical immutable snapshot includes submitted question, QuestionVersion,
resolved bindings, request/response/answer/evidence, outcome, timing, adapter,
target revision, target/build snapshots, source links, and baseline membership
where relevant. Review, comment, invalidation, baseline promotion/activation,
target revision creation, retry, and comparison tests serialize or independently
query this snapshot before action and compare it byte/value-for-value afterward.

## Metrics and export acceptance

A named mixed-state fixture supplies independently countable rows, for example
GOOD 10, BAD 2, INVALID 1, ERROR 1, and REVIEW REQUIRED 3, with deliberate
overlap across orthogonal dimensions. Expected sets are enumerated by stable
fixture IDs rather than copied from the production projection under test.

Service/query acceptance checks numeric dashboard and report projections,
denominators, filtered query sets, pagination, all-matching selection, human
transitions, and baseline comparison transitions. Request and one browser test
follow each actionable counter and compare the destination IDs with the expected
set. INVALID remains visible but is excluded only where documented
product-quality metrics require it. Chart pixels are not asserted when numeric
series and labels can be tested directly.

CSV acceptance verifies the selected filtered rows, stable columns, Unicode,
unknown markers, build identity, state dimensions, latency, and validity. JSON
Run export verifies exact questions/bindings, raw and display answers, raw
response, evidence, target/build identity, evaluator and judge results,
comparisons, reviews, comments, validity history, timing, and structured types
sufficient for later offline/LLM analysis.

Exports are searched for plaintext and recognizable encoded variants of canary
passwords, tokens, authorization values, secret query parameters, and cookies.
No password/token field or usable credential reference value is allowed. Export
scenarios are capability-gated until the optional v1 export milestone is
accepted; an unimplemented optional export is not mislabeled as a product
failure before that milestone.

## Unsafe-content rendering and authentication

The unsafe-output fixture includes script elements, event-handler attributes,
malformed HTML, Markdown-like text, nested JSON/code blocks, Unicode, and a very
long value within configured limits. Request tests inspect escaped/sanitized
HTML and raw-evidence access. Playwright installs execution canaries and verifies
no script, event handler, URL, or returned markup executes while the original
evidence remains reviewable.

Authentication acceptance covers first-ADMIN bootstrap, password hashing through
successful verification rather than plaintext inspection, successful and failed
login, inactive user denial, exact ADMIN/OPERATOR role assignment, self-elevation
denial, subsequent authorization after a role change, and ADMIN user management.
Framework staff/superuser/groups cannot create extra product roles. Synthetic
passwords are recognizable test values and must still be absent from evidence,
logs, responses, and exports.

## Fixture taxonomy

Fixtures are explicit builders plus small declarative data, not opaque database
dumps:

| Fixture | Purpose |
| --- | --- |
| minimal-domain | One product/environment/target revision, ADMIN, OPERATOR, and exact active QuestionVersion |
| reviewed-baseline | Completed immutable run with mixed GOOD/BAD/unreviewed observations and completeness |
| changed-answer | Comparable baseline/current pairs for transitions and attention |
| bad-baseline | BAD historical observation reproduced and changed independently |
| non-comparable-binding | Version, binding, concrete-question, validity, and usable-answer prerequisite failures |
| invalid-execution | Preserved evidence plus attributed validity history and metric exclusion |
| worker-concurrency | Pending work, policies, barriers, lease cases, and stable correlation IDs |
| conversation | Ordered turns, one session, turn errors, continuation, and complete retry |
| comparator-calibration | Static equivalent/material/uncertain answer pairs and expected safety outcomes |
| judge-integration | Structured inputs and scripted success/error/malformed judge outputs |
| corpus-import | Real workbook identity plus a very small synthetic edge workbook only for cases absent from the source |
| unsafe-output | Untrusted HTML/script/Markdown/JSON/Unicode/long content |
| metrics-mixed-state | Enumerated expected record sets and overlapping state dimensions |

Every builder validates its preconditions: exact initial state, expected row
counts, terminal versus mutable rows, role identities, target policy, and no
active fake-target request. Fixed timestamps and stable IDs are used where
ordering is under test; real clocks are used only for lifecycle behavior and
asserted within documented bounds.

## Repository organization

Normal tests remain conventional and near the application behavior. The
dedicated harness directory is reserved for reusable black-box assets and
orchestration:

~~~text
tests/
├── unit/
├── integration/
│   ├── db/
│   ├── migrations/
│   ├── worker/
│   ├── adapters/
│   └── import/
├── acceptance/
│   ├── services/
│   ├── rbac/
│   ├── comparison/
│   ├── metrics/
│   └── exports/
├── browser/
├── fixtures/
└── live/

harness/
├── README.md
├── fake_target/
├── scenarios/
└── orchestration/
~~~

Unit, Django, PostgreSQL, adapter, import, and service assertions belong under
tests. Fake external services, shared wire scenarios, process-control helpers,
and Docker/black-box orchestration belong under harness. Docker smoke tests may
live under tests/acceptance or tests/docker according to the future runner, but
production application composition is not duplicated inside unit-test fixtures.
No empty directories are created until their first executable asset exists.

## Black-box and internal evidence boundary

| Requirement | Primary evidence | Corroboration |
| --- | --- | --- |
| Authentication and RBAC | External/Django HTTP behavior for anonymous, ADMIN, and OPERATOR, including crafted mutation requests | Persisted state unchanged; service-policy check |
| Launch, progress, review, baseline, filters | HTTP/rendered behavior and high-value browser workflows | Exact PostgreSQL run/review/baseline rows |
| Target submission and duplicate detection | Independent fake-target request journal | Execution/request correlation and worker logs |
| Worker restart and Docker lifecycle | Separate process/container behavior | Claims, leases, Run/Execution state, target journal |
| Dashboard drill-down and exports | Rendered/API/downloaded output | Independently enumerated expected DB record IDs |
| Unsafe rendering | Browser non-execution plus encoded response | Exact preserved raw evidence in PostgreSQL |
| Exact QuestionVersion, bindings, snapshots | PostgreSQL rows and relationships | Service response/rendered detail |
| Immutability and append-only history | Before/after PostgreSQL snapshots through supported actions | HTTP/service rejection and scoped logs |
| Claims, leases, locks, invalid exclusion | PostgreSQL transactions/state and independent queries | Worker/process and projection behavior |

Everything is neither forced through a browser nor accepted solely through
direct model calls. The most authoritative observable boundary owns the primary
assertion.

## Harness self-validation and failure attribution

Before an application assertion runs, each scenario verifies its prerequisites:
database version/connectivity and migration state, unique fixture identity,
expected initial row counts, required actor roles, fake-target scenario and empty
journal, deterministic-double version, clock/process-control capability, and
workbook hash where relevant.

The fake target tests its own journal counters and scenario transitions. Fixture
builders assert their own initial conditions. Worker tests compare target-side
calls independently with database claims. Browser checks cross-check persisted
state for consequential mutations. Corpus tests hash the source before and
after. Process tests retain exit status and control-barrier evidence.

A failed prerequisite or untrustworthy assertion produces BLOCKED or an
acceptance-harness failure. The report classifies established defects as:

- StewardBench application/runtime;
- acceptance harness/test;
- fixture/data;
- database/migration;
- worker lifecycle/concurrency;
- target adapter;
- evaluated target/OpsSteward;
- evaluator/judge;
- semantic comparator; or
- environment/configuration/infrastructure.

If evidence implicates several domains, the report lists each and what remains
unknown. An independent narrower probe is required before converting a harness
failure into a StewardBench FAIL.

## Stable scenario identification

IDs use ACC-{DOMAIN}-{NNN}; IDs are never recycled for different requirements.
Test function names begin with the stable ID in lowercase form, while display
names retain the uppercase ID. Parameterized transport or browser cases append
a descriptive suffix without changing the parent scenario. Retired scenarios
remain documented as retired rather than being reused.

## Initial v1 acceptance catalog

The catalog contains 35 high-value scenarios. Each is requirement-mapped during
implementation; optional capabilities run only after their roadmap milestone is
in scope.

### Identity, authorization, lifecycle, and history

| ID | Requirement | Setup | Action | Expected observable evidence and PASS | Likely defect domains |
| --- | --- | --- | --- | --- | --- |
| ACC-AUTH-001 | First ADMIN bootstrap and password safety | Empty migrated DB; synthetic bootstrap inputs | Run bootstrap once, authenticate, then repeat bootstrap | One ADMIN with a verifiable secure hash; no plaintext in DB/output/log; login succeeds; unsafe duplicate bootstrap is rejected. PASS when role and secret evidence match. | application/runtime, database, harness, environment |
| ACC-AUTH-002 | Login and user state | ADMIN, OPERATOR, inactive user | Attempt valid, invalid-password, inactive, and logout/session-reuse flows | Correct redirects/status/session behavior; inactive and failed credentials denied; no secret echoed. PASS when all HTTP and unchanged-state assertions hold. | application/runtime, fixture, harness |
| ACC-RBAC-001 | OPERATOR is server-side read-only | Complete minimal object graph and all mutation URLs/services | Authenticate OPERATOR and issue direct mutations for runs, retry/rerun, questions, targets, users, review, comment, validity, and baselines | Every mutation denied by service and HTTP boundary; DB fingerprint unchanged; read GETs succeed. PASS is not based on hidden controls. | application/runtime, fixture, harness |
| ACC-RBAC-002 | ADMIN can perform authorized mutations; no extra roles | ADMIN plus users with Django flags/groups varied | Perform representative allowed mutations; try self-elevation as OPERATOR and unsupported role values | ADMIN changes are attributed; unsupported roles/self-elevation denied; staff/superuser/groups add no StewardBench capability. PASS when service and DB agree. | application/runtime, database, fixture |
| ACC-QVER-001 | Exact temporal QuestionVersion is retained | Question v1 active, queued/terminal history, then create v2 | Launch/complete with v1, version question, launch current run | Old run still references v1 and exact submitted text; new normal run uses v2; temporal rule holds. PASS when no historical adoption/overlap occurs. | application/runtime, database/migration |
| ACC-RUN-001 | Launch freezes one stable manifest and returns promptly | Filtered active/inactive questions across pages; one target revision | ADMIN selects one, many, then all matching and launches | Committed PENDING run contains exact eligible IDs, target revision, policy, actor, bindings strategy, and total independent of later edits/navigation. PASS when selected set equals independent query. | application/runtime, database, fixture |
| ACC-RETRY-001 | Retry/rerun create linked new history | Completed source run and terminal execution | Retry one; rerun selected/all | New Run and Execution IDs/source links exist; source run remains terminal and byte/value-identical; each deliberate attempt has a new target request ID. | application/runtime, database, worker, adapter |
| ACC-IMM-001 | Supported operations never rewrite terminal evidence | Terminal execution and completed run snapshot | Review, correct review, comment, invalidate/correct, promote/activate baseline, revise target, compare, and race terminal completion | Original observation/run fields remain identical; new attributed records/revisions append; stale completion cannot overwrite. PASS when complete before/after snapshot matches. | application/runtime, database, worker |
| ACC-BASE-001 | Baseline is immutable observed history and promotion is warning-based | Completed run with GOOD, BAD, unreviewed, ERROR, and INVALID members | Promote despite visible incompleteness; toggle active state | Membership/source/build/bindings fixed; completeness displayed; active history attributed; no member deleted or rewritten. PASS does not require all GOOD. | application/runtime, database, UI |
| ACC-BASE-002 | BAD baseline is not truth | Comparable BAD baseline answer; current equivalent then changed/current GOOD | Compare and review current answer | Equivalent reproduction is not synthesized GOOD; BAD to GOOD is shown only after current human GOOD and remains CHANGED where applicable. | application/runtime, comparator, fixture |
| ACC-COMP-001 | Controlled comparison freezes identity and exact inputs | Baseline with valid QV/bindings/concrete question and current controlled replay | Launch replay and compare | Manifest/current execution reuse exact version, binding values, and submitted question; comparator references exact pair. PASS when no current substitution occurs. | application/runtime, database, resolver, fixture |
| ACC-COMP-002 | Invalid comparison prerequisites yield NON_COMPARABLE | Separate cases for QV mismatch, binding missing/invalid, concrete-question mismatch, INVALID member, ERROR/TIMEOUT answer pair | Request comparison | Each item is NON_COMPARABLE with the exact cause; failure/validity remains separate; no replacement binding or semantic call occurs. | application/runtime, database, resolver, comparator |
| ACC-REVIEW-001 | Review state, human judgment, automation, and outcome stay orthogonal | SUCCESS and ERROR items with REQUIRED state plus evaluator/judge records | Record GOOD, BAD, correction, and error triage without judgment | REVIEWED pairs correctly with GOOD/BAD/absent; reviewer/time/history append; evaluator/judge unchanged; ERROR never becomes BAD. | application/runtime, database, UI |
| ACC-VALID-001 | INVALID preserves evidence and is excluded from normal quality metrics | Known mixed valid/invalid executions including baseline member | Invalidate then correct by new decision; query details, metrics, baseline | Evidence/history retained; current validity projected; invalid excluded from required denominators; baseline warning visible; old comparison unchanged. | application/runtime, database, metrics |

### Comparison, adapters, workers, and conversations

| ID | Requirement | Setup | Action | Expected observable evidence and PASS | Likely defect domains |
| --- | --- | --- | --- | --- | --- |
| ACC-SEM-001 | Harmless changes are equivalent | Static whitespace, punctuation, formatting, wording, and reorder pairs | Run exact then deterministic semantic pipeline | Exact-equal bypasses semantic call; known equivalent unequal pairs record EQUIVALENT and UNCHANGED with versioned inputs. | comparator, fixture, harness |
| ACC-SEM-002 | Material changes require attention | Static entity/count/conclusion/missing-fact/cannot-conclude/leakage pairs | Run comparison pipeline | Every expected material pair records MATERIAL_CHANGE, CHANGED, and REQUIRED without a quality judgment. | comparator, fixture, application/runtime |
| ACC-SEM-003 | Uncertainty/error cannot hide change | Ambiguous pairs; fake timeout, outage, malformed and ERROR results | Run comparison pipeline | UNCERTAIN or ERROR signal and REQUIRED persist; none is UNCHANGED; diagnostics are safe and comparator identity recorded. | comparator, application/runtime, harness |
| ACC-ADAPT-001 | Successful adapter capture is complete and raw-preserving | Fake target success, Unicode/evidence, then metadata present/missing | Submit exact question and fetch optional metadata | One target journal entry; exact question, full raw response/answer/evidence, status, correlation, adapter version and metadata source/unknown persist. | target adapter, fixture, database |
| ACC-ADAPT-002 | Target failures normalize without quality judgment | Script auth rejected, timeout, refusal, HTTP error, malformed JSON/schema, and incomplete response | Invoke adapter cases independently | Correct normalized error and Execution ERROR/TIMEOUT; no SUCCESS for incomplete 200; safe diagnostics; no human BAD. | target adapter, evaluated target, harness, environment |
| ACC-ADAPT-003 | Secrets are redacted before persistence | Canary secrets in credential, header, query, upstream body/error and nested payload | Exercise success/failure, inspect DB/log/UI/export | Exact and encoded/structured secret variants absent everywhere durable/user-visible; runtime request still authenticates as scripted. | target adapter, application/runtime, harness |
| ACC-WORKER-001 | Two workers claim each item once | N pending items, two worker processes, common release barrier | Release both workers and complete run | N unique target submissions and terminal observations; exclusive claim tokens; no lock held during blocked remote call; correct final run state. | worker, database, fake target, harness |
| ACC-WORKER-002 | Sequential and target-wide concurrency limits hold | Sequential delayed run; parallel 10-item runs; target cap 2 | Dispatch with excess worker capacity and barrier-controlled responses | Fake target max is 1 sequential and at most 2 across parallel runs; stored actual mode/limit/timing accurate. | worker, database, fake target, fixture |
| ACC-WORKER-003 | One item failure does not erase siblings | Mixed success, timeout, connection error, malformed response in one run | Execute to terminal state | Every item has its independent outcome/evidence; successes preserved; run becomes correct terminal aggregate; progress counts equal DB rows. | worker, adapter, database, fake target |
| ACC-WORKER-004 | Restart recovery does not silently duplicate ambiguous calls | Safe pre-call death, accepted-and-blocked call, and near-terminal-write barriers | Kill/restart worker at each controlled point | Safe item is reclaimed with one target call; accepted ambiguous item becomes explicit infrastructure ERROR with no resubmit; terminal race yields one immutable result. | worker, database, fake target, harness, environment |
| ACC-CONV-001 | Conversation uses one ordered session and retries from turn 1 | Multi-turn scenario with one BAD-quality answer, one recoverable turn error, and optional session-fatal variant | Execute, inspect transcript, retry complete conversation | One session/ordered journal; later turns attempted when protocol permits; fatal continuation gets explicit errors; retry has new run/attempt/session from turn 1; derived human result follows required turns. | adapter, worker, application/runtime, fake target |
| ACC-JUDGE-001 | Judge integration is independent and versioned | Deterministic success/disagreement/malformed/timeout/outage responses | Judge stored execution, add human review, rerun newer judge version | Expected structured context sent; model/judge/prompt versions and results append; errors remain judge errors; human judgment governs while disagreement remains. | evaluator/judge, application/runtime, fixture |

### Import, presentation, reporting, migration, and deployment

| ID | Requirement | Setup | Action | Expected observable evidence and PASS | Likely defect domains |
| --- | --- | --- | --- | --- | --- |
| ACC-IMPORT-001 | Real workbook imports non-destructively and reconciles | Verified immutable workbook and approved mapping-version fixture | Inspect/import twice and generate reconciliation report | Hash unchanged; exact sheets/counts/raw representative Unicode/comments/provenance retained; ambiguities remain manual; expectations/Acceptable not promoted to truth; second run idempotent; no substantive row unreported. | importer/application, fixture/mapping, database, harness |
| ACC-UNSAFE-001 | Untrusted target output never executes | Unsafe-output response and comment fixture | Open list, review detail, raw evidence and export in browser/request client | Script/event canaries untouched; HTML safely escaped/sanitized; malformed/long/JSON content remains reviewable; exact raw evidence preserved. | application/runtime, UI/template, browser harness |
| ACC-METRIC-001 | Counts, denominators, filters and drill-down represent exact sets | Enumerated fixture: GOOD 10, BAD 2, INVALID 1, ERROR 1, REQUIRED 3 plus transitions | Query projections, render dashboard, follow counters | Numeric counts and denominators match independent IDs; invalid exclusion is correct; each actionable link returns exactly its set across pagination/filter combinations. | application/runtime, database/query, fixture, UI |
| ACC-EXPORT-001 | CSV and JSON preserve evidence and omit secrets | Unicode reviewed run with build identity, raw evidence, comments, judge/evaluator, invalidity and canary secrets | Export filtered CSV and complete Run JSON | Correct rows/structure/types/unknown markers and raw data round-trip; all state dimensions retained; no usable secret/password/token. | application/runtime, serializer, fixture |
| ACC-PERF-001 | Versioned response performance is independent evidence | Deterministic integer latency values around every policy boundary plus GOOD/slow and BAD/fast quality fixtures | Apply policy directly; execute fake target; inspect Execution and dashboard populations | 999/1000 TARGET, 1001/2000 GOOD, 2001/5000 ACCEPTABLE, 5001/10000 SLOW, 10001 BAD; TIMEOUT is separate; no HumanReview rewrite. | application/runtime, database, fixture |
| ACC-PERF-002 | Controlled latency comparison preserves dimensions | Comparable baseline/current fixtures including +25%/+500ms, band-only degradation, improvement, and answer-stable regression | Create controlled comparison and inspect stored pair/export | Raw latency, percentage, policy bands and REGRESSED/IMPROVED evidence match the selected pair; exact/semantic/human dimensions remain separate. | application/runtime, database, fixture |
| ACC-EFF-001 | Target-reported token and runtime telemetry is safe evidence | Fake target success/missing/malformed telemetry, Unicode and secret canary metadata | Execute, inspect persisted row, render and export | Non-negative reported tokens and runtime context persist and export; unknown stays null; malformed optional telemetry does not discard answer; no secret/HTML execution. | adapter, database, UI, serializer |
| ACC-MIG-001 | Clean and representative upgrades preserve history and constraints | Empty DB plus populated prior-migration fixtures | Migrate forward, probe constraints, compare snapshots | Migration graph reaches leaf; schema/types/constraints expected; exact historical values/relations preserved; invalid constrained states fail; no identity fabricated. | database/migration, fixture, environment |
| ACC-DOCKER-001 | Deployable v1 composition completes one durable evaluation | Clean uniquely named Compose project, app image, fake target, PostgreSQL volume | Migrate, bootstrap/login, launch, restart web/worker, cycle composition, inspect result | Web/worker/db start; run completes once; data and terminal evidence survive restarts/volume cycle; clean shutdown/startup; no unapproved service dependency. | Docker/infrastructure, application/runtime, worker, database, harness |

## Execution tiers

| Tier | Contents | Normal use |
| --- | --- | --- |
| Tier 1 — Fast | Pure unit policies, normalization, fixture validation, deterministic comparison primitives | Frequent local implementation feedback |
| Tier 2 — PostgreSQL integration | Django services, schema/constraints, migrations, JSONB, requests/RBAC, claims and focused worker transactions | Persistence, service, request, migration, or worker changes; future repository CI |
| Tier 3 — Controlled acceptance | Web/worker/PostgreSQL with reusable fake target and deterministic evaluator/comparator/judge doubles | Product milestone acceptance and cross-boundary changes |
| Tier 4 — Browser and Docker | Selective Playwright workflows, process restarts, Docker composition and volume smoke | Milestone/release readiness and relevant UI/deployment changes |
| Tier 5 — Live target | Explicitly configured small OpsSteward adapter checks and optional real-model calibration | Manual integration checkpoint only; never ordinary offline acceptance |

No execution-time promises are set before implementation and measurement.
Scenario markers permit requirement-driven selection without implying that a
lower tier proves an unexecuted higher-tier contract.

## Evidence and reporting model

pytest remains the human runner. It may emit JUnit plus a small structured
machine-readable result; the harness will not build a reporting application.
For every scenario, the result records:

- StewardBench build/version and exact Git SHA;
- harness/test version and exact Git SHA;
- PostgreSQL server version and migration leaf;
- environment/profile, OS/container context, and relevant dependency versions;
- scenario ID, fixture/scenario version, start/end time, and unique correlation
  identity;
- PASS, FAIL, or BLOCKED;
- mapped authority/requirement;
- established failure domain or explicitly unknown attribution;
- concise primary and corroborating evidence;
- relevant HTTP/DB/target/process observations; and
- paths or identifiers for sanitized logs and artifacts.

Artifacts are scenario-scoped, bounded, sanitized, and referenced rather than
embedded wholesale. Screenshots/traces are retained for browser failure when
useful; fake-target journals and database snapshots use synthetic IDs and omit
credentials. The exact structured report schema remains an implementation
decision.

## Relationship to CI

Future repository CI may run StewardBench's own Tier 1 and Tier 2 tests and
selected higher tiers to verify the StewardBench software. That is ordinary
software-development validation.

It is distinct from the v2 product capability in which StewardBench is triggered
by OpsSteward CI/CD to evaluate a deployed OpsSteward build. This design neither
implements CI nor moves CI-triggered product evaluation or automatic release
gating into v1.

## Harness security

- Only clearly synthetic credentials, tokens, hosts, users, and data are stored
  in repository fixtures.
- Live credentials come only from runtime environment/secret injection and are
  never printed in command lines, pytest IDs, artifacts, journals, or reports.
- Redaction canaries resemble secrets sufficiently to test code paths but cannot
  authenticate to a real system.
- Fake control interfaces bind only to an isolated test boundary and use a
  per-run synthetic token.
- Logs default to safe metadata and bounded payload excerpts; secret-bearing
  upstream behavior is tested without retaining the secret.
- Docker and database resources use unique test names and refuse production-like
  targets/databases for destructive setup or cleanup.
- Optional live tests show target classification and planned count before
  execution, enforce allow-listed questions and conservative concurrency, and
  require explicit production opt-in.

## Implementation sequencing with product milestones

The harness grows alongside application milestones rather than arriving after
the product:

1. **Foundation and identity:** establish pytest/pytest-django, disposable
   PostgreSQL, fixture validation, structured scenario IDs, clean migration,
   authentication/RBAC, QuestionVersion, and immutable snapshot checks.
2. **First executable slice:** add the reusable fake target and adapter success/
   error contract as the first target and run services are implemented.
3. **Durable execution:** add worker claim, sequential execution, terminal
   persistence, partial-failure, two-worker race, lease/restart, ambiguity, and
   target-concurrency acceptance with real PostgreSQL and process control.
4. **Human baseline loop:** add review/judgment separation, comments, validity,
   metrics exclusion, baseline promotion, BAD-baseline, retry/rerun, and the
   first small browser flow.
5. **Controlled comparison:** add frozen binding/non-comparable cases, static
   comparator corpus, attention behavior, comparison drill-down, and dashboard
   set reconciliation.
6. **Independent evaluation:** add deterministic judge/evaluator doubles and
   versioned persistence when those optional mechanisms are introduced; later
   add separate real-model calibration.
7. **Conversation capability:** add session continuity, ordered failure and full
   retry scenarios only when the confirmed adapter wire contract supports it.
8. **Corpus migration:** add real-workbook hashing, inspection, provenance,
   reconciliation, idempotency, and representative record checks as importer
   mapping decisions are approved.
9. **Operational UI and exports:** complete selective Playwright review,
   unsafe-content, all-matching/filter, metric drill-down, and capability-gated
   export acceptance alongside those screens.
10. **Deployable v1:** add Docker startup, explicit migration/bootstrap, one
    controlled run, restart, durable volume, and shutdown/startup smoke.
11. **Optional integration:** add explicitly configured live OpsSteward checks
    only after exact v1/v2 wire contracts and safe canaries are available.

Each milestone first maps its repository requirements to scenario IDs, implements
the narrow product behavior and development tests, and then runs the independent
acceptance scenarios whose prerequisites now exist.

## Harness-specific open questions

These choices do not block the Django/PostgreSQL/worker application architecture:

1. Which cross-platform process-control primitive will provide deterministic
   worker crash barriers on Linux CI, macOS development, and Docker?
2. Which minimal Python HTTP library will implement the already-decided reusable
   fake-target contract, and how will its child-process/container entry point be
   packaged without duplicating behavior?
3. Which minimal Playwright browser matrix is required initially beyond one
   supported Chromium path?
4. Will Docker smoke be invoked directly through Compose commands or coordinated
   by pytest while retaining independently reproducible Compose steps?
5. Which small structured result format will accompany pytest/JUnit, and what
   artifact retention policy will future repository CI use?

These questions must not select the semantic-comparator model/provider, judge
provider, OpsSteward wire schema, run-cancellation behavior, or corpus mapping;
those remain in [Open questions](open-questions.md) under their existing product
or integration authority.
