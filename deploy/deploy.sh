#!/usr/bin/env bash
# Blue/green deploy script for the Virtual Agent. Polls git, rebuilds the
# inactive colour, waits for its healthcheck, reads its health JSON, swaps the
# Caddy upstream with a graceful reload, proves the service answers through the
# public hostname, then stops the old colour. Safe to run when blue/green isn't
# set up yet — it detects and no-ops.
#
# Commands:
#   deploy.sh              deploy, the timer's job: pull, build, check, flip
#   deploy.sh flip         flip to the colour that is already built and healthy
#                          (the second half of a held/canary deploy)
#   deploy.sh rollback     start the stopped colour and route back to it
#   deploy.sh status       print what is live, what is held, what is deployed
#
# This file is the source of truth. The live VPS copy should be the thin
# wrapper deploy/host-wrapper.sh (installed as /opt/virtualagent/deploy.sh),
# which only locates the checkout and execs THIS file — so the script and the
# compose file, Dockerfile and Caddyfile it interprets always come from the same
# commit. A host still running a hand-mirrored copy is detected after the pull
# and warned about loudly, because the two drifting apart is how the 2026-04
# incident in deploy/README.md happened.
#
# The wiki is NOT deployed by this script. The image carries a default copy of
# virtualagent/resources/ so a container works unmounted, but production mounts
# the host's WIKI_DIR read-only over it and the service watches that folder: a
# document dropped there is answered from within seconds, with no build, no new
# image and no flip. What this script deploys is code.
set -euo pipefail

MODE="${1:-deploy}"

# Paths derive from where this script lives, so the same file works at
# /opt/virtualagent/deploy.sh (the layout deploy/README.md describes), at
# /opt/virtualagent/app/deploy/deploy.sh (the same file, run from the checkout
# by the wrapper) and at whatever older root a host still uses. Each can be
# overridden by environment.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# When this file is run from inside the checkout (<root>/app/deploy/deploy.sh),
# the root is two levels up, not the script's own directory: everything else —
# the env file, the state files — lives beside the checkout, not inside it.
if [ "$(basename "$HERE")" = "deploy" ] && [ -f "$HERE/docker-compose.yml" ]; then
    DEFAULT_ROOT="$(cd "$HERE/../.." && pwd)"
else
    DEFAULT_ROOT="$HERE"
fi
ROOT="${VIRTUALAGENT_ROOT:-$DEFAULT_ROOT}"
REPO="${VIRTUALAGENT_REPO:-$ROOT/app}"
ENV_FILE="${VIRTUALAGENT_ENV:-$ROOT/.env}"
COMPOSE_DIR="$REPO/deploy"
UPSTREAM_FILE="$COMPOSE_DIR/upstream.conf"
LOG="${VIRTUALAGENT_LOG:-/var/log/virtualagent-deploy.log}"
LOCK="${VIRTUALAGENT_LOCK:-/var/run/virtualagent-deploy.lock}"

# The commit of the last deploy that actually finished. Written only after the
# new colour is serving through Caddy, and read to answer "is there something to
# deploy" — because HEAD cannot answer it. A failed run used to leave the
# checkout advanced, so every later tick compared HEAD to origin/main, said "no
# changes" and exited 0: production parked on the previous code, the timer green,
# nobody told, until the next commit to main happened to fix it.
STATE_FILE="${VIRTUALAGENT_STATE:-$ROOT/.deployed-sha}"
# Presence of this file (or VIRTUALAGENT_NO_FLIP=1) means: build the new colour,
# check it, log it — and do not send traffic to it. The canary the documents
# describe, made executable. HELD_FILE records which commit is sitting in the
# inactive colour so the timer does not rebuild it every tick.
HOLD_FILE="${VIRTUALAGENT_HOLD:-$ROOT/.hold}"
HELD_FILE="${VIRTUALAGENT_HELD:-$ROOT/.held-sha}"
NO_FLIP="${VIRTUALAGENT_NO_FLIP:-0}"
# A command line run when a deploy fails. It gets the message as "$1".
# Empty means the only alert is the log plus systemd's own OnFailure= unit
# (deploy/virtualagent-deploy.service), which marks the unit failed.
ALERT_CMD="${VIRTUALAGENT_ALERT_CMD:-}"
# How many virtualagent-app:<sha> images to keep. One is built per deploy and
# the previous one is what a rollback needs; a small VPS cannot keep them all.
KEEP_IMAGES="${VIRTUALAGENT_KEEP_IMAGES:-5}"

