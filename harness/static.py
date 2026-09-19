#!/usr/bin/env python3
"""The static rung: the Python service, plus what can honestly be checked of the iOS app.

`ci.py` runs one command per rung; the split lives here so the ladder stays the ladder.

    python harness/static.py

The service: ruff (lint), ruff (format), mypy, all under the backend's own environment so
the versions are the pinned ones. The wiki import tool (`tools/wiki`): ruff lint and format
under its own environment. The app: `static_ios.py`, which parses the XcodeGen spec
and the Info.plist, sanity-checks every Swift file and enforces the four-language rule on
user-facing strings - NOT a compile. There is no Swift toolchain on the machines this gate
runs on, and a check that pretends otherwise would be a smaller check wearing a bigger
check's name. And `static_contract.py`, which compares the wire contract across its four
definitions, because `docs/API.md` has two consumers and nothing mechanical read both.
The count printed at the end is of checks that RAN; four tools silently becoming three is
the shape of every bug this repo has filed against its own gate.

EVERY `uv run` HERE CARRIES `--all-extras`. ruff, mypy and pytest live in each project's
`[project.optional-dependencies].dev`, which a plain `uv run` never installs: in a fresh
worktree - every Archon worktree on the VPS - the first rung died on
`Failed to spawn: ruff ... program not found`, ci.py printed `GATE_FAILED: static`, and
every PR was routed to a fix agent for a harness defect it is not allowed to touch. It
passed here only because the venvs had been hand-synced. The extras are part of the
command, not part of the environment somebody remembered to prepare.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    # A red rung's detail can contain Arabic (the product speaks it). Under a file
    # redirect on Windows stdout is cp1252 and the print raises UnicodeEncodeError,
    # which loses the failure before it can be named.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "app" / "backend"
TOOLS = ROOT / "tools" / "wiki"
UV = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")

# A positive marker a sub-check prints for itself, so ci.py can lift it into the gate log
# and the ratchet can floor it. `STATIC_OK checks=N` is this script's own and matches too.
MARKER = re.compile(r"^[A-Z][A-Z0-9_]*_(?:OK|SKIPPED|ABSENT)\b")

CHECKS = [
    ("ruff-lint", BACKEND, [UV, "run", "--all-extras", "ruff", "check", "."]),
    ("ruff-format", BACKEND, [UV, "run", "--all-extras", "ruff", "format", "--check", "."]),
    ("mypy", BACKEND, [UV, "run", "--all-extras", "mypy", "."]),
    ("ios-manifests", BACKEND,
     [UV, "run", "--all-extras", "python", str(ROOT / "harness" / "static_ios.py")]),
    ("api-contract", BACKEND,
     [UV, "run", "--all-extras", "python", str(ROOT / "harness" / "static_contract.py")]),
    ("ruff-lint-tools", TOOLS, [UV, "run", "--all-extras", "ruff", "check", "."]),
    ("ruff-format-tools", TOOLS, [UV, "run", "--all-extras", "ruff", "format", "--check", "."]),
]


def main() -> int:
    failed: list[str] = []
    markers: list[str] = []
    ran = 0
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)

    for label, cwd, argv in CHECKS:
        if not cwd.exists():
            print(f"STATIC_MISSING {label}: {cwd} does not exist", flush=True)
            failed.append(label)
            continue
        try:
            p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600)
        except FileNotFoundError:
            print(f"STATIC_MISSING {label}: {argv[0]} is not on PATH", flush=True)
            failed.append(label)
            continue
        except subprocess.TimeoutExpired:
            print(f"STATIC_TIMEOUT {label} after 600s", flush=True)
            failed.append(label)
            continue

        ran += 1
        out = (p.stdout or "") + (p.stderr or "")
        if p.returncode != 0:
            print(f"--- {label} ---", flush=True)
            print(out.strip()[-2000:], flush=True)
            failed.append(label)
        else:
            print(f"  ok  {label}", flush=True)
            markers.extend(line.strip() for line in out.splitlines()
                           if MARKER.match(line.strip()))

    if failed:
        print(f"STATIC_FAILED checks={','.join(failed)}", flush=True)
        return 1

    # The counts a sub-check owns (IOS_MANIFESTS_OK, PHRASES_OK, CONTRACT_OK) only exist
    # inside that child's stdout, which is swallowed when it passes. Lift them here so the
    # gate log the ratchet reads carries them.
    for line in markers:
        print(line, flush=True)

    # Belt and braces for the static count: ci.py now echoes `STATIC_OK checks=N` into the
    # gate log, and this file is what the ratchet falls back to when it reads a log that
    # predates that.
    run_dir = ROOT / "harness" / ".run"
    run_dir.mkdir(exist_ok=True)
    (run_dir / "static-checks").write_text(str(ran), encoding="utf-8")
    print(f"STATIC_OK checks={ran}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
