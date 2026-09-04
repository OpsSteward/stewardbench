#!/usr/bin/env bash
set -euo pipefail

repository_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
project=${STEWARD_M11_PROJECT:-stewardbench-m11-acceptance}
port=${STEWARD_M11_PORT:-18091}
env_file=$(mktemp)
cookie_jar=$(mktemp)
admin_password='M11-Docker-Admin-84!synthetic'
export STEWARDBENCH_ADMIN_PASSWORD="$admin_password"

case "$project" in
  stewardbench-m11-acceptance | stewardbench-m11-acceptance-*) ;;
  *) printf 'Refusing non-acceptance project name: %s\n' "$project" >&2; exit 2 ;;
esac

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "$env_file" "$cookie_jar"
}
trap cleanup EXIT

cat >"$env_file" <<EOF
DJANGO_SECRET_KEY=m11-docker-only-secret-not-for-deployment
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_SECURE_COOKIES=false
POSTGRES_DB=stewardbench
POSTGRES_USER=stewardbench
POSTGRES_PASSWORD=m11-docker-database-password
STEWARD_WEB_PORT=$port
STEWARD_BENCH_APPLICATION_VERSION=1.0.0
EOF

compose=(docker compose --project-directory "$repository_dir" --env-file "$env_file" -p "$project" -f "$repository_dir/compose.yaml" -f "$repository_dir/harness/compose.acceptance.yaml")

"${compose[@]}" build web
"${compose[@]}" up -d db
"${compose[@]}" run --rm web python manage.py migrate --noinput
"${compose[@]}" run --rm -e STEWARDBENCH_ADMIN_PASSWORD web python manage.py create_stewardbench_admin --username m11-admin --password-env STEWARDBENCH_ADMIN_PASSWORD
"${compose[@]}" up -d fake-target web worker

for attempt in $(seq 1 40); do
  curl --fail --silent "http://127.0.0.1:$port/login/" >/dev/null && break
  test "$attempt" -lt 40 || exit 1
  sleep 1
done

login_page=$(curl --silent --cookie-jar "$cookie_jar" "http://127.0.0.1:$port/login/")
csrf=$(printf '%s' "$login_page" | sed -n 's/.*name="csrfmiddlewaretoken" value="\([^"]*\)".*/\1/p' | head -n 1)
login_status=$(curl --silent --output /dev/null --write-out '%{http_code}' --cookie "$cookie_jar" --cookie-jar "$cookie_jar" --referer "http://127.0.0.1:$port/login/" --data-urlencode "csrfmiddlewaretoken=$csrf" --data-urlencode 'username=m11-admin' --data-urlencode "password=$admin_password" "http://127.0.0.1:$port/login/")
test "$login_status" = 302

seed=$("${compose[@]}" exec -T web python manage.py shell -c "from accounts.models import User; from catalog.models import Question; from catalog.services import create_product,create_environment,create_domain,create_target,create_question; from evaluations.services import launch_run; import json; a=User.objects.get(username='m11-admin'); p=create_product(actor=a,slug='m11-product',display_name='M11 Product'); e=create_environment(actor=a,slug='m11-environment',display_name='M11 Environment'); d=create_domain(actor=a,slug='m11-domain',name='M11 Domain'); t=create_target(actor=a,slug='m11-target',display_name='M11 Target',product=p,environment=e,revision={'endpoint':'http://fake-target.test:18081','adapter_key':'fake-http','adapter_version':'1','credential_reference':'','classification':'LAB_TEST','supports_question_api':True,'supports_conversation_session':False,'supports_runtime_metadata':True,'supports_health_check':True,'default_execution_mode':'SEQUENTIAL','max_concurrency':1,'question_timeout_seconds':10,'inter_question_delay_seconds':0,'declared_product_version':'m11-fake','declared_build_id':'m11-build','declared_git_sha':'191cf73'}); q=create_question(actor=a,stable_id='M11-DOCKER-001',kind=Question.Kind.SINGLE_TURN,lifecycle=Question.Lifecycle.ACTIVE,domain=d,tags=(),rationale='',question_text='Return the deterministic M11 Unicode answer: operação segura.'); r=launch_run(actor=a,target=t,question_ids=[q.pk]); print(json.dumps({'run_id':str(r.pk)}))" | tail -n 1)
run_id=$(printf '%s' "$seed" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')

for attempt in $(seq 1 100); do
  state=$("${compose[@]}" exec -T web python manage.py shell -c "from evaluations.models import EvaluationRun; print(EvaluationRun.objects.get(pk='$run_id').state)" | tail -n 1)
  case "$state" in COMPLETED|COMPLETED_WITH_ERRORS|FAILED) break;; esac
  test "$attempt" -lt 100 || exit 1
  sleep 0.2
done
if [ "$state" != COMPLETED ]; then
  printf 'Unexpected terminal state: %s\n' "$state" >&2
  "${compose[@]}" exec -T web python manage.py shell -c "from evaluations.models import EvaluationRun; r=EvaluationRun.objects.get(pk='$run_id'); print(list(r.executions.values('outcome','error_class','error_detail','target_call_phase')))" >&2
  "${compose[@]}" logs --no-color worker fake-target >&2
  exit 1
fi

snapshot() {
  "${compose[@]}" exec -T web python manage.py shell -c "from evaluations.models import EvaluationRun; import hashlib,json; r=EvaluationRun.objects.get(pk='$run_id'); x=r.executions.get(); print(json.dumps({'run_id':str(r.pk),'run_state':r.state,'execution_id':str(x.pk),'correlation_id':str(x.request_correlation_id),'outcome':x.outcome,'normalized_answer':x.display_answer,'evidence_fingerprint':hashlib.sha256((x.raw_response+'|'+json.dumps(x.evidence,sort_keys=True,ensure_ascii=False)).encode()).hexdigest(),'latency_ms':x.latency_ms,'execution_count':r.executions.count()}))" | tail -n 1
}

journal() {
  "${compose[@]}" exec -T web python -c "from urllib.request import Request,urlopen; import json; q=Request('http://fake-target.test:18081/__journal',headers={'X-Fake-Control-Token':'m11-synthetic-control'}); print(urlopen(q,timeout=3).read().decode())" | tail -n 1
}

before=$(snapshot)
before_journal=$(journal)
test "$(printf '%s' "$before_journal" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["entries"]))')" = 1

"${compose[@]}" restart web
test "$(snapshot)" = "$before"
"${compose[@]}" restart worker
sleep 1
test "$(snapshot)" = "$before"
"${compose[@]}" restart db
for attempt in $(seq 1 40); do "${compose[@]}" exec -T db pg_isready -U stewardbench -d stewardbench >/dev/null 2>&1 && break; sleep 0.5; done
test "$(snapshot)" = "$before"

"${compose[@]}" down --remove-orphans
"${compose[@]}" up -d
for attempt in $(seq 1 40); do "${compose[@]}" exec -T web python manage.py check_database >/dev/null 2>&1 && break; sleep 0.5; done
after=$(snapshot)
after_journal=$(journal)
test "$after" = "$before"
test "$(printf '%s' "$after_journal" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["entries"]))')" = 1
sleep 1
test "$(snapshot)" = "$before"
test "$(printf '%s' "$(journal)" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["entries"]))')" = 1

printf 'ACC-DOCKER-001 PASS\n%s\n%s\n' "$after" "$after_journal"