SELF="$HERE/$(basename "${BASH_SOURCE[0]}")"
REPO_SELF="$COMPOSE_DIR/deploy.sh"

# The log is the record either way; a human running `rollback` or `status` at
# the console also wants to see it happen.
if [ -t 1 ]; then
    exec > >(tee -a "$LOG") 2>&1
else
    exec >>"$LOG" 2>&1
fi

log() { echo "[$(date -Iseconds)] $*"; }

compose() { docker compose --env-file "$ENV_FILE" "$@"; }

# Concurrency guard — flock on LOCK fd
exec 200>"$LOCK"
flock -n 200 || { log "another deploy running, exit"; exit 0; }

# ---- failure handling -------------------------------------------------------
# Set after a successful pull: the commit to put the checkout back on if this
# run does not finish. Without it a half-done run leaves HEAD ahead of what is
# actually serving and the next tick reports "no changes".
ROLLBACK_SHA=""
# Set to the colour Caddy was routing to, for exactly as long as upstream.conf
# names the other one but the swap is not yet proven. If we die in that window
# the file says green while Caddy serves blue, and the NEXT run computes
# ACTIVE/INACTIVE backwards and rebuilds over the colour that is serving.
UPSTREAM_RESTORE=""

alert() {
    local msg="$1"
    log "ALERT: $msg"
    if [ -n "$ALERT_CMD" ]; then
        # Run as a command line so the operator can configure anything —
        # `mail -s ... ops@example.com`, a curl to a webhook, `gh issue create`.
        # It sees the message as "$1". Its own failure must not mask ours.
        sh -c "$ALERT_CMD" virtualagent-alert "$msg" >/dev/null 2>&1 \
            || log "WARNING: VIRTUALAGENT_ALERT_CMD failed; the alert was logged only"
    fi
}

on_exit() {
    local code=$?
    trap - EXIT
    if [ "$code" -eq 0 ]; then
        exit 0
    fi
    log "FAILED (exit $code) in mode '$MODE'"

    if [ -n "$UPSTREAM_RESTORE" ]; then
        log "restoring the proxy upstream to app-$UPSTREAM_RESTORE (it is the colour actually serving)"
        echo "reverse_proxy app-$UPSTREAM_RESTORE:8000" > "$UPSTREAM_FILE" || true
        swap_caddy_upstream "app-$UPSTREAM_RESTORE:8000" \
            || log "ERROR: could not put Caddy back on app-$UPSTREAM_RESTORE — check it by hand NOW"
    fi

    if [ -n "$ROLLBACK_SHA" ]; then
        if git -C "$REPO" reset --hard --quiet "$ROLLBACK_SHA"; then
            log "rolled the checkout back to $ROLLBACK_SHA; the next run retries the same commit"
        else
            log "ERROR: could not reset $REPO to $ROLLBACK_SHA — the next run may report 'no changes' while nothing is deployed"
        fi
    fi

    alert "virtualagent deploy failed (mode '$MODE', exit $code) on $(hostname 2>/dev/null || echo host). See $LOG"
    exit "$code"
}
trap on_exit EXIT

# ---- helpers ----------------------------------------------------------------

