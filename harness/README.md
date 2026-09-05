# The validation harness

```bash
python harness/ci.py --quick   # static + unit. A few minutes. Runs anywhere with uv.
python harness/ci.py           # the whole gate. Needs uv and nothing else: no secrets, no network.
```

Measured 2026-09-06 on `product/virtual-agent`:

```
HARNESS_START mode=full driver=http
STATIC_OK
UNIT_PASSED tests=65
APP_STARTED port=61766
E2E_PASSED steps=12
HOLDOUT_PASSED scenarios=5 assertions=32
MUTATIONS_TOTAL=8
MUTATIONS_CAUGHT=8
MUTATIONS_NOT_INJECTED=0
MUTATIONS_ABOVE_LINE=7
GATE_OK mode=full
```

`python` must be a real 3.11 interpreter. On Windows the Store stub that prints
"Python est introuvable" is first on PATH by default; put
`%LOCALAPPDATA%\Programs\Python\Python311` ahead of it or the gate exits before its
first rung.

## What is in here, and where it came from

| File | Origin |
|---|---|
| `ci.py` · `appproc.py` | **Verbatim from the `build-dark-factory` skill.** The ladder and the app-process manager are the same in every factory; do not edit them here. |
| `harness.config.json` | This repo. Every command the gate runs. |
| `static.py` · `unit.py` | This repo. The static rung is ruff, ruff-format, mypy, `static_ios.py`, and ruff on `tools/wiki`; the unit rung is pytest on the service and on `tools/wiki`, with parsed counts. Each says what it does **not** cover. |
| `static_ios.py` | This repo. What can honestly be checked of the app without a Swift toolchain: the XcodeGen spec, the Info.plist, balanced braces. **Not a compile.** |
| `serve.py` · `stubs.py` | This repo. Starts stub providers (an OpenAI-shaped model and embeddings, a Brave-shaped search) on a free port, points the service at them and at `fixtures/wiki`, runs uvicorn as a child that dies with it. |
| `fixtures/wiki/` | This repo. The wiki the journey runs against: opening hours in English and French, a returns policy. **Locked**: the journey and the comprehensive-test scenarios both assume it. |
| `e2e.py` | This repo. **FACTORY_RULES.md section 4, all of it.** Twelve assertions against a live process. |
| `mutations/` | This repo. Eight deliberate defects and the runner that injects them. |

The validate-pr workflow runs `serve.py` the same way `ci.py` does, so there is one
definition of "the service is up" and one of "the journey passed".

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

## What exists above the independence line

```
python .factory/holdout/run.py     HOLDOUT_PASSED scenarios=5 assertions=32
python harness/mutations/run.py    MUTATIONS_TOTAL=8 CAUGHT=8 NOT_INJECTED=0 ABOVE_LINE=7
```

- **Holdout** - `.factory/holdout/run.py`, five composed scenarios aimed at MISSION hard
  invariants 1 through 5. **Written 2026-09-03 from the PRD and `docs/API.md`, before the
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

Re-run the mutation set after any harness change and watch `MUTATIONS_ABOVE_LINE`. If it
falls, the gate has become more dependent on checks the builder controls; if it reaches
zero, entirely.

## The mutation runner's two deviations

`mutations/run.py` mutates the real file and restores it with `git checkout --`, instead
of copying the tree per defect: `app/backend/.venv` is large and the checks need it. So
the runner **refuses a dirty tree**, and if it is killed mid-defect `git status` shows
exactly one modified file. And it runs `ci.py --quick` plus the holdout, not the full
gate, so the E2E rung is excluded from what a mutation can be caught by. A defect only
the journey could catch would escape here, and the runner says so in its header.

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
