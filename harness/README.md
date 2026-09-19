# The validation harness

```bash
python harness/ci.py --quick   # static + unit. A few minutes. Runs anywhere with uv.
python harness/ci.py           # the whole gate. Needs uv and nothing else: no secrets, no network.
```

Measured 2026-09-06 on `product/virtual-agent`, before the 2026-09-19 harness fixes:

```
HARNESS_START mode=full driver=http
STATIC_OK
UNIT_PASSED tests=78
APP_STARTED port=61766
E2E_PASSED steps=25
HOLDOUT_PASSED scenarios=6 assertions=47
MUTATIONS_TOTAL=10
MUTATIONS_CAUGHT=8
MUTATIONS_NOT_INJECTED=0
MUTATIONS_ABOVE_LINE=10
GATE_OK mode=full
```

**That measurement is from a Windows desk** (the port gives it away) and it predates the
static and ratchet rungs growing. It has never been re-run on the Linux host the factory
actually validates on; until it has, this block is a record and not a baseline. The
2026-09-19 run adds `STATIC_OK checks=7`, `CONTRACT_OK`, `PHRASES_OK` and `RATCHET_OK`.

`python` must be a real 3.11 interpreter. On Windows the Store stub that prints
"Python est introuvable" is first on PATH by default; put
`%LOCALAPPDATA%\Programs\Python\Python311` ahead of it or the gate exits before its
first rung. **Whatever interpreter starts `ci.py` runs every rung**: the config writes
`{python}`, substituted with `sys.executable` when it is loaded, so the ladder cannot
half-run under a second interpreter PATH happened to find.

## What is in here, and where it came from

| File | Origin |
|---|---|
| `ci.py` · `appproc.py` | The `build-dark-factory` skill's ladder and app-process manager. Kept in that shape on purpose; the 2026-09-19 fixes to `ci.py` (the `{python}` token, the ratchet rung, the zero-step guard, UTF-8 stdout) are worth upstreaming rather than diverging over. |
| `harness.config.json` | This repo. Every command the gate runs, and the two timeouts it enforces. |
| `static.py` · `unit.py` | This repo. The static rung is ruff, ruff-format, mypy, `static_ios.py`, `static_contract.py`, and ruff on `tools/wiki`; the unit rung is pytest on the service and on `tools/wiki`, with parsed counts. Every `uv run` carries `--all-extras`, because the tools live in each project's `dev` extra and a plain `uv run` does not install it. |
| `static_ios.py` | This repo. What can honestly be checked of the app without a Swift toolchain: the XcodeGen spec, the Info.plist, balanced braces, and the four-language rule on user-facing strings. **Not a compile.** |
| `static_contract.py` | This repo. The two-consumer contract: event names and field shapes across `docs/API.md`, `agent/events.py`, `routes/sessions.py` and the app's `Models.swift` + `AgentAPI.swift`. |
| `ratchet.py` | This repo. Grades a gate log against `.factory/locks/floor.json`, and against the floors at the **merge base** of the branch. |
| `serve.py` · `stubs.py` | This repo. Starts stub providers (an OpenAI-shaped model and embeddings, a Brave-shaped search) on a free port, points the service at them and at `fixtures/wiki`, runs uvicorn as a child that dies with it. |
| `fixtures/wiki/` | This repo. The wiki the journey runs against: opening hours in English and French, a returns policy. **Locked**: the journey and the comprehensive-test scenarios both assume it. |
| `e2e.py` | This repo. **FACTORY_RULES.md section 4, all of it.** Twelve assertions against a live process. |
| `mutations/` | This repo. Eight deliberate defects and the runner that injects them. |

The validate-pr workflow runs `serve.py` the same way `ci.py` does, so there is one
definition of "the service is up" and one of "the journey passed".

## The six rungs are one command

`python harness/ci.py` runs static, unit, the journey against a live process, the
holdout, the mutation set **and the ratchet**, in that order, and exits `GATE_OK
mode=full` only when all six hold. The ratchet used to live only in the workflow, as a
second command, while every document here called `ci.py` the whole gate: a builder who
deleted tests saw `GATE_OK` locally and learned about the floor in validation, burning
one of two fix attempts. It now grades the run's own log, kept at `harness/.run/gate.log`,
and compares this branch's floors against the merge base with `origin/main` (or
`FACTORY_BASE_REF`) when one resolves.

Three of its verdicts are distinct on purpose:

- `RATCHET_OK floors=N` - observed >= floor, every key.
- `RATCHET_FAILED` - a count fell, or this PR lowered a floor below the one it branched
  from. That is the judge-tampering finding, and it escalates.
