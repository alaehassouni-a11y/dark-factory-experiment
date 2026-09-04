#!/usr/bin/env python3
"""The unit rung, with a real count.

    python harness/unit.py

Runs pytest under the backend's own environment and parses the count, because `ci.py`
refuses a run that reports zero tests - a suite that discovered nothing exits 0 and looks
perfect. The iOS app's XCTest target is NOT run here: there is no Swift toolchain on the
gate's machines, and the count below is only the service's. Saying so is the point.
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
UV = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")

PATTERN = re.compile(r"(\d+) passed")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def main() -> int:
    if not BACKEND.exists():
        print(f"UNIT_MISSING backend: {BACKEND} does not exist", flush=True)
        return 1
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    try:
        p = subprocess.run([UV, "run", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
                           cwd=BACKEND, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
    except FileNotFoundError:
        print(f"UNIT_MISSING backend: {UV} is not on PATH", flush=True)
        return 1
    except subprocess.TimeoutExpired:
        print("UNIT_TIMEOUT backend after 900s", flush=True)
        return 1

    out = ANSI.sub("", (p.stdout or "") + (p.stderr or ""))
    if p.returncode != 0:
        print(out.strip()[-3000:], flush=True)
        print("UNIT_FAILED half=backend", flush=True)
        return 1
    m = PATTERN.search(out)
    count = int(m.group(1)) if m else 0
    if count == 0:
        print("UNIT_ERROR backend: exited 0 but reported 0 tests. Either the suite ran nothing, "
              "or the pattern no longer matches this runner's output.", flush=True)
        return 1
    print(f"UNIT_PASSED tests={count} backend={count} ios=not-run", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
