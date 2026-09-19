#!/usr/bin/env python3
"""MUTATION TESTING. Break the software on purpose and require the gate to notice.

    python harness/mutations/run.py

THE ONLY THING IN THIS GATE THAT MEASURES THE HARNESS RATHER THAN THE CODE. Everything
else answers "is this build good?". This answers "would this gate know if it were not?",
and they are completely different questions. Until one of these has been injected and
caught there is no evidence any check here can fail at all.

═══════════════════════════════════════════════════════════════════════════════════════
TWO DELIBERATE DEVIATIONS FROM THE SKILL'S TEMPLATE, both forced by this repo.
═══════════════════════════════════════════════════════════════════════════════════════

**1. It mutates IN PLACE and restores with git, instead of copying the tree.**
The template copies `["app", "tests", "harness", ".factory"]` into a temp dir per defect.
Here `app/` contains `app/backend/.venv` - hundreds of megabytes, and the better part of
a minute per defect. Excluding it instead breaks the copy, because ruff, mypy and pytest
all run out of that venv.

So: apply the mutation to the real file, run the checks, and restore with
`git checkout --`. Every file a defect touches must be CLEAN before this starts, which
is asserted below (the rest of the tree may be dirty: validate-pr overlays `.archon/`
onto the PR worktree), and every path restores in a `finally`.

A `finally` does not survive being killed. When the outer cap in `harness/ci.py`
(`mutations_timeout_s`) expires, this process is terminated where it stands, and ci.py -
which is still alive - checks the defect targets out again and prints `MUTATIONS_RESTORED`
or `MUTATIONS_DIRTY <file>`. Run by hand and killed by hand, `git status` shows exactly
one modified file and `git checkout -- <file>` is the fix.

**2. It runs `ci.py --quick` PLUS the holdout, not the full `ci.py`.**
Not because the full gate cannot run: it can, here, with no secrets and no network -
`harness/serve.py` starts stub providers and `e2e.py` has been rung 3 of `ci.py` since
2026-09-04. It is boot cost. The full gate starts a uvicorn process and indexes the wiki
per run, and eight defects times that, twice (the quick gate and the holdout each already
cost seconds, not minutes), turns a ~90 s rung into a many-minute one on every PR.

The consequence is stated rather than hidden: **these eight defects are caught by static,
unit and holdout only.** A defect that only the API journey could catch would escape here
and this file would not know. Set `FACTORY_MUTATION_FULL=1` to spend the boot cost and
close that hole for one run.

Emits `MUTATIONS_TOTAL=N` and `MUTATIONS_CAUGHT=N`; the gate requires them equal.
`MUTATIONS_ABOVE_LINE=N` is how many the holdout caught, whether or not a lower rung
caught them first. That is the independence number, it is the one to watch, and since
2026-09-19 `harness/ratchet.py` can floor it instead of asking a human to watch by eye.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFECTS = Path(__file__).resolve().parent / "defects.json"


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def paths_are_clean(paths: list[str]) -> bool:
    """Only the files this runner mutates and restores need to be clean.

    The first version checked the whole tree, which would have refused every
    validate-pr run: the workflow overlays .archon/ from origin/main onto the PR
    worktree before the gate runs, so the tree is legitimately dirty in files no
    defect touches. What `git checkout --` must not destroy is uncommitted work in
    a file it is about to restore, and that is exactly the set checked here."""
    return not git("status", "--porcelain", "--", *paths).stdout.strip()


def apply(defect: dict) -> bool:
    target = ROOT / defect["file"]
    if not target.exists():
        return False
    body = target.read_text(encoding="utf-8")
    if defect["find"] not in body:
        return False
    target.write_text(body.replace(defect["find"], defect["replace"], 1), encoding="utf-8")
    return True


def run_checks() -> tuple[bool, str, bool]:
    """Returns (went_red, first rung that went red, holdout also red).

    The holdout runs EVEN WHEN a lower rung already caught the defect. The number that
    matters is how many defects are caught above the independence line, and a runner
    that stops at the first red rung can only ever report the lowest one - the first
    measurement read 1 of 8 above the line for exactly that reason.

    utf-8 with replacement on every child: Windows decodes as cp1252 by default, the
    holdout and the service print Arabic, and the reader thread died on byte 0x81 during
    the first full run. A rung attribution read from a half-decoded buffer is a guess.

    THE BUDGETS BELOW ARE SIZED TO WHAT THE RUN COSTS. Eight defects measure ~90 s in
    total on a warm cache, about 11 s each for both children together. 180 s and 60 s are
    roughly twenty times that, which covers a cold uv and mypy cache in a fresh worktree.
    They used to be 900 s each, so eight defects could in principle ask for four hours
    under an outer cap of fifteen minutes - the cap always won, and killed the runner
    holding a mutated file.
    """
    env = dict(os.environ, FACTORY_IN_MUTATION="1")
    full = os.environ.get("FACTORY_MUTATION_FULL") == "1"
    gate = [sys.executable, "harness/ci.py"] + ([] if full else ["--quick"])

    quick = subprocess.run(gate, cwd=ROOT,
                           env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600 if full else 180)
    rung = ""
    if quick.returncode != 0:
        rung = "gate"
        for line in (quick.stdout or "").splitlines():
            if line.startswith("GATE_FAILED:"):
                rung = line.split(":", 1)[1].strip()

    holdout = subprocess.run([sys.executable, ".factory/holdout/run.py"], cwd=ROOT,
                             env=env, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
    holdout_red = holdout.returncode != 0

    if rung:
        return True, rung, holdout_red
    if holdout_red:
        return True, "holdout", True
    return False, "", False


def main() -> int:
    if not DEFECTS.exists():
        print("MUTATIONS_ABSENT no defects.json next to this script", flush=True)
        return 0

    defects = json.loads(DEFECTS.read_text(encoding="utf-8"))["defects"]
    targets = sorted({d["file"] for d in defects})
    if not paths_are_clean(targets):
        # REFUSE. Restoring with `git checkout --` would destroy uncommitted work, and a
        # mutation runner that eats your changes is a tool nobody runs twice.
        print("MUTATIONS_REFUSED a file this runner mutates has uncommitted changes. It "
              "mutates in place and restores with git, so it will not start until these "
              f"are committed or stashed: {', '.join(targets)}", flush=True)
        return 1

    total = caught = not_injected = above = 0

    print("MUTATION_START", flush=True)
    for d in defects:
        total += 1
        injected = False
        try:
            if not apply(d):
                # NOT a pass. The anchor moved, so this defect tested nothing - and a
                # mutation set that silently stops injecting reports a perfect score for
                # doing nothing at all.
                not_injected += 1
                print(f"  NOT_INJECTED  {d['id']:<38} anchor not found in {d['file']}",
                      flush=True)
                continue
            injected = True
            went_red, rung, holdout_red = run_checks()
            if went_red:
                caught += 1
                if holdout_red:
                    above += 1
                tag = rung if rung == "holdout" or not holdout_red else f"{rung} (+holdout)"
                print(f"  CAUGHT        {d['id']:<38} by {tag}", flush=True)
            else:
                print(f"  ESCAPED       {d['id']:<38} <-- {d['why']}", flush=True)
        finally:
            if injected:
                git("checkout", "--", d["file"])

    if not paths_are_clean(targets):
        print("MUTATIONS_DIRTY a mutated file did not restore cleanly - inspect `git status` "
              "before trusting anything above", flush=True)
        return 1

    print(f"MUTATIONS_TOTAL={total}", flush=True)
    print(f"MUTATIONS_CAUGHT={caught}", flush=True)
    print(f"MUTATIONS_NOT_INJECTED={not_injected}", flush=True)
    print(f"MUTATIONS_ABOVE_LINE={above}", flush=True)
    if caught == total and not_injected == 0:
        print("MUTATIONS_OK", flush=True)
        return 0
    print("MUTATIONS_FAILED - every escaped defect is a class of bug that can currently "
          "merge unreviewed", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