# The public hostname, read from the env file without sourcing it: that file is
# secrets and this script never wants the rest of it in its environment.
host_from_env() {
    local line=""
    line=$(grep -E '^[[:space:]]*VIRTUALAGENT_HOST=' "$ENV_FILE" 2>/dev/null | tail -1 || true)
    line="${line#*=}"
    line="${line%\"}"; line="${line#\"}"
    line="${line%\'}"; line="${line#\'}"
    echo "$line" | tr -d '[:space:]'
}

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
            log "caddy reload returned non-zero — will verify and restart if needed"
        }

    # Verify reload took effect by reading the live admin-API config.
    sleep 1
    local live
    live=$(docker exec virtualagent-caddy wget -qO- --timeout=3 \
        http://127.0.0.1:2019/config/ 2>/dev/null || echo "")
    if echo "$live" | grep -q "$expected"; then
        log "caddy reload verified — routing to $expected"
        return 0
    fi

    log "WARNING: caddy reload did not apply (live config missing '$expected'). Forcing restart."
    compose restart caddy
    # Wait briefly for Caddy to come back. We're not strict here — if Caddy
    # itself is broken the next deploy attempt or a human will catch it.
    local i
    for i in $(seq 1 15); do
        if docker exec virtualagent-caddy wget -qO- --timeout=2 \
            http://127.0.0.1:2019/config/ 2>/dev/null | grep -q "$expected"; then
            log "caddy restart verified — routing to $expected"
            return 0
        fi
        sleep 1
    done
    log "ERROR: caddy still not routing to $expected after restart"
    return 1
}

# Wait for a colour's container healthcheck. 300 x 2s = 10 minutes: the image is
# already built by the time we get here, so this covers process start plus
# indexing the whole wiki through the embeddings endpoint, and no more.
wait_healthy() {
    local colour="$1" s="missing" i
    for i in $(seq 1 300); do
        s=$(docker inspect --format='{{.State.Health.Status}}' "virtualagent-app-$colour" 2>/dev/null || echo missing)
        if [ "$s" = "healthy" ]; then
            log "app-$colour is healthy"
            return 0
        fi
        sleep 2
    done
    log "ERROR: app-$colour never became healthy (last container status: $s)"
    return 1
}

