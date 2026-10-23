# shellcheck shell=bash disable=SC2034  # sourced: the variables are used by the scripts
# Shared by the scripts in deploy/ (sourced, not run). See docs/deploy.md.
#
# The scripts work in two layouts:
# - a checkout: the project is the repo root, backups go to <repo>/backups;
# - a server deployed from a registry (LINGO_ROOT, usually /srv/lingo-agent):
#     releases/<commit>/   one release: compose file, config/, deploy/
#     current -> releases/<commit>
#     shared/.env          the only copy of settings and secrets
#     backups/  logs/  bin/deploy-entry
#   Each release has .env -> ../../shared/.env and .release.env (IMAGE_TAG=<commit>).

DEPLOY_DIR=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
PROJECT_DIR=$(dirname "$DEPLOY_DIR")
if [[ $(basename "$(dirname "$PROJECT_DIR")") == releases ]]; then
  LINGO_ROOT=${LINGO_ROOT:-$(dirname "$(dirname "$PROJECT_DIR")")}
fi
LINGO_ROOT=${LINGO_ROOT:-}
if [[ -n $LINGO_ROOT ]]; then
  BACKUP_DIR=${LINGO_BACKUP_DIR:-$LINGO_ROOT/backups}
else
  BACKUP_DIR=${LINGO_BACKUP_DIR:-$PROJECT_DIR/backups}
fi

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

# docker compose for the release (or checkout) in $1. A release adds .release.env,
# which pins IMAGE_TAG to its commit on top of the shared .env.
compose_in() {
  local dir=$1
  shift
  local args=(--project-directory "$dir")
  if [[ -f $dir/.release.env ]]; then
    args+=(--env-file "$dir/.env" --env-file "$dir/.release.env")
  fi
  docker compose "${args[@]}" "$@"
}

compose() {
  compose_in "$PROJECT_DIR" "$@"
}

is_commit() {
  [[ $1 =~ ^[0-9a-f]{40}$ ]]
}
