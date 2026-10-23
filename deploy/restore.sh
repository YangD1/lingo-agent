#!/usr/bin/env bash
# Replace the database with a dump from backup.sh: deploy/restore.sh [--yes] <file>
# Backs up the current database first, stops the app while restoring, then starts it
# again. The app version must match the dump's schema: restore before deploying the
# release the dump was taken under, not after.
set -euo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "$(readlink -f "$0")")/lib.sh"

yes=false
if [[ ${1:-} == --yes ]]; then
  yes=true
  shift
fi
file=${1:-}
[[ -n $file ]] || die "usage: deploy/restore.sh [--yes] <dump file>"
[[ -f $file ]] || die "no such file: $file"

compose exec -T postgres pg_restore --list <"$file" >/dev/null || die "not a readable dump: $file"

if ! $yes; then
  [[ -t 0 ]] || die "pass --yes to restore without a terminal"
  printf 'Replace the database of %s with %s? [y/N] ' "$PROJECT_DIR" "$file"
  read -r answer
  [[ $answer == [yY] ]] || die "cancelled"
fi

echo "==> backing up the current database"
"$DEPLOY_DIR/backup.sh" before_restore

echo "==> stopping the app"
compose stop backend frontend

echo "==> restoring $file"
# One transaction: a failed restore leaves the database as it was.
# shellcheck disable=SC2016  # expanded inside the container
if ! compose exec -T postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction' \
  <"$file"; then
  compose up -d --no-build --wait backend frontend || true
  die "restore failed; the database is unchanged and the app was started again"
fi

echo "==> starting the app"
compose up -d --no-build --wait backend frontend
echo "restored"