# Read a colour's own /api/health and say out loud what it will serve. The
# container healthcheck already refuses a colour with no indexed documents, so
# this is mostly the record — but it is the record that tells a human, a week
# later, that the colour they flipped to knew 42 documents and reached the web
# through perplexity. Belt and braces on the document count: if the healthcheck
# is ever weakened again, this still stops the flip.
report_colour_health() {
    local colour="$1" json docs indexed provider
    json=$(docker exec "virtualagent-app-$colour" python -c \
        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).read().decode())" \
        2>/dev/null || echo "")
    if [ -z "$json" ]; then
        log "ERROR: could not read /api/health from app-$colour"
        return 1
    fi
    docs=$(echo "$json" | sed -n 's/.*"wiki_documents"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    indexed=$(echo "$json" | sed -n 's/.*"wiki_indexed_at"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    provider=$(echo "$json" | sed -n 's/.*"web_search"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    log "app-$colour health: wiki_documents=${docs:-none} wiki_indexed_at=${indexed:-none} web_search=${provider:-none}"
    if ! echo "${docs:-}" | grep -qE '^[0-9]+$' || [ "$docs" -lt 1 ]; then
        log "ERROR: app-$colour has indexed no wiki documents. It would answer every client from the web instead of from the wiki. Check WIKI_DIR in $ENV_FILE: it must be a folder this host has, containing .md or .txt files, readable by uid 1000."
        return 1
    fi
    return 0
}

# Prove the service answers THROUGH Caddy: the certificate, the compression, the
# proxy and the app, over the public hostname, as a phone would reach it. A
# colour can pass its own healthcheck on the internal network and still be wrong
# for clients. Two requests, neither of which calls a model: /api/health, then
# creating and deleting a session (which exercises the auth path and returns the
# voice locale the app needs).
smoke_through_caddy() {
    local host="$1" json sess sid tok
    if [ -z "$host" ]; then
        log "WARNING: no VIRTUALAGENT_HOST found in $ENV_FILE — skipping the public smoke test"
        return 0
    fi
    if ! command -v curl >/dev/null 2>&1; then
        log "WARNING: curl is not installed on this host — skipping the public smoke test. Install it: the flip is unverified without it."
        return 0
    fi

    json=$(curl -fsS --max-time 20 "https://$host/api/health" 2>/dev/null || echo "")
    if [ -z "$json" ]; then
        log "ERROR: GET https://$host/api/health failed through Caddy (TLS, certificate or proxy)"
        return 1
    fi
    if ! echo "$json" | grep -qE '"wiki_documents"[[:space:]]*:[[:space:]]*[1-9]'; then
        log "ERROR: https://$host/api/health reports no indexed wiki documents: $json"
        return 1
    fi

    sess=$(curl -fsS --max-time 20 -X POST "https://$host/api/sessions" \
        -H 'Content-Type: application/json' \
        -d '{"client_id":"deploy-smoke"}' 2>/dev/null || echo "")
    if ! echo "$sess" | grep -q '"voice_locale"'; then
        log "ERROR: POST https://$host/api/sessions did not return a greeting with a voice_locale: ${sess:-<no response>}"
        return 1
    fi
    sid=$(echo "$sess" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    tok=$(echo "$sess" | sed -n 's/.*"session_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    if [ -n "$sid" ] && [ -n "$tok" ]; then
        curl -fsS --max-time 10 -X DELETE "https://$host/api/sessions/$sid" \
            -H "Authorization: Bearer $tok" >/dev/null 2>&1 || true
    fi
    log "public smoke test passed through https://$host (health + session)"
    return 0
}

# Point Caddy at $target and, once that is proven, stop $previous.
# restore=restore -> if anything below fails, the exit trap puts Caddy back on
# $previous, which is still running. restore=keep -> we are already rolling
# back; $previous is the colour we are running away from and must not return.
flip_to() {
    local target="$1" previous="$2" restore="${3:-restore}"

    if [ "$restore" = "restore" ]; then
        UPSTREAM_RESTORE="$previous"
    fi
    echo "reverse_proxy app-$target:8000" > "$UPSTREAM_FILE"
    swap_caddy_upstream "app-$target:8000"

    # Give in-flight requests a moment to drain from the old upstream.
    sleep 5

    smoke_through_caddy "$(host_from_env)"

    # Committed: the new colour is answering real requests through the proxy.
    UPSTREAM_RESTORE=""
    compose stop "app-$previous" || true
    log "live colour is now app-$target (was app-$previous)"
}

# One image is built per deployed commit (see docker-compose.yml), so the
# previous commit's image survives for a rollback. Keep the newest few and try
# to delete the rest; `docker image rm` refuses an image a container still
# references, which is exactly the protection we want, so failures are ignored.
prune_old_images() {
    local tag
    docker images --filter=reference='virtualagent-app:*' --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
        | tail -n "+$((KEEP_IMAGES + 1))" \
        | while read -r tag; do
              if docker image rm "$tag" >/dev/null 2>&1; then
                  log "removed old image $tag"
              fi
          done
}

# The host copy of this script and the repository copy drifting apart is a real
# incident, not a theory: deploy/README.md documents the day a stale host copy
# read a compose failure as "not yet configured" and exited 0 with nothing
# deployed. The wrapper (deploy/host-wrapper.sh) makes this impossible; until it
# is installed, say so every run.
warn_if_host_copy_stale() {
    local mine theirs
    [ "$SELF" = "$REPO_SELF" ] && return 0
    [ -f "$REPO_SELF" ] || return 0
    mine=$(sha256sum "$SELF" 2>/dev/null | cut -d' ' -f1 || echo a)
    theirs=$(sha256sum "$REPO_SELF" 2>/dev/null | cut -d' ' -f1 || echo b)
    if [ "$mine" != "$theirs" ]; then
        log "WARNING: $SELF is NOT the script in the checkout ($REPO_SELF). It is interpreting a compose file and Dockerfile from a different commit than itself. Install deploy/host-wrapper.sh as $SELF once and this cannot happen again (see deploy/README.md)."
        alert "virtualagent: the host deploy.sh is stale (differs from $REPO_SELF)"
    fi
}

# Which colour Caddy is routing to, from the file Caddy imports. The `|| true`
# is not decoration: under `set -o pipefail` a grep that matches nothing — or a
# `head` that closes the pipe first — makes the whole substitution non-zero, and
# `ACTIVE=$(active_colour)` would then kill the script through `set -e` instead
# of returning the empty string every caller already checks for.
active_colour() {
    local found
    found=$(grep -oE 'app-(blue|green)' "$UPSTREAM_FILE" 2>/dev/null | head -1 || true)
    echo "${found#app-}"
}

other_colour() {
    if [ "$1" = "blue" ]; then echo green; else echo blue; fi
}

# An upstream.conf that names neither colour is not a situation to guess at: the
# guess would be "blue", and if green is the one actually serving the next build
# lands on top of it. Stop instead.
require_active() {
    if [ "$1" != "blue" ] && [ "$1" != "green" ]; then
        log "ERROR: $UPSTREAM_FILE names neither app-blue nor app-green. Repair it by hand (see upstream.conf.example, and check which container is running) before deploying."
        exit 1
    fi
}

# ---- pre-flight, every mode -------------------------------------------------

log "---- $MODE start ----"

if [ ! -d "$REPO" ]; then
    log "ERROR: no directory at $REPO (set VIRTUALAGENT_ROOT or VIRTUALAGENT_REPO)"
    exit 1
fi
# stderr is the log (exec above), so git's own reason lands on the line before this one.
if ! git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null; then
    log "ERROR: git refused $REPO - its reason is on the line above. A checkout owned by another user needs: git config --global --add safe.directory $REPO (for the user running this script)"
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    log "ERROR: no env file at $ENV_FILE (set VIRTUALAGENT_ENV)"
    exit 1
fi
# Pre-flight against the checkout AS IT IS NOW, before anything is pulled, so a
# host whose env file lacks a required variable is told so on every run and
# nothing is half-done. A commit that itself adds a required variable gets past
# this one and is caught by the second check after the pull, which rolls the
# pull back for the same reason.
if ! compose -f "$COMPOSE_DIR/docker-compose.yml" config >/dev/null; then
    log "ERROR: docker compose config failed against $ENV_FILE - a required variable is missing (see deploy/.env.example). Nothing was pulled."
    exit 1
fi

# ---- flip / rollback / status: no pull, no build ----------------------------

case "$MODE" in
    status)
        if [ -f "$UPSTREAM_FILE" ]; then
            ACTIVE=$(active_colour)
            log "live colour: app-${ACTIVE:-unknown} (per $UPSTREAM_FILE)"
            report_colour_health "$ACTIVE" || true
        else
            log "no $UPSTREAM_FILE — blue/green has never been deployed here"
        fi
        log "checkout HEAD: $(git -C "$REPO" rev-parse HEAD)"
        if [ -f "$STATE_FILE" ]; then
            log "last successful deploy: $(cat "$STATE_FILE")"
        else
            log "last successful deploy: unknown (no $STATE_FILE yet)"
        fi
        if [ -f "$HOLD_FILE" ]; then
            log "HOLD IS IN PLACE ($HOLD_FILE): new commits are built and checked but NOT flipped live"
            [ -f "$HELD_FILE" ] && log "held commit waiting in the inactive colour: $(cat "$HELD_FILE")"
        else
            log "no hold: a commit to main goes live on the next timer tick"
        fi
        docker ps -a --filter 'name=virtualagent-' --format '{{.Names}}: {{.Status}}' 2>/dev/null || true
        exit 0
        ;;

    flip)
        # The second half of a held deploy: the inactive colour is already built
        # and healthy, a human has looked at it, now send traffic to it.
        if [ ! -f "$UPSTREAM_FILE" ]; then
            log "ERROR: no $UPSTREAM_FILE — there is nothing to flip between"
            exit 1
        fi
        ACTIVE=$(active_colour)
        require_active "$ACTIVE"
        TARGET=$(other_colour "$ACTIVE")
        log "flipping app-$ACTIVE -> app-$TARGET on request"
        cd "$COMPOSE_DIR"
        wait_healthy "$TARGET"
        report_colour_health "$TARGET"
        flip_to "$TARGET" "$ACTIVE" restore
        git -C "$REPO" rev-parse HEAD > "$STATE_FILE"
        rm -f "$HELD_FILE"
        log "flip complete: $ACTIVE -> $TARGET at $(cat "$STATE_FILE")"
        exit 0
        ;;

    rollback)
        # Undo the last flip. `compose start`, never `compose up`: up would
        # recreate the container from the image the compose file names today and
        # destroy the very thing we are rolling back to. The per-commit image
        # tags exist so this container's image is still on disk.
        if [ ! -f "$UPSTREAM_FILE" ]; then
            log "ERROR: no $UPSTREAM_FILE — there is nothing to roll back to"
            exit 1
        fi
        ACTIVE=$(active_colour)
        require_active "$ACTIVE"
        TARGET=$(other_colour "$ACTIVE")
        if ! docker inspect "virtualagent-app-$TARGET" >/dev/null 2>&1; then
            log "ERROR: there is no virtualagent-app-$TARGET container to roll back to. Recreate it from a known-good image by hand: docker images --filter=reference='virtualagent-app:*'"
            exit 1
        fi
        log "rolling back app-$ACTIVE -> app-$TARGET"
        cd "$COMPOSE_DIR"
        compose start "app-$TARGET"
        wait_healthy "$TARGET"
        report_colour_health "$TARGET"
        # keep: if this fails we do NOT want Caddy sent back to the colour we are
        # running away from. It stays on the rollback target and a human is told.
        flip_to "$TARGET" "$ACTIVE" keep
        log "rollback complete: app-$TARGET is live. $STATE_FILE still names the commit that was rolled back, so the timer will not redeploy it; the next commit to main will deploy normally. Create $HOLD_FILE if you want to stop that too."
        alert "virtualagent: rolled back to app-$TARGET by hand"
        exit 0
        ;;

    deploy) : ;;

    *)
        log "ERROR: unknown command '$MODE'. Use: deploy | flip | rollback | status"
        exit 1
        ;;
