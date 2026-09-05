# The factory

<!--
  Maintainer: whoever changes what runs unattended. Update the level and the date in the
  SAME commit that changes either - a stale level here is a lie about what is running
  with nobody watching.
-->

**Current autonomy level: 4** - an untriaged issue is classified, planned, built,
reviewed, independently validated and **merged** with no human in the chain. A person
files the issues and promotes releases.
**Level 5 is deliberately not the goal.** The factory does not write its own issues.
**Stop button:** `.factory-stop` in the orchestrator's working copy (works with the
network down) **and** the `factory:stop` label on any open issue (reachable from a
phone). Both fail closed. Checked by `scripts/factory-stop.sh` before anything else is
read. Tested on purpose, both directions, 2026-08-12.
**Built from PRD:** [`docs/virtualagent.prd.md`](docs/virtualagent.prd.md), itself
written from the four sentences in [`requirements.md`](requirements.md) - `MISSION.md`
is its compression. **Change one, change both**, in the same commit. Nothing warns you:
the factory will keep faithfully building the old scope until someone notices.
**Product replaced 2026-09-03.** Until then this factory built DynaChat, a RAG chat over
a YouTube channel. The factory, its rules and its incident log carried over; the
application did not. Every number below was re-measured against the new product.

## The five components, as built here

| # | Component | This repo's version |
|---|---|---|
| 1 | Workflow-driven repo | **Archon**, four YAML workflows in `.archon/workflows/`. State in GitHub labels |
| 2 | The trigger | Pure-bash orchestrator on the VPS at `/opt/dark-factory/orchestrator.sh`, cron every 30 min, `MAX_PARALLEL=4` with per-target locks |
| 3 | Deployment | `deploy/deploy.sh` - polls `main`, rebuilds the inactive colour (the image carries the wiki), waits for the Docker healthcheck (which passes only once the wiki is indexed), swaps the Caddy upstream. Rollback is flipping it back |
| 4 | Guidance layer | `MISSION.md` · `FACTORY_RULES.md` · `CLAUDE.md`, all three protected |
| 5 | Validation harness | `harness/ci.py`, the whole gate, including the section 4 journey. See below |

**The orchestrator is deliberately not in this repo.** It holds no state of its own, and
everything it reads is visible here as issues, PRs and labels. The one bad consequence -
that the only off switch lived on a machine - is fixed: `scripts/factory-stop.sh` is
versioned here and the orchestrator calls it first.

## The gates that are actually code

Everything else is a prompt instruction, which is a suggestion with good manners. These
cannot be argued past:

1. **`apply-verdict`** in `dark-factory-validate-pr.yaml` - bash reads a verdict file and
   branches on it. The merge is never a model deciding to merge.
2. **The `APP_STARTED` backstop**, same node. Deterministic bash reads `start-app`'s
   output and flips any `approve` to `reject`+escalate when the marker is absent.
   Added after PR #80 (`3fc03a0`).
3. **`harness/ci.py`** - the ladder. Static, unit, the journey against a live process,
   the holdout, the mutation set, in that order, each with a positive marker and a
   count, exit non-zero on the first that fails. Added 2026-08-13; the journey moved
   into it 2026-09-04.

**Three.** It was two; the third is what closed the gap the previous product carried for
five months.

## The end-to-end path

`FACTORY_RULES.md` section 4, twelve assertions, in `harness/e2e.py`, against a service
`harness/serve.py` started with stub providers: the service is up with exactly the four
languages; a session opens with a spoken greeting; an anonymous turn is refused; a
wiki-covered French question is answered in French, sentence by sentence, from the wiki,
**with the web never called**; an uncovered German question is answered from the web
with a URL; Arabic is Arabic; an unsupported language gets a spoken question; another
session's token cannot read the transcript.

The service's only client is an iOS app that cannot run on the factory's machines. So the
journey is the API contract in `docs/API.md`, driven exactly as the app drives it. That is
the whole journey - and it is a smaller claim than "a client heard the answer".

## Component 5, stated honestly

```
python harness/ci.py
  HARNESS_START mode=full driver=http
  STATIC_OK
  UNIT_PASSED tests=52
  APP_STARTED port=61766
  E2E_PASSED steps=12
  HOLDOUT_PASSED scenarios=5 assertions=32
  MUTATIONS_TOTAL=8
  MUTATIONS_CAUGHT=8
  MUTATIONS_NOT_INJECTED=0
  MUTATIONS_ABOVE_LINE=7
  GATE_OK mode=full
```

