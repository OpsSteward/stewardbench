# Development and deployment

This page documents the v1.0.0 Docker deployment and operational workflow.
Real OpsSteward wire-contract certification is recorded separately for each
configured target and must never be inferred from deterministic fake-target
acceptance.

## Runtime and configuration

The supported application runtime is Python 3.12 through 3.13 and Django
5.2.17. The application database engine is always Django's PostgreSQL backend,
using psycopg 3.3.5. There is no SQLite settings path.

Copy `.env.example` to `.env` for Docker development and replace every
`replace-with-...` value. Required runtime settings are:

- `DJANGO_SECRET_KEY`;
- `POSTGRES_DB`;
- `POSTGRES_USER`; and
- `POSTGRES_PASSWORD`.

`STEWARD_BENCH_APPLICATION_VERSION` identifies the deployed application in the
ADMIN operational-status page and JSON exports. The v1 release value is
`1.0.0`; Compose supplies that default, while immutable image/build identity
should also be retained by the deployment platform.

`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, secure-cookie behavior,
TLS redirect behavior, database connection settings, the host web port, worker
poll interval, and log level are optional environment configuration. Keep
`DJANGO_DEBUG=false` and secure cookies enabled on a DGX or other non-local
deployment. Terminate TLS at the deployment proxy and configure trusted origins
for the deployed HTTPS origin. Never put `.env` into an image or commit it.

Compose uses the deployment `.env` both to interpolate the documented fixed
configuration and, for `web` and `worker` only, as an application `env_file`.
The latter is required because Compose interpolation alone does not inject an
arbitrary symbolic target credential into a container. Consequently every
`STEWARD_BENCH_TARGET_CREDENTIAL_<NORMALIZED_REFERENCE>` in the external
deployment file is available at runtime to both application roles without a
product-specific Compose entry. The `db` service does not load this file and
therefore does not receive target credentials.

The ordinary deployment command uses the project `.env` automatically. When a
deployment instead uses `docker compose --env-file /secure/path/.env`, pass the
same non-secret path for the application env file as well:

```bash
STEWARD_BENCH_APP_ENV_FILE=/secure/path/.env \
  docker compose --env-file /secure/path/.env up -d web worker
