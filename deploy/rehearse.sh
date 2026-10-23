#!/usr/bin/env bash
# Rehearse a registry deploy end to end on this machine (CI's deploy-rehearsal job):
#   deploy/rehearse.sh [backend image] [frontend image]
# (default: lingo-agent-backend:latest and lingo-agent-frontend:latest, as `make up`
# builds them). Starts a throwaway registry and server root, then deploys through
# bin/deploy-entry exactly as the server does:
#   1. first deploy            -> serving, current/ set
#   2. upgrade, same schema    -> serving, backup taken
#   3. broken, same schema     -> fails, rolled back to 2
#   4. broken, new migration   -> fails, not rolled back; restore + redeploy 2 works
# Uses compose project lingo-rehearsal and ports 5544 / 8100 / 3100, so a running
# dev stack is left alone. Needs about 1.5GB of memory while it runs.
set -euo pipefail

repo=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
backend_src=${1:-lingo-agent-backend:latest}
frontend_src=${2:-lingo-agent-frontend:latest}
registry=127.0.0.1:5555
registry_name=lingo-rehearsal-registry
project=lingo-rehearsal
root=$(mktemp -d /tmp/lingo-rehearsal.XXXXXX)

# Fake commits, one per scenario.
a=$(printf 'a%.0s' {1..40})
b=$(printf 'b%.0s' {1..40})
c=$(printf 'c%.0s' {1..40})
d=$(printf 'd%.0s' {1..40})

failures=0
check() {
  local what=$1
  shift
  if "$@"; then
    printf 'PASS  %s\n' "$what"
  else
    printf 'FAIL  %s\n' "$what"
    failures=$((failures + 1))
  fi
}

cleanup() {
  docker compose -p "$project" down -v --remove-orphans >/dev/null 2>&1 || true
  docker volume rm "${project}_pgdata" >/dev/null 2>&1 || true
  docker rm -f "$registry_name" >/dev/null 2>&1 || true
  rm -rf "$root"
}
trap cleanup EXIT

echo "==> registry and server root ($root)"
docker run -d --rm --name "$registry_name" -p "$registry:5000" registry:2.8.3 >/dev/null
mkdir -p "$root/shared/postgres-init" "$root/bin" "$root/releases"
cp -r "$repo/docker/postgres/init/." "$root/shared/postgres-init/"
install -m 755 "$repo/deploy/deploy-entry" "$root/bin/deploy-entry"
cat >"$root/shared/.env" <<EOF
COMPOSE_PROJECT_NAME=$project
BACKEND_IMAGE=$registry/lingo/backend
FRONTEND_IMAGE=$registry/lingo/frontend
RELEASE_IMAGE=$registry/lingo/release
POSTGRES_IMAGE=$registry/lingo/pgvector:pg16
POSTGRES_INIT_DIR=$root/shared/postgres-init
POSTGRES_PASSWORD=rehearsal
POSTGRES_HOST_PORT=5544
BACKEND_HOST_PORT=8100
FRONTEND_HOST_PORT=3100
FRONTEND_HOST_BIND=127.0.0.1
JWT_SECRET=rehearsal
CREDENTIALS_ENCRYPTION_KEYS=r:$(openssl rand -base64 32 | tr '+/' '-_')
SCHEDULER_ENABLED=false
MEMORY_REFLECTION_ENABLED=false
EOF

push() { # push <source image> <target repo> <commit>
  docker tag "$1" "$registry/lingo/$2:$3"
  docker push -q "$registry/lingo/$2:$3" >/dev/null
}

