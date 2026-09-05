#!/usr/bin/env python3
"""THE RATCHET'S TEETH. Assert a gate log against `.factory/locks/floor.json`.

    python harness/ratchet.py gate.log                    observed >= floor, every key
    python harness/ratchet.py gate.log --base origin/main   ... and floor(head) >= floor(base)

Until 2026-09-04 nothing read `floor.json`. Its own header said "the gate asserts
observed >= floor", and no line of code did. A floor nobody checks is a number in a file,
and the whole point of the file was that the gap between observed and floor is exactly the
number of assertions that can be deleted with the gate still green. This script is the
check the header promised.

What it reads:

  * The gate log - the stdout of `python harness/ci.py`. Every rung prints a positive
    marker with a count (`UNIT_PASSED tests=N`, `E2E_PASSED steps=N`,
    `HOLDOUT_PASSED scenarios=S assertions=A`, `MUTATIONS_TOTAL=N`), and this script
    refuses a log in which a floored marker is ABSENT: a rung that did not run is not a
    rung that passed.
  * `harness/.run/static-checks` - the count `harness/static.py` writes when it succeeds.
    `ci.py` swallows a passing rung's output, so the count cannot come from the log; it
    comes from the one file the rung leaves behind. Absent file, failed floor.
  * With `--base REF`, the floor file at that git ref, so a PR cannot lower a floor and
    delete the assertions it covered in the same commit. Lowering is a human decision and
    it is made on `main`, in the open.

Emits `RATCHET_OK floors=N` and exits 0, or names every floor that failed and exits 1.
Stdlib only: this runs after the gate, under whatever `python` the harness has.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FLOOR = ROOT / ".factory" / "locks" / "floor.json"
STATIC_COUNT = HERE / ".run" / "static-checks"

# floor key -> (marker regex with one group, human name)
MARKERS: dict[str, tuple[str, str]] = {
    "unit_tests": (r"^UNIT_PASSED tests=(\d+)", "unit tests"),
    "e2e_steps": (r"^E2E_PASSED steps=(\d+)", "journey steps"),
    "holdout_assertions": (r"^HOLDOUT_PASSED scenarios=\d+ assertions=(\d+)", "holdout assertions"),
    "mutations_total": (r"^MUTATIONS_TOTAL=(\d+)", "mutations"),
}


def floors_at(ref: str | None) -> dict[str, int]:
    if ref is None:
        raw = FLOOR.read_text(encoding="utf-8")
    else:
        p = subprocess.run(["git", "show", f"{ref}:.factory/locks/floor.json"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8")
        if p.returncode != 0:
            raise SystemExit(f"RATCHET_ERROR cannot read floor.json at {ref}: {p.stderr.strip()}")
        raw = p.stdout
    data = json.loads(raw)
    return {k: int(v) for k, v in data.items() if not k.startswith("_") and isinstance(v, int)}


def observed(log: str) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for key, (pattern, _) in MARKERS.items():
        m = re.search(pattern, log, re.MULTILINE)
        out[key] = int(m.group(1)) if m else None
    if STATIC_COUNT.exists():
        try:
            out["static_checks"] = int(STATIC_COUNT.read_text(encoding="utf-8").strip())
        except ValueError:
            out["static_checks"] = None
    else:
        out["static_checks"] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("gate_log", help="stdout of `python harness/ci.py`")
    ap.add_argument("--base", help="git ref whose floor.json this one may not fall below")
    args = ap.parse_args()

    log = Path(args.gate_log).read_text(encoding="utf-8", errors="replace")
    if not re.search(r"^GATE_OK mode=full", log, re.MULTILINE):
        print("RATCHET_FAILED the log does not end in GATE_OK mode=full; there is nothing to "
              "ratchet against a run that did not pass", flush=True)
        return 1

    floors = floors_at(None)
    seen = observed(log)
    failures: list[str] = []

    for key, floor in sorted(floors.items()):
        got = seen.get(key)
        name = MARKERS.get(key, ("", key))[1] or key
        if got is None:
            failures.append(f"{key}: floor {floor}, but no {name} count was observed - the rung "
                            f"did not run or stopped printing its marker")
        elif got < floor:
            failures.append(f"{key}: observed {got} < floor {floor} ({floor - got} {name} gone)")
        else:
            print(f"  ok  {key:<20} observed={got:<5} floor={floor}", flush=True)

    if args.base:
        base = floors_at(args.base)
        for key, floor in sorted(base.items()):
            head = floors.get(key)
            if head is None:
                failures.append(f"{key}: floor {floor} at {args.base} was removed")
            elif head < floor:
                failures.append(f"{key}: floor lowered {floor} -> {head} relative to {args.base}. "
                                f"Lowering a floor is a human decision made on main, not in a PR")

    if failures:
        for f in failures:
            print(f"  RATCHET_FAIL  {f}", flush=True)
        print(f"RATCHET_FAILED floors={len(floors)} failures={len(failures)}", flush=True)
        return 1
    print(f"RATCHET_OK floors={len(floors)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
