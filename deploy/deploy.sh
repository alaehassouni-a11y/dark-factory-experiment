#!/usr/bin/env bash
# Blue/green deploy script for the Virtual Agent. Polls git, rebuilds inactive
# color, waits for healthcheck, swaps Caddy upstream with graceful reload,
# stops old. Safe to run when blue/green isn't set up yet — it detects and
# no-ops.
#
# This file is the source-of-truth copy; the live VPS copy at
# /opt/virtualagent/deploy.sh is kept in sync by hand. The systemd timer that
# drives it doesn't pull this from git, so changes here must be mirrored to
# the VPS to take effect.
#
# The wiki (virtualagent/resources/) is copied into the image by the
# Dockerfile, so a wiki-only commit goes through exactly this path: new image
# on the inactive color, healthcheck, flip. There is nothing to sync.
set -euo pipefail

# Paths derive from where this script lives, so the same file works at
# /opt/virtualagent/deploy.sh (the layout deploy/README.md describes) and at
# whatever older root a host still uses. Each can be overridden by environment.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${VIRTUALAGENT_ROOT:-$HERE}"
REPO="${VIRTUALAGENT_REPO:-$ROOT/app}"
ENV_FILE="${VIRTUALAGENT_ENV:-$ROOT/.env}"
COMPOSE_DIR="$REPO/deploy"
UPSTREAM_FILE="$COMPOSE_DIR/upstream.conf"
LOG="${VIRTUALAGENT_LOG:-/var/log/virtualagent-deploy.log}"
LOCK="${VIRTUALAGENT_LOCK:-/var/run/virtualagent-deploy.lock}"

exec >>"$LOG" 2>&1

compose() { docker compose --env-file "$ENV_FILE" "$@"; }

# Concurrency guard — flock on LOCK fd
exec 200>"$LOCK"
flock -n 200 || { echo "[$(date -Iseconds)] another deploy running, exit"; exit 0; }

echo "[$(date -Iseconds)] ---- deploy check start ----"

if [ ! -d "$REPO" ]; then
    echo "[$(date -Iseconds)] ERROR: no directory at $REPO (set VIRTUALAGENT_ROOT or VIRTUALAGENT_REPO)"
    exit 1
fi
# stderr is the log (exec above), so git's own reason lands on the line before this one.
if ! git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null; then
    echo "[$(date -Iseconds)] ERROR: git refused $REPO - its reason is on the line above. A checkout owned by another user needs: git config --global --add safe.directory $REPO (for the user running this script)"
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "[$(date -Iseconds)] ERROR: no env file at $ENV_FILE (set VIRTUALAGENT_ENV)"
    exit 1
fi
# Pre-flight against the checkout AS IT IS NOW, before anything is pulled, so a
# host whose env file lacks a required variable is told so on every run and
# nothing is half-done. A commit that itself adds a required variable gets past
# this one and is caught by the second check after the pull, which rolls the
# pull back for the same reason.
if ! compose -f "$COMPOSE_DIR/docker-compose.yml" config >/dev/null; then
    echo "[$(date -Iseconds)] ERROR: docker compose config failed against $ENV_FILE - a required variable is missing (see deploy/.env.example). Nothing was pulled."
    exit 1
fi

cd "$REPO"
git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse @{u})
if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[$(date -Iseconds)] no changes (HEAD=$LOCAL)"
    exit 0
fi

echo "[$(date -Iseconds)] changes: $LOCAL -> $REMOTE, pulling"
git pull --ff-only --quiet

cd "$COMPOSE_DIR"

# The compose file refuses to render without VIRTUALAGENT_HOST and
# LETSENCRYPT_EMAIL in the env file. Check that FIRST and fail loudly: the
# blue/green gate below would otherwise read a failed `config` as "not yet
# configured" and exit 0 with nothing deployed.
if ! compose config >/dev/null; then
    echo "[$(date -Iseconds)] ERROR: docker compose config failed - a required variable is missing from $ENV_FILE (see deploy/.env.example)"
    # Roll the pull back, or every later run would compare HEAD to origin/main,
    # log 'no changes' and exit 0 - the timer looking healthy while nothing is
    # deployed. `reset`, not `checkout`: a detached HEAD breaks the @{u} lookup.
    git -C "$REPO" reset --hard --quiet "$LOCAL"
    echo "[$(date -Iseconds)] rolled the checkout back to $LOCAL; the next run retries once $ENV_FILE is fixed"
    exit 1
fi

# Caddy reads VIRTUALAGENT_HOST and LETSENCRYPT_EMAIL from its own container
# environment, and `caddy reload` re-reads the Caddyfile but never that
# environment. A container created before those variables existed would fail
# the reload below, and the restart fallback would then crash-loop it on the
# new Caddyfile: a full outage. `up -d` recreates the container only when its
# config changed (a few seconds, once) and is a no-op otherwise.
compose up -d --no-deps caddy

