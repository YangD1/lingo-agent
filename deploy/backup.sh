#!/usr/bin/env bash
# Dump the database of this checkout or release: deploy/backup.sh [label]
# Writes <backups>/<UTC time>_<label>.dump (pg_dump custom format), checks it can be
# read back, keeps the newest LINGO_BACKUP_KEEP (default 14) and prints its path.
#
# The dump holds model API keys encrypted with CREDENTIALS_ENCRYPTION_KEYS from .env:
# keep a copy of .env elsewhere, or a restored database can't decrypt them.
set -euo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "$(readlink -f "$0")")/lib.sh"

label=${1:-manual}
[[ $label =~ ^[A-Za-z0-9_-]+$ ]] || die "label may only contain letters, digits, - and _"
keep=${LINGO_BACKUP_KEEP:-14}
[[ $keep =~ ^[1-9][0-9]*$ ]] || die "LINGO_BACKUP_KEEP must be a positive number"

umask 077
mkdir -p "$BACKUP_DIR"
file=$BACKUP_DIR/$(date -u +%Y%m%dT%H%M%SZ)_$label.dump

# Credentials come from the container's own environment, not from parsing .env.
# shellcheck disable=SC2016  # expanded inside the container
compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$file.partial" ||
  { rm -f "$file.partial"; die "pg_dump failed"; }
compose exec -T postgres pg_restore --list <"$file.partial" >/dev/null ||
  { rm -f "$file.partial"; die "the dump can't be read back"; }
mv "$file.partial" "$file"

# Names start with the time, so name order is age order.
mapfile -t dumps < <(find "$BACKUP_DIR" -maxdepth 1 -name '*.dump' -printf '%f\n' | sort)
if ((${#dumps[@]} > keep)); then
  for old in "${dumps[@]:0:${#dumps[@]}-keep}"; do
    rm -f "${BACKUP_DIR:?}/$old"
  done
fi

printf '%s\n' "$file"