esac

# ---- deploy: is there anything to do? ---------------------------------------

cd "$REPO"
git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse @{u})
DEPLOYED=""
if [ -f "$STATE_FILE" ]; then
    DEPLOYED=$(tr -d '[:space:]' < "$STATE_FILE")
fi

# "Nothing to do" means the remote commit is the one that is actually SERVING,
# not merely the one the checkout happens to be on. On a host that has never
# recorded a successful deploy (no state file yet) fall back to the old rule, so
# a fresh install does not redeploy on every tick.
if [ "$LOCAL" = "$REMOTE" ] && { [ -z "$DEPLOYED" ] || [ "$DEPLOYED" = "$REMOTE" ]; }; then
    log "no changes (HEAD=$LOCAL)"
    exit 0
fi

HELD=""
if [ -f "$HELD_FILE" ]; then
    HELD=$(tr -d '[:space:]' < "$HELD_FILE")
fi
if [ -f "$HOLD_FILE" ] || [ "$NO_FLIP" = "1" ]; then
    if [ "$HELD" = "$REMOTE" ]; then
        log "held: $REMOTE is built and healthy in the inactive colour and is NOT live. Remove $HOLD_FILE and run '$SELF flip' to promote it."
        exit 0
    fi
fi

if [ "$LOCAL" != "$REMOTE" ]; then
    log "changes: $LOCAL -> $REMOTE, pulling"
    git pull --ff-only --quiet
    # From here on, a failure puts the checkout back: see on_exit.
    ROLLBACK_SHA="$LOCAL"