- `RATCHET_STALE` - a human raised a floor on `main` after this branch was cut. The PR
  lowered nothing; it simply has not run the assertions the new floor covers. **Rebase
  and re-run**, do not escalate.

## What the gate proves, and what it does not

The service's only client is an iOS app that cannot run on the factory's machines. So
the journey is the **API contract** in `docs/API.md`, driven exactly as the app drives
it: open a session, send what the client said, read the stream. That is the whole of
section 4 and it runs here, against a live process, every time.

Because the providers are stubs, the gate proves the **pipeline**: that the language the
pipeline chose reached the model, that the source it declares is the one it used, that
the web was **not** called while the wiki had a confident answer (the stub counts its
calls), that a sentence is ready to speak before the turn closes. It does **not** prove
that OpenRouter or Brave behave, and it does not prove that the app speaks. The first is
the mocked-boundary policy in `CLAUDE.md`; the second is the gap `FACTORY.md` names, and
a person with a Mac closes it.

What `static_contract.py` adds is the half of that second gap a machine can reach: the
app is never compiled here, but the **shape it decodes** is compared to the shape the
service emits, in both directions, on every run. A renamed `voice_locale` or a new
required field now stops the gate instead of the first spoken sentence.

## What exists above the independence line

```
python .factory/holdout/run.py     HOLDOUT_PASSED scenarios=6 assertions=47
python harness/mutations/run.py    MUTATIONS_TOTAL=10 CAUGHT=10 NOT_INJECTED=0 ABOVE_LINE=10
```

- **Holdout** - `.factory/holdout/run.py`, five composed scenarios aimed at MISSION hard
  invariants 1 through 6. **Written 2026-09-03 from the PRD and `docs/API.md`, before the
  code existed**, against module names that did not yet exist; the implementation was
  built until they passed. That is the property in the right order. One mechanical
  adaptation since: the route walk descends into FastAPI 0.141's nested routers
  (2026-09-04). The assertions are unchanged.
- **Mutation set** - `harness/mutations/`, eight defects, every one type-clean and
  lint-clean on purpose, aimed at the invariants and at the one property the requirement
  calls "live". All eight caught, and **seven of the eight by the holdout**, whether or
  not the unit suite caught them first. The eighth, `sentences-only-at-the-end`, is caught
  by unit alone: the holdout has no liveness scenario yet, and a defect caught only by a
  check the builder can edit is a defect the builder could arrange not to be caught.
- **Ratchet** - `.factory/locks/floor.json`, floors set equal to what is observed today,
  so the slack is zero.

`MUTATIONS_ABOVE_LINE` is the number to watch: if it falls, the gate has become more
dependent on checks the builder controls; if it reaches zero, entirely. It is no longer
watched by eye - `ratchet.py` reads it, so `mutations_above_line` can be floored like any
other count.

## The mutation runner's two deviations

`mutations/run.py` mutates the real file and restores it with `git checkout --`, instead
of copying the tree per defect: `app/backend/.venv` is large and the checks need it. So
the runner **refuses a dirty tree**, and if it is killed mid-defect `git status` shows
exactly one modified file. A kill by the outer timeout is handled for it: `ci.py` checks
the defect targets out again and prints `MUTATIONS_RESTORED` or `MUTATIONS_DIRTY <file>`,
because a killed process cannot run its own `finally`.

And it runs `ci.py --quick` plus the holdout, not the full gate, so the E2E rung is
excluded from what a mutation can be caught by. That is boot cost, not a missing
environment: the full gate needs no secrets. `FACTORY_MUTATION_FULL=1` spends the cost
and closes the hole for one run.

## Refusing loudly

`serve.py` refuses to start without `uv` and says so:

```
APP_START_REFUSED missing=uv - install uv (https://docs.astral.sh/uv/) ...
```

That refusal is deliberate. On 2026-04-18 the previous product's workflow launched the
service without its environment, the process crashed at import, the health poll failed,
and the synthesizer scored it as `not_e2e_testable`. A PR auto-merged having never been
driven end to end. **A step that cannot run has to be loud, not absent.** The
`APP_STARTED` marker, printed only once `/api/health` reports the wiki loaded, is the
positive assertion the validate-pr workflow reads deterministically before any approve.

The same rule is why a failing rung's output is quoted. `ci.py` prints every line of it
behind a `| `, between two delimiter lines, so that nothing a test happened to echo can
be mistaken by a caller grepping for `GATE_OK` or `HOLDOUT_PASSED`.