Measured 2026-09-04. Real, reproducible, and it needs no secrets: the stubs are an
OpenAI-shaped model and a Brave-shaped search, so **the gate proves the pipeline, not
the providers.** What the real model says to a real client is the mocked-boundary
policy in `CLAUDE.md`, and a person checks it on the host after a merge.

Above the independence line:

- **Holdout** - `.factory/holdout/run.py`, five composed scenarios aimed at MISSION hard
  invariants 1 through 5, **written 2026-09-03 from the PRD before the code existed**.
  That is a holdout's first rule and this one follows it, which the previous product's
  did not. One mechanical adaptation since (the route walk descends into FastAPI
  0.141's nested routers); the assertions are the ones written on the day.
- **Mutation set** - `harness/mutations/defects.json`, eight defects, each type-clean and
  lint-clean on purpose so it measures the harness and not the compiler: the cap raised,
  the window shrunk, a fifth language, Arabic never detected, web before wiki, source
  always wiki, the transcript guard removed, sentences only at the end. All eight caught,
  **seven of them by the holdout** - the number that matters, because the holdout is the
  one check the builder cannot read. The eighth is below.
- **Ratchet** - `.factory/locks/floor.json`, every floor equal to the number above, so
  the slack is zero and raising one is a human commit.

**What is still missing, named rather than quietly absent:**

| Gap | Consequence | Tracked |
|---|---|---|
| The app has never been compiled or run | The half of the product a client touches is verified by a person with a Mac, not by the gate | D-005 |
| The mutation runner excludes the E2E rung | A defect only the journey could catch escapes the mutation set; `mutations/run.py` says so in its header | D-006 |
| The holdout has no liveness scenario | `sentences-only-at-the-end` is caught by the unit suite alone, below the independence line | D-006 |
| The gate cannot hear | Whether the voice is intelligible, whether the first sentence arrives fast enough to feel live, is not a thing a stub can assert | D-005 |
| The real wiki is one document | `virtualagent/resources/` holds the about-page only; the business's documents are not in yet, so the falsification test in the PRD ("most answers from the wiki") cannot be run | D-007 |

## Incident log

Append only. Every entry is a rule that now exists because of it.

| Date | What happened | What changed |
|---|---|---|
| 2026-04-14 | The first twelve hours of the factory were quoting, heredocs and shell escaping across a Windows `bash -c` boundary. Almost nothing was about AI | The agent is the interchangeable part; the plumbing is not |
| 2026-04-15 | The verdict schema allowed `e2e_status: "not_e2e_testable"`, giving the model an honest-looking exit when the app failed to start. The health poll also targeted `/health`, but the backend only serves `/api/health` - so every run would have failed identically and masked the real bug | Rule 0 gained an explicit FORBIDDEN clause. **An enum value with no deterministic check behind it is an escape hatch** (`c4997c4`) |
| 2026-04-18 | `start-app` launched uvicorn with no env, the backend crashed at import with `RuntimeError: DATABASE_URL is not set`, and the synthesizer scored it `not_e2e_testable`. **PR #80 auto-merged having never been driven through a browser**, and was reverted the same day | The deterministic `APP_STARTED` backstop. Bash reads the raw output and overrides the model (`3fc03a0`) |
| 2026-05 → 2026-08 | The factory ran on a 30-minute cron for roughly three months and found nothing to do. A benchmark run had parked all 17 open issues as `factory:in-progress`, and the priority order correctly refuses to start new work while work is in flight. **The rule that keeps a factory healthy is the rule that starved it** | Backlog cleared by hand 2026-08-11 (`#364`). A stall reaper is the outstanding fix |
| 2026-08-12 | The comprehensive-test workflow scored an unreadable result as a clean one: a missing fenced JSON block set `FAILURES_JSON=[]` and printed ALL GREEN | Both paths exit non-zero, and the run emits `SCENARIOS_RAN` (`c97f9ff`) |
| 2026-08-12 | The only off switch lived on the VPS, unreachable except over SSH | `scripts/factory-stop.sh`, versioned here, called first by the orchestrator. Fails closed |
| 2026-09-04 | `harness.config.json` held an invalid JSON escape (`\d`), so `ci.py` raised before its first rung. **The gate had never run on any machine** since the product was replaced; every green claim about it was a claim about scripts run by hand | Fixed (`11a37e2`). The full gate was run and its output pasted above; a number in this file is a number that was observed |
| 2026-09-04 | The holdout's public-surface whitelist saw three routes, all public: FastAPI 0.141 nests included routers, and every session route sat unexamined one level down. Only the count assertion (`>= 6`) noticed | The walk descends into nested routers. **A whitelist is only as good as the enumeration it runs over**, and a count assertion next to it is what tells you the enumeration broke |