else
    log "checkout is already at $REMOTE but the last successful deploy was ${DEPLOYED:-unknown} — redeploying"
fi

warn_if_host_copy_stale

cd "$COMPOSE_DIR"

# The compose file refuses to render without VIRTUALAGENT_HOST and
# LETSENCRYPT_EMAIL in the env file. Check that FIRST and fail loudly: the
# blue/green gate below would otherwise read a failed `config` as "not yet
# configured" and exit 0 with nothing deployed.
if ! compose config >/dev/null; then
    log "ERROR: docker compose config failed - a required variable is missing from $ENV_FILE (see deploy/.env.example). The exit handler puts the checkout back so the next run retries this commit."
    exit 1
fi

# Caddy reads VIRTUALAGENT_HOST and LETSENCRYPT_EMAIL from its own container
# environment, and `caddy reload` re-reads the Caddyfile but never that
# environment. A container created before those variables existed would fail
# the reload below, and the restart fallback would then crash-loop it on the
# new Caddyfile: a full outage. `up -d` recreates the container only when its
# config changed (a few seconds, once) and is a no-op otherwise.
compose up -d --no-deps caddy

# Gate: require blue/green services + upstream.conf to exist before deploying
if ! compose config --services 2>/dev/null | grep -q '^app-blue$'; then
    log "blue/green not yet configured in compose — skipping. Reload caddy only if its config changed (safe, no app dependency)."
    compose up -d --no-deps caddy || true
    exit 0
