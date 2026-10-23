#!/usr/bin/env bash
# Switch the server to this release: releases/<commit>/deploy/deploy.sh <commit>
# Run by bin/deploy-entry, which fetched the release and holds the deploy lock.
#
#   pull images -> note whether the schema changes -> back up -> start and wait for
#   health checks -> point current/ at this release.
# If health checks fail and the schema didn't change, the previous release is started
# again. If it did change, nothing is rolled back automatically (the previous code
# may not run on the new schema): the output says how to restore the backup.
#
# This output ends up in CI logs, which are public for a public repository: print
# steps and outcomes only. Command output and container logs go to logs/ on the server.
set -euo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "$(readlink -f "$0")")/lib.sh"

commit=${1:-}
is_commit "$commit" || die "usage: deploy.sh <40-hex commit>"
[[ -n $LINGO_ROOT ]] || die "deploy.sh runs inside <root>/releases/<commit>/"
[[ $PROJECT_DIR == "$LINGO_ROOT/releases/$commit" ]] || die "this is not release $commit"
if ! [[ -e /proc/self/fd/9 ]] || ! flock -n 9; then
  die "run through bin/deploy-entry (it holds the lock)"
fi

short=${commit:0:7}
release=$PROJECT_DIR
previous=$(readlink -f "$LINGO_ROOT/current" 2>/dev/null || true)
again=false
[[ $previous == "$release" ]] && again=true
[[ $again == false && -d $previous ]] || previous=""
mkdir -p "$LINGO_ROOT/logs"
log=$LINGO_ROOT/logs/$(date -u +%Y%m%dT%H%M%SZ)_$short.log

step() {
  printf '==> %s\n' "$*"
  printf '\n==> %s\n' "$*" >>"$log"
}

# Details of a step: into the log only.
quiet() {
  "$@" >>"$log" 2>&1
}

record() {
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$commit" "$1" >>"$LINGO_ROOT/deployed.log"
}

finish_failed() {
  printf 'details on the server: %s\n' "$log"
  exit 1
}

# Alembic heads the backend image of a release expects (no database needed).
schema_of() {
  compose_in "$1" run --rm --no-deps -T --entrypoint alembic backend heads 2>>"$log"
}

if $again; then
  step "deploying $short again"
else
  step "deploying $short${previous:+ (replacing $(basename "$previous" | cut -c1-7))}"
fi

step "pulling images"
quiet compose pull || { record pull-failed; echo "can't pull the images; nothing changed"; finish_failed; }

schema_changes=true
$again && schema_changes=false
if [[ -n $previous ]]; then
  new_schema=$(schema_of "$release") || { record failed; echo "can't read the new schema"; finish_failed; }
  old_schema=$(schema_of "$previous") || old_schema=""
  [[ -n $new_schema && $new_schema == "$old_schema" ]] && schema_changes=false
fi
if $schema_changes; then
  step "this release migrates the database"
fi

step "backing up the database"
quiet compose up -d --no-build --wait postgres || { record failed; echo "postgres isn't healthy; nothing changed"; finish_failed; }
backup=$("$DEPLOY_DIR/backup.sh" "before_$short" 2>>"$log") || { record failed; echo "backup failed; nothing changed"; finish_failed; }
printf '    %s\n' "$(basename "$backup")"

step "starting $short"
if quiet compose up -d --no-build --remove-orphans --wait --wait-timeout "${LINGO_DEPLOY_WAIT:-180}"; then
  ln -sfn "releases/$commit" "$LINGO_ROOT/.current.new"
  mv -T "$LINGO_ROOT/.current.new" "$LINGO_ROOT/current"
  record ok
  # Later deploys go through this release's entry point.
  install -m 755 "$DEPLOY_DIR/deploy-entry" "$LINGO_ROOT/bin/.deploy-entry.new"
  mv -T "$LINGO_ROOT/bin/.deploy-entry.new" "$LINGO_ROOT/bin/deploy-entry"

  step "cleaning up"
  "$DEPLOY_DIR/prune.sh" >>"$log" 2>&1 || echo "    cleanup failed (see the log); the deploy itself succeeded"
  step "deployed $short"
  exit 0
fi

step "health checks failed"
compose ps --all --format '    {{.Service}}: {{.State}} {{.Health}}' 2>>"$log" || true
quiet compose logs --no-color --tail 200 || true

if [[ -n $previous ]] && ! $schema_changes; then
  step "rolling back to $(basename "$previous" | cut -c1-7) (no schema change)"
  if quiet compose_in "$previous" up -d --no-build --remove-orphans --wait --wait-timeout "${LINGO_DEPLOY_WAIT:-180}"; then
    record rolled-back
    echo "rolled back; the previous release is serving again"
  else
    record rollback-failed
    echo "the rollback failed too; the site is down"
  fi
  finish_failed
fi

record failed
echo "not rolled back automatically: this release already migrated the database."
if [[ -n $previous ]]; then
  echo "to go back, on the server run"
  printf '    %s/deploy/restore.sh %s\n' "$previous" "$backup"
  echo "then deploy $(basename "$previous") again."
fi
finish_failed
