#!/usr/bin/env python3
"""The static rung: the Python service, plus what can honestly be checked of the iOS app.

`ci.py` runs one command per rung; the split lives here so the ladder stays the ladder.

    python harness/static.py

The service: ruff (lint), ruff (format), mypy, all under the backend's own environment so
the versions are the pinned ones. The app: `static_ios.py`, which parses the XcodeGen spec
and the Info.plist and sanity-checks every Swift file - NOT a compile. There is no Swift
toolchain on the machines this gate runs on, and a check that pretends otherwise would be
a smaller check wearing a bigger check's name. The count printed at the end is of checks
that RAN; four tools silently becoming three is the shape of every bug this repo has
filed against its own gate.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "app" / "backend"
UV = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")

CHECKS = [
    ("ruff-lint", BACKEND, [UV, "run", "ruff", "check", "."]),
    ("ruff-format", BACKEND, [UV, "run", "ruff", "format", "--check", "."]),
    ("mypy", BACKEND, [UV, "run", "mypy", "."]),
    ("ios-manifests", BACKEND, [UV, "run", "python", str(ROOT / "harness" / "static_ios.py")]),
]


def main() -> int:
    failed: list[str] = []
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
        if p.returncode != 0:
            print(f"--- {label} ---", flush=True)
            print(((p.stdout or "") + (p.stderr or "")).strip()[-2000:], flush=True)
            failed.append(label)
        else:
            print(f"  ok  {label}", flush=True)

    if failed:
        print(f"STATIC_FAILED checks={','.join(failed)}", flush=True)
        return 1
    # ci.py swallows a passing rung's output, so the count the ratchet needs cannot
    # come from the log. Leave it in the one place a rung may: harness/.run.
    run_dir = ROOT / "harness" / ".run"
    run_dir.mkdir(exist_ok=True)
    (run_dir / "static-checks").write_text(str(ran), encoding="utf-8")
    print(f"STATIC_OK checks={ran}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
