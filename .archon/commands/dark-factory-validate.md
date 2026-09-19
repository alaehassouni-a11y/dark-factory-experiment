---
description: Repair whatever the quick gate reported red. The gate itself is run by bash, not by you.
argument-hint: (no arguments — reads the gate-quick node's output and $ARTIFACTS_DIR/gate-quick.log)
---

# Dark Factory Validation — the repair pass

**Workflow ID**: $WORKFLOW_ID

---

## What changed, and why you are reading this

This command used to re-implement the gate by hand: it told you to run `ruff`,
`ruff format`, `mypy` and `pytest` under `app/backend`, and claimed that was
"exactly the rungs of `python harness/ci.py --quick`". It was not, and the drift
was expensive. When `tools/wiki` joined the ladder on 2026-09-06 this file was
not updated, so a change to the import tool — an allowed placement per
`CLAUDE.md` — passed here and failed at the validator, on both fix attempts,
and escalated. A prose copy of a command is a copy that goes stale.

So the gate is now run by the `gate-quick` bash node, which executes the real
`python harness/ci.py --quick` and writes its full output to
`$ARTIFACTS_DIR/gate-quick.log`. Your job is narrower and more useful: **read
what it reported and fix the code.** After you finish, the `gate-recheck` node
runs the same command again and the run cannot reach `create-pr` unless it
prints `GATE_OK mode=quick`. You do not get to declare yourself green.

---

## Inputs

### The gate's verdict

$gate-quick.output

The log is also at `$ARTIFACTS_DIR/gate-quick.log`. Read it with the Read tool
if the output above was truncated.

### What was implemented

Read `$ARTIFACTS_DIR/implementation.md` for what this change was meant to do,
and `git diff` for what it actually did.

---

## Your task

**If the output contains `BUILDER_GATE_GREEN`**: there is nothing to repair.
Write the artifact described below saying so, and stop. Do not "improve"
anything. Touching code the issue did not ask you to touch is a scope
violation (FACTORY_RULES §2) and the validator rejects for it.

**If the output contains `BUILDER_GATE_RED`**: find the first failing rung in
the log and fix it. The runner stops at the first red rung, so there may be
more behind it; `gate-recheck` will surface those.

The marker the log ends on tells you which rung failed:

| Marker | What failed | Where to look |
|---|---|---|
| `GATE_FAILED: static` | ruff, ruff format, mypy, the iOS manifest check, the phrases check or the API contract check | the quoted rung output in the log names the tool and the file |
| `GATE_FAILED: unit` | pytest, under `app/backend` or under `tools/wiki` | the pytest tail is in the log |
| `GATE_ENV_MISSING` | no usable `python` on PATH | an environment fault, not your change — say so and stop |

The static rung covers **two** projects and **five** tools. Run whichever one
failed, in the directory the log names:

```bash
cd app/backend && uv run --all-extras ruff check .
cd app/backend && uv run --all-extras ruff format .
cd app/backend && uv run --all-extras mypy .
cd tools/wiki && uv run --all-extras ruff check .
python harness/static_ios.py
python harness/static_contract.py
```

and for tests:

```bash
cd app/backend && uv run --all-extras pytest tests -x
cd tools/wiki && uv run --all-extras pytest tests -x
```

You may also simply re-run `python harness/ci.py --quick` yourself while
iterating; it is the same command the recheck will run.

---

## Golden rules

- **Fix the root cause, never the check.** Rewriting a test, loosening an
  assertion, adding a `# type: ignore`, or widening a lint exclusion to make a
  red rung go green is an explicit FACTORY_RULES §2 violation and the validator
  rejects for it. If the check is genuinely wrong, stop and say so in the
  artifact: that is a human decision.
- **Stay inside the issue's scope.** Repair what the gate reported. Do not
  refactor, tidy, rename or "improve" anything else.
- **Never edit a protected path** (`.factory/protected-paths.txt`). The gate's
  own scripts under `harness/` and `.factory/` are on that list: a builder that
  can edit its own judge has no judge. If the only way to make a rung pass is
  to change the rung, that is a `factory:needs-human` situation — write it in
  the artifact and stop.
- **Every bug fix ships a regression test** that fails before your change and
  passes after it (`CLAUDE.md`). If you added a test, say which.
- **The iOS app cannot be compiled here.** `static_ios.py` checks manifests,
  brace balance and that every user-facing string lives in `Phrases.swift` in
  all four languages. Passing it is not a build. If you changed Swift, say so
  in the artifact so the PR body can carry a `## Manual verification` section.

---

## Output artifact

Write `$ARTIFACTS_DIR/validation.md` with the Write tool:

```markdown
# Validation

Gate before: {GREEN | RED at rung <name>}
Gate after:  {GREEN | STILL RED}

## What the gate reported
{the failing rung and the actual error, quoted, one or two lines}

## What was wrong
{the root cause, in one or two sentences}

## What was changed
- {file}: {what and why}

## Regression test
{the test that now covers this, or "not applicable: no behaviour changed"}

## Needs a human
{empty, or: what cannot be fixed inside the factory's lane and why}
```

Then reply with one line: the gate's state before and after. Do not paste the
artifact into your reply.

---

## Success criteria

- **GATE_READ**: you read the gate's real output rather than re-deriving it
- **ROOT_CAUSE_FIXED**: the failing rung's cause is fixed in product code, not
  in the check
- **SCOPE_HELD**: no file outside the issue's scope was touched, and no
  protected path was touched at all
- **ARTIFACT_WRITTEN**: `$ARTIFACTS_DIR/validation.md` exists and is accurate

The run's actual verdict is not yours to give. `gate-recheck` runs
`python harness/ci.py --quick` after you and fails the run on anything but
`GATE_OK mode=quick`.