```

`STEWARD_BENCH_APP_ENV_FILE` selects the file only; it is not a credential.
Keep that file external to the repository and do not render its contents with
`docker compose config` in logs or support tickets.

## Docker topology

`compose.yaml` defines three long-running services:

- `web`: Gunicorn serving the Django application;
- `worker`: the same image running `python manage.py run_worker`; and
- `db`: PostgreSQL 17.11 with the named `postgres_data` volume.

The worker performs M4 durable execution and M8 ordered conversation turns. A browser request creates the
complete Run/Execution manifest in PostgreSQL and returns; worker processes
later claim eligible Executions. It never holds a database transaction across a
target call. Both application services wait for PostgreSQL health.
Migrations remain an explicit one-shot operation and never run implicitly in
web or worker startup.

### DGX production deployment and upgrade

Keep `.env` or equivalent secret injection outside the repository. Set a long
random `DJANGO_SECRET_KEY`, explicit `POSTGRES_DB`, `POSTGRES_USER`, and
`POSTGRES_PASSWORD`, `DJANGO_DEBUG=false`, deployment-specific
`DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`, secure cookies, and the
desired `STEWARD_WEB_PORT`. Configure target session values only as
`STEWARD_BENCH_TARGET_CREDENTIAL_<REFERENCE>` runtime secrets matching symbolic
TargetRevision references. No default ADMIN password exists.

For a first install, build the pinned checkout, start `db`, explicitly run
`python manage.py migrate --noinput` through the `web` image, bootstrap the
first ADMIN with the password environment mechanism below, then start `web` and
`worker`. Confirm `/health/live/`, authenticated `/health/ready/`, and the ADMIN
operational-status page before configuring targets.

Before an upgrade, back up the PostgreSQL database and the external deployment
configuration/secret mechanism. Deploy the new application image, run the
explicit migration command once, restart web and worker, and verify readiness
and worker state. PostgreSQL data—not a container filesystem—is authoritative;
the named volume requires host-level backup/restore planning. Mapping files and
the workbook are repository-controlled and need no separate mutable backup.

### PostgreSQL backup

Before a deployment that could affect the persistent database, create a
custom-format dump on protected host storage. The command obtains database
credentials only inside the database container and does not print them:

```bash
umask 077
docker compose exec -T db sh -lc \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > /protected-backups/stewardbench-$(date -u +%Y%m%dT%H%M%SZ).dump
```

Record the dump path, SHA-256, and deployment/release identity with the
operational change. Test restoration only against an isolated PostgreSQL
database; do not drop or overwrite the active `postgres_data` volume as part of
normal release work.

TLS termination, firewalling, and reverse-proxy policy remain deployment
responsibilities. Production must not run debug mode or example credentials,
and public registration is not available.

## Managed catalog

After signing in, all authenticated users can browse Products, Environments,
Targets and their configuration history, Questions and their version history,
Domains, Tags, and optional Historical Fixtures. ADMIN can use the product UI
to create and update stable catalog metadata, create target revisions, create
questions and new question versions, and activate or retire questions.
OPERATOR sees the same catalog evidence but every catalog mutation is denied at
the server and service boundaries.

Target endpoint, adapter, technical capability, classification, execution
policy, credential reference, or declared-build fallback changes are made with
**New revision**. Existing TargetRevision rows have no update/delete product
workflow. Likewise, evaluation-relevant question text, guidance, or binding
changes use **New version**; historical QuestionVersion and BindingDefinition
rows are immutable through supported workflows. PostgreSQL permits at most one
current (`valid_to IS NULL`) row per target/question, and service transitions
lock the stable parent and close/create the temporal pair atomically.

Credential references are symbolic deployment-secret names only. The target
endpoint form rejects user information, query parameters, and fragments, and
fixture fixed-parameter keys reject credential-shaped names. Never put usable
credentials into catalog records.

## M3 frozen evaluation

An ADMIN activates one or more single-turn Questions, selects them from
**Questions**, chooses one target, and creates a Run. `Select all matching` is
resolved at launch to all currently filtered eligible `ACTIVE`
single-turn Questions, never merely the current page and never future catalog
records. DRAFT, RETIRED, and conversation Questions are not M3 launch-eligible.
OPERATOR may browse Runs and Executions but cannot launch one through either the
UI or a direct POST.

At launch the application snapshots the target revision endpoint, adapter and
policy, declared build metadata, exact QuestionVersion ID/text, exact concrete
submitted question, resolved fixed bindings, and deterministic manifest order.
The worker uses those frozen rows rather than rereading a current QuestionVersion
or TargetRevision. A later catalog revision therefore cannot change a launched
Run.

M3 supports an optional non-secret fixed/admin value on a BindingDefinition.
It substitutes only the explicit `{{binding_name}}` marker. A required binding
without a fixed value, or a configured marker absent from the template, creates
an Execution `ERROR` with `BINDING_CONFIGURATION_ERROR` and sends no target
request. M3 deliberately has no dynamic resolver.

The reusable deterministic `fake-http` adapter remains the executable M3 test
contract. It sends `POST <endpoint>/question` with an immutable
request correlation UUID and accepts only a complete JSON envelope containing
`complete: true` and a string `answer`. Its optional `GET <endpoint>/metadata`
lookup is non-fatal: declared launch values and runtime-discovered metadata are
retained separately, with unknown/unavailable state shown explicitly.
OpsSteward v1.0.4 Production is separately live certified for the versioned
`opss-v1-chat` adapter at `/api/chat` and `/api/version`; v2 routes and session
lifecycle remain integration open items. No generic fake-target route or schema
is inferred for another product.

For a TargetRevision with a non-empty credential reference, the runtime worker
resolves it only from an environment variable named
`STEWARD_BENCH_TARGET_CREDENTIAL_<REFERENCE>`, where non-alphanumeric
characters in the symbolic reference become `_` and letters are uppercased.
For example, `secrets/m3-fake` resolves from
`STEWARD_BENCH_TARGET_CREDENTIAL_SECRETS_M3_FAKE`. The value is injected into
the outgoing Authorization header but is omitted/redacted before raw request,
response, metadata, diagnostic, and UI persistence. A missing value becomes an
explicit `AUTHENTICATION_FAILED` Execution error.

The standard-library fake service is reusable by adapter, worker, and later
Docker tests:

```bash
python -m harness.fake_target --port 18081 --control-token synthetic-control-token
```

It defaults to loopback. For a disposable isolated Docker test network only,
pass `--host 0.0.0.0` so the separately packaged worker can reach it; retain a
per-run synthetic control token and do not publish that port outside the test
network. The control token protects configuration/reset/journal endpoints. Its
append-only journal records request correlation, concrete submitted question,
request fingerprint, timestamps, mode, and observed concurrency independently
of StewardBench. It supports complete Unicode answers, delays/timeouts,
HTTP/auth errors, malformed/incomplete/wrong-content-type responses, unsafe
HTML, metadata available/unavailable/malformed modes, scripted per-request
dispositions, and test-only before-acceptance, after-acceptance, and
before-response barriers. The journal also exposes per-correlation counts and
observed concurrent requests so it independently detects duplicate submissions
and capacity violations.

## M4 durable worker

The launch form offers **Sequential** and **Parallel** mode. The frozen Run
stores the requested mode, the TargetRevision maximum, and the actual Run
maximum: sequential is always one; parallel is the lesser of the frozen target
maximum and `WORKER_MAX_CONCURRENCY` at launch. The Run detail shows all three
values. `WORKER_MAX_CONCURRENCY` defaults to `8`; it is a positive bounded
worker setting, not a user scheduling control.

Each active Execution has a generated worker identity, claim token, claim
attempt number, database-clock claim/lease/heartbeat timestamps, and a small
target-call phase. A short PostgreSQL transaction claims a `PENDING` row using
`SKIP LOCKED`, locks the exact TargetRevision only while admitting capacity, and
commits before any adapter I/O. Completion locks the row again and succeeds
only for the matching token. Terminal rows retain their final claim evidence and
are never claimed again.

The worker heartbeats long adapter calls. Capacity is count-derived from durable
unexpired claims, never from process memory: sequential Runs have at most one
active claim; parallel Runs have at most their frozen actual maximum; and all
active Runs using the same frozen TargetRevision share its frozen target
maximum. A newer TargetRevision does not silently change an old Run's policy or
share this v1 revision-scoped capacity bucket. Optional inter-question delay is
also persisted as the Run's next eligible dispatch time, so another worker
cannot bypass it.

Recovery is deliberately asymmetric. An expired `CLAIMED` row has not crossed
the durable submission boundary and returns to `PENDING` for one safe later
claim. An expired `SUBMISSION_STARTED` row, and a legacy interrupted M3 row,
becomes terminal `ERROR` with `AMBIGUOUS_INFRASTRUCTURE`; it is not resubmitted.
TIMEOUT, adapter errors, malformed responses, and one sibling's failure each
reach their own terminal observation while other planned work continues. No M4
path introduces general automatic remote retries.

`WORKER_LEASE_SECONDS` defaults to `30` and `WORKER_HEARTBEAT_SECONDS` defaults
to `10`; heartbeat must be smaller than the lease. PostgreSQL's clock is used
for lease decisions. `WORKER_POLL_SECONDS` remains a simple bounded polling
cadence.

## M5 human review and historical integrity

An ADMIN can review a terminal Execution as `GOOD` or `BAD` in the execution
workstation. A review appends an attributed `HumanReview`; correcting a prior
judgment appends a new linked review and makes that later review the current
projection. It never edits the captured request, response, answer, evidence,
timing, target/build snapshot, or execution outcome. `REQUIRED`, `REVIEWED`,
and `NONE` are a separately attributed review-workflow projection. An
`ERROR`/`TIMEOUT` may be triaged `REVIEWED` without inventing a human GOOD/BAD.

Run and Execution comments are append-only, authored, timestamped Unicode text.
The product UI and service layer have no edit/delete path; a correction is a
new comment. Known runtime credential values are rejected from comment text
before persistence.

Every Execution defaults to `VALID`. ADMIN may append an attributed `INVALID`
decision and, if needed, append a later `VALID` correction. The current
projection records invalidation actor/time while the complete decision history
remains visible. INVALID observations and their raw evidence stay available,
but GOOD/BAD and human-review quality metrics use only the displayed valid
population and show the invalid count separately.

`Retry` and `Rerun` always create new immutable history:

- **Retry one Execution** creates a new one-question Run and Execution linked
  to its source Run/Execution. It repeats the source's frozen QuestionVersion,
  concrete submitted question, resolved bindings, TargetRevision/snapshot, and
  execution policy with a new request correlation ID. The new Run takes a fresh
  runtime-metadata observation when its worker executes.
- **Rerun selected/all** creates a new Run linked to the completed source Run.
  It uses the selected (or all still eligible) source Questions but follows the
  normal current launch path, freezing current QuestionVersions, bindings, and
  target revision independently. It never copies old comments or reviews.

The workstation presents all four independent dimensions, review and validity
history, raw evidence, related attempts, append-only comments, and a stable
previous/next Run queue. OPERATOR may read all of this evidence but direct
mutation POSTs are rejected server-side.

The Product and Environment examples in the product definition are not loaded
automatically. Configure them explicitly through the ADMIN UI so initial data
is visible, reversible, and environment-appropriate. Catalog configuration
itself performs no target call; only the separate M4 worker performs a frozen
Run through its configured adapter.

## M6 baselines and exact controlled comparison

An ADMIN can create a named Baseline from a completed Run that has at least one
usable VALID SUCCESS observation. Promotion fixes the source Run and exact
Execution membership permanently; later retries, reruns, reviews, comments, or
validity decisions never rewrite or extend that member set. Baselines are
observed history, not answer keys: they can contain BAD, unreviewed, ERROR,
TIMEOUT, or later-invalidated observations. The promotion and Baseline detail
views show total, valid/invalid, reviewed/unreviewed, GOOD/BAD, and execution
outcome completeness without an approval gate or invented score.

Baselines can be ACTIVE or INACTIVE. Every designation change appends an
attributed state-history event, and deactivation never deletes the Baseline,
source Run, members, or prior Comparison records. If an existing member later
becomes INVALID, StewardBench retains the member and all comparison evidence,
then records durable ADMIN-attention context on the Baseline.

From an ACTIVE Baseline, an ADMIN launches a new controlled comparison Run
against a selected current target in the same Product/Environment context. The
new Run snapshots that target's current TargetRevision and build declaration at
launch, while every replay Execution reuses the historical exact
QuestionVersion, concrete submitted question, and resolved binding values. It
does not select a newer QuestionVersion or substitute a fresh binding. A
frozen input that cannot safely be replayed is persisted as NON_COMPARABLE and
is completed without a target submission.

M6 comparison uses `exact-v1`: line ending normalization plus trailing
horizontal-whitespace normalization only. For a versioned structured
operator-answer representation, that same shallow normalization applies to
each text value before deterministic JSON serialization, so every structured
value—including table columns, rows, cells, and summary payload fields—
participates in exact equality. Plain-text answers retain the original text-only
behavior. Equal normalized answers are UNCHANGED; unequal
answers are CHANGED and set the current Execution to
REQUIRED unless a later legitimate review already made it REVIEWED. Neither
state determines GOOD/BAD or regression. ERROR/TIMEOUT, invalidity, and human
GOOD/BAD transitions stay separate. In particular, an answer equal to a BAD
baseline remains current-unreviewed until a human explicitly reviews it.
Comparison records and their per-pair hashes/reasons are immutable. The
comparison list/detail and execution workstation expose M6 summary counters,
URL-addressable triage filters, NON_COMPARABLE reasons, and baseline/current
answers with their independent target/build, review, and validity context.

Structured operator answers are included in the JSON run export as a
machine-readable `observation.operator_answer` object (and retain their
immutable response-metadata copy). The primary UI supports plain text, safe
structured tables, and structured summaries whose text is shown without
flattening their variable payload. CSV remains the scalar operational view: it
keeps `raw_answer` and `display_answer` but intentionally does not flatten
arbitrary target tables or summaries into lossy cells. CSV formula protection
therefore continues to apply only to its documented scalar fields.

## M7 conservative semantic triage

M7 leaves the M6 `exact-v1` ComparisonItem immutable. Semantic triage runs only
for a VALID, successful controlled pair whose exact result is `CHANGED`; exact
`UNCHANGED`, `NON_COMPARABLE`, failure, and invalid evidence do not receive a
semantic verdict. A `SemanticComparisonResult` is a separate append-only record
with the baseline/current Execution IDs, exact QuestionVersion and frozen-input
hashes, provider/model/comparator/prompt identities, safe concise rationale or
failure detail, and timing. A newer re-evaluation points to the previous result;
the unsuperseded leaf is the current semantic projection, while all older
results remain visible.

The offline M7 comparator boundary is provider-neutral. The production default
is deliberately `unconfigured`, which persists an attributable `ERROR` and
keeps review required; it never guesses equivalence. The repository’s
deterministic scripted fake comparator supports `EQUIVALENT`,
`MATERIAL_CHANGE`, `UNCERTAIN`, and failure/malformed cases for PostgreSQL
acceptance. A live provider/model, credentials, prompt, data-transfer terms,
and calibration remain open product/security decisions and are not configured
or claimed here.

`EQUIVALENT` means only that the comparator established harmless difference for
triage. It may append a system review-tracking event that clears the M6
change-only `REQUIRED` projection to `NONE`; it does not change the immutable
exact `CHANGED` result, baseline answer, raw answer, validity, execution
outcome, or human GOOD/BAD. `MATERIAL_CHANGE`, `UNCERTAIN`, and `ERROR` retain
or create `REQUIRED`; an existing ADMIN `REVIEWED` projection is never replaced.
This keeps semantic/human disagreement visible—especially a semantically
equivalent response to a BAD baseline, which is never synthesized as GOOD.

Comparison and Execution detail show exact M6 evidence and semantic M7 triage
as separate labeled fields, with comparator identity/rationale, immutable
history, review state, human judgment, and side-by-side baseline/current
answers. Comparison counters and URL-addressable filters distinguish exact
results, semantic equivalent/material/uncertain/error/not-run states, failures,
and pending human review.

## M8 ordered conversation scenarios

An ADMIN manages a stable `ConversationScenario` and creates a new immutable
`ConversationScenarioVersion` whenever its exact ordered turns, required-turn
status, canonical QuestionVersion links, static bindings, or expected session
behavior changes. A ScenarioVersion owns ordered `ConversationTurn` records;
the stable scenario contains no mutable executable prompt text. OPERATOR may
browse scenario/version/run evidence but cannot create, version, launch,
review, or retry a scenario.

Launching an ACTIVE scenario requires a current target revision that declares
both the supported question API and `CONVERSATION_SESSION` capability. The
launch creates a normal durable EvaluationRun with sequential actual
concurrency, a `ConversationAttempt`, and one immutable Execution per turn.
The worker opens exactly one target session before Turn 1, persists its
non-secret identity and adapter-safe metadata, then submits later turns in
strict ordinal order using that same identity. Target output is always answer
data; it is never interpreted as StewardBench configuration or instructions.

Every turn retains the concrete submitted prompt, answer/raw evidence, latency,
target-session request evidence, outcome, and ordinary M5 review history. A
human BAD or semantic result does not affect worker control flow. A recoverable
turn error can retain the session and continue later turns. If the adapter says
continuity is unusable or unknown—including M4 stale submission ambiguity—the
attempt is marked unusable, dependent turns become explicit
`SESSION_CONTINUITY_BLOCKED` observations without target requests, and no new
session is silently created.

The transcript is shown in ordinal order on the Run detail alongside per-turn
review controls and prior context. The derived attempt result is `GOOD` only
when every required terminal turn is human GOOD; it is `BAD` if a required turn
is human BAD, `NOT_FULLY_REVIEWED` when required successful turns lack a human
judgment, and `EXECUTION_INCOMPLETE` while a required turn has error/timeout or
has not reached a terminal answer observation. Semantic `EQUIVALENT` never
supplies human GOOD.

Conversation retry is deliberately whole-attempt only: it creates a new
EvaluationRun, ConversationAttempt, correlation IDs, and a fresh target session
from Turn 1, while preserving the original transcript unchanged. Independent
retry/rerun of a dependent conversation turn is rejected. Controlled baseline
replay similarly starts fresh but reuses the baseline's exact ScenarioVersion,
turn identities/order, frozen prompts, and frozen bindings. M6 exact and M7
semantic comparison stay per-turn; conversation summary remains derived from
those corresponding turn observations rather than a new score.

`RUBIN-CONV-01` is the explicit repository-controlled source mapping for
PROFILE rows 187, 190, and 193–196. PROFILE rows 197–202 remain preserved as
standalone canonical Questions with deferred grouping; no relationship is
guessed. The deterministic fake target independently journals session IDs,
correlation IDs, prompts, ordinal order, request counts, recoverable errors,
and session loss. It is the routine M8 acceptance target. No real OpsSteward
conversation adapter is claimed until an authoritative wire contract exists.

## Reconciled source corpus

The repository-controlled `StewardBench workbook mapping v1` fixture is
`import_mappings/v2_dev_troubleshooting_v1.json`. The importer opens
`docs/reference/v2-dev-troubleshooting.xlsx` without saving it, verifies the
approved SHA-256, validates all five sheet structures, and produces a
reconciliation report. The default mode is non-mutating:

```bash
docker compose run --rm web python manage.py import_stewardbench_workbook --dry-run
```

Apply requires an existing StewardBench ADMIN and is transactional:

```bash
docker compose run --rm web python manage.py import_stewardbench_workbook \
  --apply --actor admin
