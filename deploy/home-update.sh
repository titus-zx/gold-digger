#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="${GOLD_DIGGER_HOME:-$HOME/gold-digger}"
cd "$APP_DIR"
exec 9>"$APP_DIR/.deploy.lock"
flock -n 9 || exit 0

# Stop on local modifications rather than discarding user changes.
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Tracked files modified locally; refusing automatic update" >&2
  exit 1
fi
git fetch --quiet origin main
git merge --ff-only origin/main
docker compose config --quiet
old_image="$(docker image inspect ghcr.io/titus-zx/gold-digger:main --format '{{.Id}}' 2>/dev/null || true)"
docker compose pull gold-digger
new_image="$(docker image inspect ghcr.io/titus-zx/gold-digger:main --format '{{.Id}}' 2>/dev/null || true)"
running_image="$(docker inspect --format '{{.Image}}' "$(docker compose ps -q gold-digger)" 2>/dev/null || true)"
if [[ "$new_image" == "$running_image" ]]; then
  echo "Already running latest image: $new_image"
  exit 0
fi
docker compose up -d --no-deps gold-digger
healthy=0
for attempt in $(seq 1 20); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8080/health >/dev/null; then
    healthy=1
    break
  fi
  sleep 3
done
if [[ "$healthy" -ne 1 ]]; then
  echo "Health check failed after deploy" >&2
  if [[ -n "$old_image" && "$old_image" != "$new_image" ]]; then
    docker tag "$old_image" ghcr.io/titus-zx/gold-digger:main
    docker compose up -d --no-deps --force-recreate gold-digger
    echo "Restored previous local image (check config compatibility)" >&2
  fi
  exit 1
fi
echo "Deployment healthy: $new_image"