fi

# One image per commit, so the colour that is still serving keeps an image of
# its own and `deploy.sh rollback` has something to roll back TO. Exported for
# every compose call below (docker-compose.yml reads it).
VIRTUALAGENT_IMAGE_TAG="$(git -C "$REPO" rev-parse --short HEAD)"
export VIRTUALAGENT_IMAGE_TAG
log "building image virtualagent-app:$VIRTUALAGENT_IMAGE_TAG"

if [ ! -f "$UPSTREAM_FILE" ]; then
    log "upstream.conf missing — initial deploy. Starting app-blue."
    echo 'reverse_proxy app-blue:8000' > "$UPSTREAM_FILE"
    compose up -d --build app-blue
    # Until app-blue is actually healthy, upstream.conf naming it is a lie that
    # would make the NEXT run think blue/green is established and deploy green.
    # Take the file away again if this first colour never comes up.
    if ! wait_healthy blue || ! report_colour_health blue; then
        rm -f "$UPSTREAM_FILE"
        log "aborting the initial deploy; removed $UPSTREAM_FILE so the next run starts it over"
        exit 1
    fi
    swap_caddy_upstream "app-blue:8000"
    # Non-fatal here, unlike on a flip: this is the very first request to the
    # hostname, so it is also the one that makes Caddy fetch the certificate.
    # A DNS record that has not propagated yet is a reason to look, not a reason
    # to tear down a colour that is demonstrably healthy.
    smoke_through_caddy "$(host_from_env)" \
        || log "WARNING: the public smoke test did not pass on this first deploy — check DNS and the Let's Encrypt certificate, then run '$SELF status'"
    git -C "$REPO" rev-parse HEAD > "$STATE_FILE"
    log "initial deploy complete: app-blue live at $(cat "$STATE_FILE")"
    exit 0
fi

# ---- standard blue/green swap -----------------------------------------------

ACTIVE=$(active_colour)
require_active "$ACTIVE"
INACTIVE=$(other_colour "$ACTIVE")
log "active=$ACTIVE, deploying to $INACTIVE"

# Build + start inactive
compose up -d --build --no-deps "app-$INACTIVE"

if ! wait_healthy "$INACTIVE"; then
    log "aborting, keeping app-$ACTIVE live"
    compose stop "app-$INACTIVE" || true
    exit 1
fi

# What did it actually index, and how will it reach the web? On the record,
# before any traffic reaches it.
if ! report_colour_health "$INACTIVE"; then
    log "aborting, keeping app-$ACTIVE live"
    compose stop "app-$INACTIVE" || true
    exit 1
fi

# The hold: built, healthy, checked, NOT live. This is the canary path the
# documents describe — the new colour runs the new commit (and, if CHAT_MODEL is
# set for a canary, the new model) with no client traffic until a human says so.
if [ -f "$HOLD_FILE" ] || [ "$NO_FLIP" = "1" ]; then
    echo "$REMOTE" > "$HELD_FILE"
    log "HOLD: app-$INACTIVE is built, healthy and NOT receiving traffic; Caddy still routes to app-$ACTIVE."
    log "HOLD: reach it from this host with: docker exec virtualagent-app-$INACTIVE curl -s localhost:8000/api/health"
    log "HOLD: to promote it, remove $HOLD_FILE and run '$SELF flip'. To discard it, leave the hold in place; the next commit rebuilds the colour."
    exit 0
fi

flip_to "$INACTIVE" "$ACTIVE" restore

git -C "$REPO" rev-parse HEAD > "$STATE_FILE"
rm -f "$HELD_FILE"
prune_old_images || true
log "deploy complete: $ACTIVE -> $INACTIVE at $REMOTE (image virtualagent-app:$VIRTUALAGENT_IMAGE_TAG)"