# Reload Caddy reliably. `caddy reload` re-parses the Caddyfile (which imports
# upstream.conf), but in 2026-04 we hit a case where the live in-memory config
# kept dialing the old container even though upstream.conf on disk had been
# rewritten. Production 502'd until Caddy was hard-restarted. The fix: after
# `caddy reload`, check that the running Caddy config actually contains the
# expected upstream; if not, fall back to `docker restart` (~3s downtime,
# vastly better than an indefinite outage).
swap_caddy_upstream() {
    local expected="$1"   # e.g. "app-green:8000"
    sync
    compose exec -T caddy \
        caddy reload --config /etc/caddy/Caddyfile || {
            echo "[$(date -Iseconds)] caddy reload returned non-zero — will verify and restart if needed"
        }

    # Verify reload took effect by reading the live admin-API config.
    sleep 1
    local live
    live=$(docker exec virtualagent-caddy wget -qO- --timeout=3 \
        http://127.0.0.1:2019/config/ 2>/dev/null || echo "")
    if echo "$live" | grep -q "$expected"; then
        echo "[$(date -Iseconds)] caddy reload verified — routing to $expected"
        return 0
    fi

    echo "[$(date -Iseconds)] WARNING: caddy reload did not apply (live config missing '$expected'). Forcing restart."
    compose restart caddy
    # Wait briefly for Caddy to come back. We're not strict here — if Caddy
    # itself is broken the next deploy attempt or a human will catch it.
    for i in $(seq 1 15); do
        if docker exec virtualagent-caddy wget -qO- --timeout=2 \
            http://127.0.0.1:2019/config/ 2>/dev/null | grep -q "$expected"; then
            echo "[$(date -Iseconds)] caddy restart verified — routing to $expected"
            return 0
        fi
        sleep 1
    done
    echo "[$(date -Iseconds)] ERROR: caddy still not routing to $expected after restart"
    return 1
}

# Gate: require blue/green services + upstream.conf to exist before deploying
if ! compose config --services 2>/dev/null | grep -q '^app-blue$'; then
    echo "[$(date -Iseconds)] blue/green not yet configured in compose — skipping. Reload caddy only if its config changed (safe, no app dependency)."
    compose up -d --no-deps caddy || true
    exit 0
fi

if [ ! -f "$UPSTREAM_FILE" ]; then
    echo "[$(date -Iseconds)] upstream.conf missing — initial deploy. Starting app-blue."
    echo 'reverse_proxy app-blue:8000' > "$UPSTREAM_FILE"
    compose up -d --build app-blue
    # Wait for healthy
    for i in $(seq 1 900); do
        S=$(docker inspect --format='{{.State.Health.Status}}' virtualagent-app-blue 2>/dev/null || echo missing)
        [ "$S" = "healthy" ] && break
        sleep 2
    done
    [ "$S" = "healthy" ] || { echo "[$(date -Iseconds)] app-blue failed healthcheck ($S)"; exit 1; }
    swap_caddy_upstream "app-blue:8000"
    echo "[$(date -Iseconds)] initial deploy complete: app-blue healthy"
    exit 0
fi

# Standard blue/green swap
ACTIVE=$(grep -oE 'app-(blue|green)' "$UPSTREAM_FILE" | head -1 | sed 's/app-//')
if [ "$ACTIVE" = "blue" ]; then INACTIVE=green; else INACTIVE=blue; fi
echo "[$(date -Iseconds)] active=$ACTIVE, deploying to $INACTIVE"

# Build + start inactive
compose up -d --build --no-deps "app-$INACTIVE"

# Wait for inactive to be healthy (90s budget)
for i in $(seq 1 900); do
    S=$(docker inspect --format='{{.State.Health.Status}}' "virtualagent-app-$INACTIVE" 2>/dev/null || echo missing)
    [ "$S" = "healthy" ] && break
    sleep 2
done
if [ "$S" != "healthy" ]; then
    echo "[$(date -Iseconds)] app-$INACTIVE unhealthy ($S) — aborting, keeping $ACTIVE live"
    compose stop "app-$INACTIVE" || true
    exit 1
fi

# Flip Caddy upstream + graceful reload (zero dropped connections in the happy
# path; ~3s drop with restart fallback if reload misfires)
echo "reverse_proxy app-$INACTIVE:8000" > "$UPSTREAM_FILE"
swap_caddy_upstream "app-$INACTIVE:8000"

# Give in-flight requests a moment to drain from old upstream
sleep 5

# Stop old
compose stop "app-$ACTIVE" || true
echo "[$(date -Iseconds)] deploy complete: $ACTIVE -> $INACTIVE"
