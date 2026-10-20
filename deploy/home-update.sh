#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="${GOLD_DIGGER_HOME:-$HOME/gold-digger}"
cd "$APP_DIR"
exec 9>"$APP_DIR/.deploy.lock"
flock -n 9 || exit 0

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Tracked files modified locally; refusing automatic update" >&2
  exit 1
fi
git fetch --quiet origin main
current="$(git rev-parse HEAD)"
remote="$(git rev-parse origin/main)"
running="$(docker compose ps -q gold-digger)"
if [[ "$current" == "$remote" && -n "$running" ]]; then
  echo "No new commit; container exists"
  exit 0
fi

git merge --ff-only origin/main
docker compose config --quiet
# Build from source on the home machine; no GHCR dependency.
docker compose build --pull
docker compose up -d
healthy=0
for attempt in $(seq 1 20); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8080/health >/dev/null; then
    healthy=1
    break
  fi
  sleep 3
done
if [[ "$healthy" -ne 1 ]]; then
  echo "Health check failed after local build/deploy; inspect docker compose logs" >&2
  exit 1
fi
echo "Local build deployed from $remote"
