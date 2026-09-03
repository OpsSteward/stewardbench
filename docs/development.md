# M0 development and deployment

This page documents the implemented M0 foundation only. It does not describe or
imply question, target, run, baseline, comparator, judge, or adapter capability.

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

`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, secure-cookie behavior,
TLS redirect behavior, database connection settings, the host web port, worker
poll interval, and log level are optional environment configuration. Keep
`DJANGO_DEBUG=false` and secure cookies enabled on a DGX or other non-local
deployment. Terminate TLS at the deployment proxy and configure trusted origins
for the deployed HTTPS origin. Never put `.env` into an image or commit it.

## Docker topology

`compose.yaml` defines three long-running services:

- `web`: Gunicorn serving the Django application;
- `worker`: the same image running `python manage.py run_worker`; and
- `db`: PostgreSQL 17.11 with the named `postgres_data` volume.

The M0 worker connects to PostgreSQL, logs one readiness message, and stays
alive with a bounded idle loop. It has no job table, claim logic, target call,
or evaluation semantics. Those belong to later milestones. Both application
services wait for PostgreSQL health. Migrations remain an explicit one-shot
operation and never run implicitly in web or worker startup.

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
connection.

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

## Static assets and logs

The image collects the build-free local stylesheet and WhiteNoise serves it.
There is no Node/SPA toolchain and no unfinished logo artwork. Django template
auto-escaping remains enabled.

Web and worker logs go to standard output. Configuration values, passwords,
session values, and database credentials are not intentionally logged. Normal
Gunicorn access logs contain request metadata only; do not put secrets into
URLs.