```

Use `--path` or `--mapping` for an alternate location and `--json` for a
machine-readable report. The content must still match the mapping fixture hash;
the importer never writes the source file. The identity tuple mapping ID,
mapping version, and source SHA-256 makes an unchanged re-import a reported
no-op. Existing identical Domains, Tags, and Questions are reused. A conflicting
stable Question ID or Domain fails apply with `SOURCE_CONFLICT`; manually
managed content is never overwritten.

Imported Questions remain DRAFT. Corpus import history, source row mappings,
warnings, and LegacyObservations are visible under **Corpus imports** to both
authenticated roles. Legacy observations are explicitly not EvaluationRuns,
Executions, or attributed HumanReviews.

After changing application code, rebuild the image:

```bash
docker compose build
docker compose up -d db
docker compose run --rm web python manage.py migrate --noinput
docker compose up -d web worker
docker compose ps
```

Authenticated readiness endpoints are intentionally minimal:

- `/health/live/` reports only process liveness;
- `/health/ready/` checks PostgreSQL and reports `503` when unavailable.

They expose no credentials, build data, or product evidence.

## First ADMIN

Create the first StewardBench ADMIN after migrations:

```bash
read -rsp 'Initial StewardBench password: ' STEWARDBENCH_ADMIN_PASSWORD
export STEWARDBENCH_ADMIN_PASSWORD
docker compose run --rm -e STEWARDBENCH_ADMIN_PASSWORD web \
  python manage.py create_stewardbench_admin \
  --username admin --email admin@example.invalid \
  --password-env STEWARDBENCH_ADMIN_PASSWORD
