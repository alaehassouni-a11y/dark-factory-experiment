#!/usr/bin/env python3
"""THE RATCHET'S TEETH. Assert a gate log against `.factory/locks/floor.json`.

    python harness/ratchet.py gate.log                     observed >= floor, every key
    python harness/ratchet.py gate.log --base origin/main   ... and floor(head) >= floor(merge-base)

Until 2026-09-04 nothing read `floor.json`. Its own header said "the gate asserts
observed >= floor", and no line of code did. A floor nobody checks is a number in a file,
and the whole point of the file was that the gap between observed and floor is exactly the
number of assertions that can be deleted with the gate still green. This script is the
check the header promised. `harness/ci.py` runs it as the last rung of a full run, so
`GATE_OK mode=full` and `RATCHET_OK` are one command again.

What it reads:

  * The gate log - the stdout of `python harness/ci.py`. Every rung prints a positive
    marker with a count (`STATIC_OK checks=N`, `UNIT_PASSED tests=N`, `E2E_PASSED steps=N`,
    `HOLDOUT_PASSED scenarios=S assertions=A`, `MUTATIONS_TOTAL=N`,
    `MUTATIONS_ABOVE_LINE=N`, `CONTRACT_OK events=E fields=F`, `PHRASES_OK cases=N`), and
    this script refuses a log in which a floored marker is ABSENT: a rung that did not
    run is not a rung that passed.
  * `harness/.run/static-checks` - the count `harness/static.py` leaves behind, used only
    when the log carries no `STATIC_OK checks=`. Belt and braces, no longer the only copy.
  * With `--base REF`, the floor file at the MERGE BASE of REF and HEAD.

WHY THE MERGE BASE, and not the tip of the base branch. The floors are raised with zero
slack, which means most human commits on `main` raise one; a PR branched the day before
such a commit has a floor that is lower than `main`'s and has lowered nothing. Comparing
against the tip made every open PR a guaranteed reject at the moment a human raised a
floor, with the wrong message ("Lowering a floor is a human decision") and the wrong
routing (escalate as judge tampering, rather than rebase and retry). The merge base is
the floor this branch actually started from, so "lowered in this PR" means what it says.
The stale case is still not a pass - the PR has not run the assertions the new floor
covers - but it is a DIFFERENT failure: `RATCHET_STALE`, so the caller can rebase.

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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FLOOR = ROOT / ".factory" / "locks" / "floor.json"
STATIC_COUNT = HERE / ".run" / "static-checks"

# floor key -> (marker regex with one group, human name)
MARKERS: dict[str, tuple[str, str]] = {
    "static_checks": (r"^STATIC_OK checks=(\d+)", "static checks"),
    "unit_tests": (r"^UNIT_PASSED tests=(\d+)", "unit tests"),
    "e2e_steps": (r"^E2E_PASSED steps=(\d+)", "journey steps"),
    "holdout_assertions": (r"^HOLDOUT_PASSED scenarios=\d+ assertions=(\d+)", "holdout assertions"),
    "mutations_total": (r"^MUTATIONS_TOTAL=(\d+)", "mutations"),
    # The independence number. Every document in this repo calls it "the number to watch"
    # and nothing watched it: a product change that stops a holdout scenario exercising a
    # mutated path leaves 8/8 caught while this falls from 7 to 1, with every other floor
    # green. Floor it and the gate notices the gate getting weaker.
    "mutations_above_line": (r"^MUTATIONS_ABOVE_LINE=(\d+)", "defects caught above the line"),
    "contract_events": (r"^CONTRACT_OK events=(\d+)", "wire events compared"),
    "contract_fields": (r"^CONTRACT_OK events=\d+ fields=(\d+)", "wire fields compared"),
    "phrases_cases": (r"^PHRASES_OK cases=(\d+)", "translated phrases"),
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


def merge_base(ref: str) -> str | None:
    p = subprocess.run(["git", "merge-base", ref, "HEAD"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def observed(log: str) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for key, (pattern, _) in MARKERS.items():
        m = re.search(pattern, log, re.MULTILINE)
        out[key] = int(m.group(1)) if m else None
    if out.get("static_checks") is None and STATIC_COUNT.exists():
        try:
            out["static_checks"] = int(STATIC_COUNT.read_text(encoding="utf-8").strip())
        except ValueError:
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
            print(f"  ok  {key:<22} observed={got:<5} floor={floor}", flush=True)

    stale: list[str] = []
    if args.base:
        base = floors_at(args.base)
        mb = merge_base(args.base)
        started_from = floors_at(mb) if mb else base
        for key, floor in sorted(base.items()):
            head = floors.get(key)
            began = started_from.get(key)
            if head is None:
                if began is None:
                    # The key did not exist when this branch started; main added it.
                    stale.append(f"{key}: added on {args.base} after this branch started")
                else:
                    failures.append(f"{key}: floor {began} at the merge base was removed")
            elif began is not None and head < began:
                failures.append(f"{key}: floor lowered {began} -> {head} relative to the merge "
                                f"base. Lowering a floor is a human decision made on main, "
                                f"not in a PR")
            elif head < floor:
                stale.append(f"{key}: {head} here, {floor} on {args.base}")

    if failures:
        for f in failures:
            print(f"  RATCHET_FAIL  {f}", flush=True)
        print(f"RATCHET_FAILED floors={len(floors)} failures={len(failures)}", flush=True)
        return 1

    if stale:
        # NOT tampering, and not a pass either. The branch predates a human floor raise,
        # so it has not run the assertions that floor covers. Rebase and re-run.
        for s in stale:
            print(f"  RATCHET_STALE  {s}", flush=True)
        print(f"RATCHET_STALE base={args.base} keys={len(stale)} - this branch was cut before a "
              f"floor was raised on {args.base} and has lowered nothing. Rebase onto "
              f"{args.base} and run the gate again; this is not a judge-tampering finding.",
              flush=True)
        return 1

    print(f"RATCHET_OK floors={len(floors)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
