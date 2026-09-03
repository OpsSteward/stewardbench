#!/usr/bin/env bash
set -euo pipefail

repository_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
smoke_project=${STEWARD_SMOKE_PROJECT:-stewardbench-m0-smoke}
smoke_port=${STEWARD_SMOKE_PORT:-18080}

case "$smoke_project" in
  stewardbench-m0-smoke | stewardbench-m0-smoke-*) ;;
  *)
    printf 'Refusing non-smoke Compose project name: %s\n' "$smoke_project" >&2
    exit 2
    ;;
esac

if ! [[ "$smoke_port" =~ ^[0-9]+$ ]] || ((smoke_port < 1024 || smoke_port > 65535)); then
  printf 'STEWARD_SMOKE_PORT must be an unprivileged TCP port from 1024 to 65535.\n' >&2
  exit 2
fi

smoke_env=$(mktemp)
cookie_jar=$(mktemp)
admin_password='M0-Smoke-Admin-46!synthetic'
operator_password='M0-Smoke-Operator-73!synthetic'
export STEWARDBENCH_ADMIN_PASSWORD="$admin_password"

cleanup() {
  docker compose --project-directory "$repository_dir" --env-file "$smoke_env" -p "$smoke_project" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "$smoke_env" "$cookie_jar"
}
trap cleanup EXIT

cat >"$smoke_env" <<EOF
DJANGO_SECRET_KEY=m0-smoke-only-secret-key-not-for-deployment
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_SECURE_COOKIES=false
POSTGRES_DB=stewardbench
POSTGRES_USER=stewardbench
POSTGRES_PASSWORD=m0-smoke-database-password
STEWARD_WEB_PORT=$smoke_port
EOF

compose=(docker compose --project-directory "$repository_dir" --env-file "$smoke_env" -p "$smoke_project")

"${compose[@]}" build web
"${compose[@]}" up -d db
"${compose[@]}" run --rm web python manage.py migrate --noinput
"${compose[@]}" run --rm -e STEWARDBENCH_ADMIN_PASSWORD web \
  python manage.py create_stewardbench_admin --username smoke-admin --password-env STEWARDBENCH_ADMIN_PASSWORD
"${compose[@]}" up -d web worker

for attempt in $(seq 1 30); do
  if curl --fail --silent "http://127.0.0.1:$smoke_port/login/" >/dev/null; then
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    "${compose[@]}" ps
    "${compose[@]}" logs --no-color web worker
    exit 1
  fi
  sleep 1
done

curl --fail --silent "http://127.0.0.1:$smoke_port/static/css/stewardbench.css" | grep -q -- '--navy:'

csrf_from_page() {
  sed -n 's/.*name="csrfmiddlewaretoken" value="\([^"]*\)".*/\1/p' | head -n 1
}

login_page=$(curl --silent --cookie-jar "$cookie_jar" "http://127.0.0.1:$smoke_port/login/")
csrf=$(printf '%s' "$login_page" | csrf_from_page)
login_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cookie "$cookie_jar" --cookie-jar "$cookie_jar" \
  --referer "http://127.0.0.1:$smoke_port/login/" \
  --data-urlencode "csrfmiddlewaretoken=$csrf" \
  --data-urlencode "username=smoke-admin" \
  --data-urlencode "password=$admin_password" \
  "http://127.0.0.1:$smoke_port/login/")
test "$login_status" = "302"
curl --fail --silent --cookie "$cookie_jar" "http://127.0.0.1:$smoke_port/health/ready/" | grep -q '"database": "postgresql"'

create_page=$(curl --fail --silent --cookie "$cookie_jar" --cookie-jar "$cookie_jar" "http://127.0.0.1:$smoke_port/users/new/")
csrf=$(printf '%s' "$create_page" | csrf_from_page)
create_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cookie "$cookie_jar" --cookie-jar "$cookie_jar" \
  --referer "http://127.0.0.1:$smoke_port/users/new/" \
  --data-urlencode "csrfmiddlewaretoken=$csrf" \
  --data-urlencode "username=smoke-operator" \
  --data-urlencode "email=smoke-operator@example.invalid" \
  --data-urlencode "role=OPERATOR" \
  --data-urlencode "is_active=on" \
  --data-urlencode "password1=$operator_password" \
  --data-urlencode "password2=$operator_password" \
  "http://127.0.0.1:$smoke_port/users/new/")
test "$create_status" = "302"

"${compose[@]}" restart web worker
for attempt in $(seq 1 30); do
  if curl --fail --silent "http://127.0.0.1:$smoke_port/login/" >/dev/null; then break; fi
  sleep 1
done

rm -f "$cookie_jar"
login_page=$(curl --silent --cookie-jar "$cookie_jar" "http://127.0.0.1:$smoke_port/login/")
csrf=$(printf '%s' "$login_page" | csrf_from_page)
operator_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cookie "$cookie_jar" --cookie-jar "$cookie_jar" \
  --referer "http://127.0.0.1:$smoke_port/login/" \
  --data-urlencode "csrfmiddlewaretoken=$csrf" \
  --data-urlencode "username=smoke-operator" \
  --data-urlencode "password=$operator_password" \
  "http://127.0.0.1:$smoke_port/login/")
test "$operator_status" = "302"

dashboard=$(curl --fail --silent --cookie "$cookie_jar" "http://127.0.0.1:$smoke_port/")
printf '%s' "$dashboard" | grep -q 'smoke-operator'
printf '%s' "$dashboard" | grep -q 'OPERATOR'

operator_csrf=$(awk '$6 == "csrftoken" {print $7}' "$cookie_jar" | tail -n 1)
denied_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --cookie "$cookie_jar" \
  --referer "http://127.0.0.1:$smoke_port/users/new/" \
  --data-urlencode "csrfmiddlewaretoken=$operator_csrf" \
  --data-urlencode "username=forbidden-user" \
  --data-urlencode "role=ADMIN" \
  --data-urlencode "password1=Forbidden-Account-89!synthetic" \
  --data-urlencode "password2=Forbidden-Account-89!synthetic" \
  "http://127.0.0.1:$smoke_port/users/new/")
test "$denied_status" = "403"

vendor=$("${compose[@]}" exec -T web python manage.py shell -c 'from django.db import connection; print(connection.vendor)' | tail -n 1)
test "$vendor" = "postgresql"
"${compose[@]}" exec -T web sh -c '! find /app -name "*.sqlite3" -print -quit | grep -q .'
"${compose[@]}" logs --no-color worker | grep -Eq 'Worker foundation ready|M3 sequential worker ready'

printf 'M0 Docker smoke PASS: PostgreSQL, migrations, bootstrap, ADMIN/OPERATOR login, restart persistence, RBAC denial, and worker readiness.\n'
