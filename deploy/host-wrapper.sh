#!/usr/bin/env bash
# The ONLY file that is copied onto the deploy host by hand.
#
# Install it as /opt/virtualagent/deploy.sh (see deploy/README.md step 8). It
# does one thing: work out where the checkout is and run the deploy script that
# lives inside it.
#
# Why it exists. The host used to carry a hand-mirrored copy of deploy.sh, while
# the docker-compose.yml, Dockerfile and Caddyfile that script interprets came
# from git. Every change to deploy.sh was a two-place edit that nothing reminded
# anyone of, and when the two drifted the failure was silent: deploy/README.md
# records the day a stale host copy read a compose-config failure as "blue/green
# not yet configured" and exited 0 with nothing deployed. This wrapper has no
# opinions to go stale — it holds no deploy logic at all, so the script and the
# files it interprets are always from the same commit.
#
# It deliberately does NOT pull. The real script checks the stack against the
# env file BEFORE pulling and puts the checkout back if the run fails; pulling
# out here would take that decision away from it. The consequence is one tick of
# lag on a change to deploy.sh itself: run N pulls the new script, run N+1 is
# the first to execute it. That is the entire skew this design allows, and it
# closes by itself.
#
# Every argument is passed through, so `/opt/virtualagent/deploy.sh rollback`
# and `/opt/virtualagent/deploy.sh status` work the same as the timer's bare
# invocation.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${VIRTUALAGENT_ROOT:-$HERE}"
REPO="${VIRTUALAGENT_REPO:-$ROOT/app}"
TARGET="$REPO/deploy/deploy.sh"

# The real script derives its root from its own location, and from inside the
# checkout that would be the checkout, not the host root where .env and the
# state files live. Tell it explicitly.
export VIRTUALAGENT_ROOT="$ROOT"
export VIRTUALAGENT_REPO="$REPO"

if [ ! -f "$TARGET" ]; then
    echo "[$(date -Iseconds)] ERROR: no deploy script at $TARGET. Is the checkout at $REPO? (set VIRTUALAGENT_ROOT or VIRTUALAGENT_REPO)" >&2
    exit 1
fi

# `bash "$TARGET"`, not `"$TARGET"`: a checkout made by a user whose umask or
# filesystem dropped the execute bit would otherwise stop every deploy.
exec bash "$TARGET" "$@"
