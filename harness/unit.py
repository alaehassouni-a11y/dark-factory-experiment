#!/usr/bin/env python3
"""The unit rung, with a real count.

    python harness/unit.py

Runs pytest under the backend's own environment and under the wiki import tool's, and
parses both counts, because `ci.py` refuses a run that reports zero tests - a suite that
discovered nothing exits 0 and looks perfect. The iOS app's XCTest target is NOT run here:
there is no Swift toolchain on the gate's machines, and the counts below are the service's
and the tool's. Saying so is the point.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "app" / "backend"
TOOLS = ROOT / "tools" / "wiki"
UV = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")

PATTERN = re.compile(r"(\d+) passed")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def run_suite(label: str, cwd: Path) -> int | None:
    """Passed-test count for one pytest project, or None when it failed or ran nothing."""
    if not cwd.exists():
        print(f"UNIT_MISSING {label}: {cwd} does not exist", flush=True)
        return None
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    try:
        p = subprocess.run([UV, "run", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
                           cwd=cwd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
    except FileNotFoundError:
        print(f"UNIT_MISSING {label}: {UV} is not on PATH", flush=True)
        return None
    except subprocess.TimeoutExpired:
        print(f"UNIT_TIMEOUT {label} after 900s", flush=True)
        return None

    out = ANSI.sub("", (p.stdout or "") + (p.stderr or ""))
    if p.returncode != 0:
        print(out.strip()[-3000:], flush=True)
        print(f"UNIT_FAILED half={label}", flush=True)
        return None
    m = PATTERN.search(out)
    count = int(m.group(1)) if m else 0
    if count == 0:
        print(f"UNIT_ERROR {label}: exited 0 but reported 0 tests. Either the suite ran nothing, "
              "or the pattern no longer matches this runner's output.", flush=True)
        return None
    return count


def main() -> int:
    backend = run_suite("backend", BACKEND)
    if backend is None:
        return 1
    tools = run_suite("tools", TOOLS)
    if tools is None:
        return 1
    print(f"UNIT_PASSED tests={backend + tools} backend={backend} tools={tools} ios=not-run", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