unset STEWARDBENCH_ADMIN_PASSWORD
```

The password is read from the named environment variable inside the transient
container and is not printed. The alternate interactive form is:

```bash
docker compose run --rm web \
  python manage.py create_stewardbench_admin --username admin
```

Password validation uses Django's configured validators. The account is a
StewardBench `ADMIN`, with ordinary Django `is_staff=false` and
`is_superuser=false`. Framework staff, superuser, groups, and model permissions
never grant StewardBench ADMIN capability. A repeat bootstrap exits with an
error and makes no changes if any product ADMIN already exists or the requested
username is taken.

## Tests against PostgreSQL

The Compose application image includes the pinned test extra. Start the database
and run development or acceptance tests as one-shot application containers:

```bash
docker compose up -d db
docker compose run --rm web python -m pytest tests/unit tests/integration
docker compose run --rm web python -m pytest tests/acceptance
```

pytest creates and migrates a disposable PostgreSQL test database using the
configured PostgreSQL server. A session fixture rejects any non-PostgreSQL
connection. M1 extends the `minimal-domain` fixture with a product-neutral
Product, Environment, TargetRevision, Domain, Unicode Tag, and exact active
QuestionVersion.

Run Django and migration consistency checks with:

```bash
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py makemigrations --check --dry-run
docker compose run --rm web python manage.py migrate --plan
```

## M0 Docker smoke

The smoke script uses a uniquely named Compose project, synthetic temporary
credentials, a clean PostgreSQL volume, and host port 18080 by default:

```bash
./scripts/smoke_m0.sh
```

It builds and starts the actual topology, migrates from zero, bootstraps an
ADMIN, authenticates the ADMIN, creates and authenticates an OPERATOR through
the product UI, restarts the web container, proves the user persisted, sends an
OPERATOR direct administrative POST and expects `403`, verifies the worker
readiness log, confirms the database vendor is PostgreSQL, and checks that no
SQLite database exists. The disposable project and volume are removed on exit.

Set `STEWARD_SMOKE_PROJECT` or `STEWARD_SMOKE_PORT` only when the defaults
conflict with another local resource.

### Rootless Docker fallback

If the normal host Docker socket is intentionally inaccessible, invoke the
already-provisioned isolated rootless daemon rather than changing host group
membership or using `sudo`. Point the Docker client at that daemon's private
runtime socket, confirm it is rootless, then use the ordinary Compose and smoke
commands:

```bash
export DOCKER_HOST="unix://${XDG_RUNTIME_DIR}/<isolated-rootless-daemon>.sock"
docker version
docker info --format '{{.SecurityOptions}}'
./scripts/smoke_m0.sh
```

Use a uniquely named disposable Compose project for concurrent acceptance
work. Do not publish fake-target control ports outside that isolated test
network.

For repeatable validation, prefer the wrapper below. It preserves a usable
user-provided Docker configuration, otherwise falls back to the established
rootless socket, verifies server connectivity, and reports the selected daemon:

```bash
./scripts/with-rootless-docker.sh docker version
./scripts/with-rootless-docker.sh docker compose up -d db
```

Set `STEWARD_ROOTLESS_DOCKER_SOCKET` only when the established rootless socket
is intentionally different. The wrapper does not start daemons, change host
permissions, or require `sudo`.

## Static assets and logs

The image collects the build-free local stylesheet and WhiteNoise serves it.
There is no Node/SPA toolchain and no unfinished logo artwork. Django template
auto-escaping remains enabled.

Web and worker logs go to standard output. Configuration values, passwords,
session values, and database credentials are not intentionally logged. Normal
Gunicorn access logs contain request metadata only; do not put secrets into
URLs.