echo "==> pushing four releases"
docker image inspect pgvector/pgvector:pg16 >/dev/null 2>&1 || docker pull -q pgvector/pgvector:pg16 >/dev/null
push pgvector/pgvector:pg16 pgvector pg16
docker build -q -f "$repo/deploy/release.Dockerfile" -t rehearsal-release "$repo" >/dev/null
head=$(docker run --rm --entrypoint alembic "$backend_src" heads | awk '{print $1}')
docker build -q -t rehearsal-unhealthy - >/dev/null <<EOF
FROM $backend_src
HEALTHCHECK --interval=2s --timeout=2s --start-period=1s --retries=1 CMD ["false"]
EOF
docker build -q -t rehearsal-migrates - >/dev/null <<EOF
FROM rehearsal-unhealthy
USER root
RUN printf '%s\n' \
  'revision = "rehearsal0001"' 'down_revision = "$head"' 'branch_labels = None' \
  'depends_on = None' 'def upgrade(): pass' 'def downgrade(): pass' \
  >app/db/migrations/versions/rehearsal0001.py
USER lingo
EOF
for commit in "$a" "$b" "$c" "$d"; do
  push rehearsal-release release "$commit"
  push "$frontend_src" frontend "$commit"
done
push "$backend_src" backend "$a"
push "$backend_src" backend "$b"
push rehearsal-unhealthy backend "$c"
push rehearsal-migrates backend "$d"

deploy() { # deploy <commit>: output in $root/out, status in $status
  status=0
  LINGO_DEPLOY_WAIT=${LINGO_DEPLOY_WAIT:-120} SSH_ORIGINAL_COMMAND="deploy $1" \
    "$root/bin/deploy-entry" >"$root/out" 2>&1 || status=$?
  sed 's/^/      | /' "$root/out"
}
current_is() { [[ $(readlink "$root/current") == "releases/$1" ]]; }
last_record_is() { [[ $(tail -n 1 "$root/deployed.log" | cut -d' ' -f3) == "$1" ]]; }
healthy() { [[ $(docker compose -p "$project" ps backend --format '{{.Health}}') == healthy ]]; }
serves_login() { curl -fsS -o /dev/null http://127.0.0.1:3100/login; }
said() { grep -q -- "$1" "$root/out"; }
has_backup() { compgen -G "$root/backups/*_before_$1.dump" >/dev/null; }

echo "==> only \"deploy <commit>\" gets through"
status=0
SSH_ORIGINAL_COMMAND="sh -c id" "$root/bin/deploy-entry" >/dev/null 2>&1 || status=$?
check "other commands are refused" test "$status" -ne 0
status=0
SSH_ORIGINAL_COMMAND="deploy $a; id" "$root/bin/deploy-entry" >/dev/null 2>&1 || status=$?
check "extra words are refused" test "$status" -ne 0

echo "==> 1. first deploy"
deploy "$a"
check "succeeds" test "$status" -eq 0
check "current is the release" current_is "$a"
check "the site serves" serves_login

echo "==> 2. upgrade with the same schema"
deploy "$b"
check "succeeds" test "$status" -eq 0
check "current moved" current_is "$b"
check "backed up first" has_backup "${b:0:7}"
check "the site serves" serves_login

echo "==> 3. unhealthy release, same schema"
deploy "$c"
check "fails" test "$status" -ne 0
check "rolled back" last_record_is rolled-back
check "current unchanged" current_is "$b"
check "previous release healthy" healthy
check "no container logs in the output" bash -c "! grep -qi 'uvicorn\|traceback' '$root/out'"

echo "==> 4. unhealthy release with a new migration"
deploy "$d"
check "fails" test "$status" -ne 0
check "not rolled back" last_record_is failed
check "says how to restore" said "restore.sh"
check "current unchanged" current_is "$b"
backup=$(compgen -G "$root/backups/*_before_${d:0:7}.dump")
"$root/releases/$b/deploy/restore.sh" --yes "$backup" >"$root/out" 2>&1 || true
check "restore succeeds" said "^restored$"
deploy "$b"
check "redeploying the same release says so" said "deploying ${b:0:7} again"
check "restore + redeploy succeeds" test "$status" -eq 0
check "back on the previous schema" healthy

if ((failures > 0)); then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
