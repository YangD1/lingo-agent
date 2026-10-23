#!/usr/bin/env bash
# Free disk after a successful deploy (run by deploy.sh): keep the newest
# LINGO_KEEP_RELEASES (default 5) releases plus the current one, remove the others
# and their images, unused image layers and logs older than 30 days.
set -euo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "$(readlink -f "$0")")/lib.sh"

[[ -n $LINGO_ROOT ]] || die "prune.sh runs inside <root>/releases/<commit>/"
keep=${LINGO_KEEP_RELEASES:-5}
current=$(basename "$(readlink -f "$LINGO_ROOT/current")")

# Newest first.
mapfile -t releases < <(
  find "$LINGO_ROOT/releases" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended \
    -regex '.*/[0-9a-f]{40}' -printf '%T@ %f\n' | sort -rn | cut -d' ' -f2
)
kept=("$current")
removed=()
for release in "${releases[@]}"; do
  [[ $release == "$current" ]] && continue
  if ((${#kept[@]} < keep)); then
    kept+=("$release")
  else
    removed+=("$release")
  fi
done

# Repositories of this release's images, minus the tag (postgres isn't per release).
mapfile -t repos < <(
  compose config --images | grep -F ":$current" | sed "s/:$current\$//"
  sed -n 's/^RELEASE_IMAGE=//p' "$LINGO_ROOT/shared/.env" | tail -n 1 | tr -d "\"'"
)

for release in "${removed[@]}"; do
  echo "removing release $release"
  rm -rf "${LINGO_ROOT:?}/releases/$release"
  for repo in "${repos[@]}"; do
    [[ -n $repo ]] && docker image rm "$repo:$release" 2>/dev/null || true
  done
done

# Fetches interrupted before they finished.
find "$LINGO_ROOT/releases" -maxdepth 1 -name '.incoming.*' -mmin +60 -exec rm -rf {} +
docker image prune -f
find "$LINGO_ROOT/logs" -name '*.log' -mtime +30 -delete
