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
Here `app/` contains `app/backend/.venv` and `app/frontend/node_modules` - gigabytes, and
several minutes per defect. Excluding them instead breaks the copy, because the checks
need that venv to run at all.

So: apply the mutation to the real file, run the checks, and restore with
`git checkout --`. Every file a defect touches must be CLEAN before this starts, which
is asserted below (the rest of the tree may be dirty: validate-pr overlays `.archon/`
onto the PR worktree), and every path restores in a `finally`. If this process is killed mid-defect, `git status`
shows exactly one modified file and `git checkout -- <file>` is the fix.

**2. It runs `ci.py --quick` PLUS the holdout, not the full `ci.py`.**
The full gate starts the backend, which requires a validation env that holds secrets and
lives outside the repo. On any machine without it the app refuses to start and the gate
exits non-zero - which would mark every single defect CAUGHT, for a reason that has
nothing to do with the defect. A mutation suite that passes because the app cannot boot
is worse than no mutation suite, so the E2E rung is excluded rather than faked.

The consequence is stated rather than hidden: **these four defects are caught by static,
unit and holdout only.** A defect that only the browser journey could catch would escape
here and this file would not know. That is a real hole and it is the same hole
`harness/README.md` names - section 4 lives in the workflow, not in this harness yet.

Emits `MUTATIONS_TOTAL=N` and `MUTATIONS_CAUGHT=N`; the gate requires them equal.
`MUTATIONS_ABOVE_LINE=N` is how many the holdout caught, whether or not a lower rung
caught them first. That is the independence number, and it is the one to watch.
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
    """
    env = dict(os.environ, FACTORY_IN_MUTATION="1")

    quick = subprocess.run([sys.executable, "harness/ci.py", "--quick"], cwd=ROOT,
                           env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900)
    rung = ""
    if quick.returncode != 0:
        rung = "gate"
        for line in (quick.stdout or "").splitlines():
            if line.startswith("GATE_FAILED:"):
                rung = line.split(":", 1)[1].strip()

    holdout = subprocess.run([sys.executable, ".factory/holdout/run.py"], cwd=ROOT,
                             env=env, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=900)
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
