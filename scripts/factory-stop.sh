#!/usr/bin/env bash
# The stop button. Both halves of it.
#
#   bash scripts/factory-stop.sh          exit 0 = clear to dispatch, exit 1 = STOPPED
#
# The orchestrator is a bash script on the VPS at /opt/dark-factory/orchestrator.sh and
# it is deliberately not in this repository - it holds no state, and everything it reads
# is visible here as issues, PRs and labels. That had one bad consequence: the only off
# switch lived on a machine. Nothing in this repo could halt the factory, which meant the
# stop button was unreachable from anywhere except an SSH session.
#
# So the CHECK lives here, versioned and readable, and the orchestrator calls it first:
#
#   if ! bash /opt/dark-factory/repo/scripts/factory-stop.sh; then exit 0; fi
#
# Two mechanisms, on purpose, because they fail in different places.
#
#   1. A LOCAL kill file. Works with the network down, which is when you most want it.
#   2. A REMOTE label: any open issue tagged `factory:stop`. Reachable from a phone,
#      which is the entire reason it exists at 2am.
#
# Both are checked before anything else is read.

set -uo pipefail

# The repository whose issues carry the label: FACTORY_REPO if set, else the origin
# remote of the working copy. Not a hardcoded slug - this repository is a fork, and
# a stop label on the upstream's issues is not this factory's stop button. No
# repository at all counts as stopped, like every other unreadable state below.
# The lookup runs in FACTORY_WORKDIR if set, else in this script's own directory,
# which is inside the clone wherever the orchestrator's cwd happens to be.
repo_from_origin() {
  git -C "${FACTORY_WORKDIR:-$(dirname "${BASH_SOURCE[0]}")}" remote get-url origin 2>/dev/null \
    | sed -E 's#^(git@github\.com:|ssh://git@github\.com/|https://github\.com/)##; s#/$##; s#\.git$##'
}
REPO="${FACTORY_REPO:-$(repo_from_origin)}"

# Where the kill file lives by default. This used to be "$PWD/.factory-stop", which was
# a real hole: the repository above is found from this script's own directory precisely
# so the check works from any cwd, but the local half then looked somewhere else. The
# documented invocation is an absolute path with no cd, cron's cwd is $HOME, and every
# workflow node runs inside its own worktree - so `touch .factory-stop` at the repository
# root, which is what every document tells you to do, was invisible to all three.
#
# Resolved against the same root as the repository lookup. `--show-toplevel` on a
# worktree gives that worktree's root, so a run inside one can still be stopped by
# placing the file there; FACTORY_WORKDIR and FACTORY_KILL_FILE still override.
factory_root() {
  git -C "${FACTORY_WORKDIR:-$(dirname "${BASH_SOURCE[0]}")}" rev-parse --show-toplevel 2>/dev/null \
    || echo "${FACTORY_WORKDIR:-$(dirname "${BASH_SOURCE[0]}")/..}"
}
KILL_FILE="${FACTORY_KILL_FILE:-$(factory_root)/.factory-stop}"
STOP_LABEL="factory:stop"

if [ -z "$REPO" ]; then
  echo "STOPPED: cannot tell which repository to check (no FACTORY_REPO and no origin remote in ${FACTORY_WORKDIR:-.}), halting."
  exit 1
fi

# --- 1. the local half -------------------------------------------------------
if [ -f "$KILL_FILE" ]; then
  echo "STOPPED: $KILL_FILE present. Remove it to resume."
  [ -s "$KILL_FILE" ] && echo "reason: $(head -1 "$KILL_FILE")"
  exit 1
fi

# --- 2. the remote half, and it FAILS CLOSED ---------------------------------
# This is the polarity that matters and it is easy to get backwards. The obvious design
# is "the factory runs while a label is absent" - but an absent label cannot be told
# apart from an API call that failed to return it, so a network blip reads as "carry on"
# and the stop button works only while the network does.
#
# Inverted here: the label is something you ADD, and ANY error listing it counts as
# stopped. An unreadable stop button is a stop button you do not have.
if ! HITS=$(gh issue list -R "$REPO" --label "$STOP_LABEL" --state open \
              --json number,title --jq '.[] | "#\(.number) \(.title)"' 2>&1); then
  echo "STOPPED: cannot read the stop state from GitHub, halting: $HITS"
  exit 1
fi

if [ -n "$HITS" ]; then
  echo "STOPPED: an open issue in $REPO carries $STOP_LABEL"
  echo "$HITS" | sed 's/^/  /'
  exit 1
fi

echo "STOP_CHECK_OK: no kill file, no $STOP_LABEL issue in $REPO"
exit 0
