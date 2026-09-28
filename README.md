# The Dark Factory Experiment

**A public Dark Factory experiment.** This repository is a factory that is built, reviewed,
and merged almost entirely by AI coding agents, aimed at whatever product `requirements.md`
currently names. Humans do one thing: file issues. Everything after that - triage,
implementation, code review, testing, merging - is handled by Archon workflows running on a
cron. Deploy is product-specific and lives with the product, not in this repository's
factory scaffolding.

Two honest caveats, because they are the design and not an asterisk. This runs at **level 4,
not level 5**: the factory does not write its own issues. And there is a deliberate
**human-authored perimeter** it is never allowed to touch - the invariants of whichever
product is current, and the three governance files that define its own rules. The list is in
`FACTORY_RULES.md` §5, with `.factory/protected-paths.txt` as its machine-readable twin - the
file the validator actually matches a PR's changed files against - and a PR touching any of
it is auto-rejected before anything else is evaluated. An autonomous system is only as
trustworthy as the things it cannot change about itself.

> **History.** Until 2026-09-03 this repository built DynaChat, a RAG chat interface over a
> YouTube channel's transcripts. The product was replaced in place from a four-sentence
> requirement (`requirements.md`); the factory, its rules and its incident log carried over.
> The old application is in git history, not in the tree.
>
> From 2026-09-03 to 2026-09-27 the product was the **Virtual Agent**, a multilingual
> push-to-talk voice assistant. It moved to `alaehassouni-a11y/firstRepo` on 2026-09-27,
> together with its product harness (https://github.com/alaehassouni-a11y/firstRepo/pull/54),
> and no product currently lives here. `requirements.md` is the placeholder; the sections
> below describe the factory that will build whatever comes next.

---

## The Dark Factory

The term "Dark Factory" comes from Dan Shapiro (Glowforge), inspired by FANUC's 1980s lights-out robotics plants where robots built robots 24/7 with no humans on the floor. Applied to software: **specs go in, software comes out.**

This repo is a live attempt at that pattern, and it uses GitHub itself as the shared state machine.

### The three layers

There's a stack of three distinct things doing the work, and it's worth pulling them apart:

1. **The harness: [Archon](https://github.com/coleam00/archon).** The workflow engine, and the thing that makes the whole experiment possible. Archon lets you stitch coding agent sessions together with deterministic steps (running scripts, calling `gh`, parsing output, branching on results) into a single end-to-end workflow you actually trust. The Dark Factory's logic, "triage these issues, then implement this one, then validate the PR, then merge it," is built in Archon as a handful of workflows under `.archon/workflows/`. Without something like Archon, you're either hand-prompting agents one step at a time or writing a giant brittle script around them. Archon is what turns "AI can sometimes do this" into "the factory does this every few hours, on its own."
2. **The coding agent: Claude Code.** Inside each AI node, Archon spawns Claude Code as the agent. Claude Code is what actually holds the tools (file editing, bash, `gh`, web fetch), runs the loop, and executes the work the prompt asks for.
3. **The model: Claude Sonnet, with Haiku on the cheap nodes.** Set per workflow node, so the routing is a config decision rather than a property of the factory. Claude Code is the wrapper around the model; the model is the brain doing the reasoning and the writing.

Model routing is the cheapest lever in the whole system, and it is worth treating as one. The factory has run on MiniMax M2.7 and on Kimi K2.6 via Pi at different points in the experiment; the workflows under `.archon/workflows/` currently declare `provider: claude` with `sonnet` for reasoning nodes and `haiku` for cheap extraction. Nothing else in the design changes when that swaps, which is the point: the agent and the model are the interchangeable parts, and the plumbing around them is not.

A mixed-provider benchmark once measured that rather than assuming it - a matrix varying the plan and implement models independently to find out where reasoning actually pays for itself. It was run against DynaChat, the product this repository built until 2026-09-03, and every number in it is a DynaChat number: its candidate issues name files that no longer exist. It is archived, unrunnable as written, under [`docs/archive/benchmark-dynachat/`](docs/archive/benchmark-dynachat). Read `BENCHMARK-PLAYBOOK.md` there before quoting anything from it; it documents a known prompt-parity confound in the premium baseline cell.

### How a change actually ships

```
        GitHub Issues (filed by humans or the regression testing workflow)
                       │
                       ▼
            ┌──────────────────────┐
            │  Orchestrator (cron) │   pure-bash loop, no LLM
            │   every 30 minutes   │   reads GitHub state, dispatches
            └──────────┬───────────┘   up to MAX_PARALLEL=4 workflows
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
  dark-factory     fix-github-     dark-factory
  -triage          issue           -validate-pr
  (classify        (10-phase       (independent
   open issues,     implement +     holdout review
   accept/reject)   draft PR)       + auto-merge)
                       │
                       ▼
                ┌─────────────┐
                │    main     │  AI-managed branch
                └─────────────┘
                   deploy, if any, is defined by the current product,
                   under its own deploy/ folder — none exists right now
```

**There is no release branch and no promotion step in the factory itself.** A merged PR is
the end state the factory guarantees; whatever a product's own deploy configuration does
with `main` from there is that product's concern, described in its own docs when a product
exists. `FACTORY.md` says what the gate does and does not prove.

### Labels are the state machine

The orchestrator does not hold state itself. It reads GitHub labels and decides what to do next:

**Issues:** `factory:triaging` → `factory:accepted` → `factory:in-progress` → (PR opened) or `factory:rejected` (closed with reason).

**PRs:** `factory:implementing` → `factory:needs-review` → `factory:approved` (auto-merged) or `factory:needs-human` (escalated). A PR that needs changes is repaired **inside** the validation run - one fix pass in a fresh context, then a second validation pass, and if that one still asks for changes the PR escalates. There is no separate fix-PR workflow and no cross-run attempt counter. (`factory:needs-fix` still exists as a label and nothing consumes it; a PR that lands on it is a dead end, not a queue.)

**Priority:** Triage tags every accepted issue `priority:critical|high|medium|low` so the orchestrator picks the highest-impact work first.

### The non-negotiable rules

These come from research on every prior Dark Factory attempt (StrongDM, Spotify Honk, Steve Yegge's Gas Town) and the failure modes they hit:

1. **The validator never reads the implementation plan.** It checks the *outcome* against the *issue*, not the approach. This is StrongDM's "holdout" pattern - it's what stops an agent from gaming its own acceptance criteria. Above that sits a second holdout the builder cannot even read: a product's `.factory/holdout/run.py`, written from its PRD before the code exists. No product is current, so no holdout exists right now; the next one adds its own.
2. **Triage has only two verdicts: accept or reject.** No "needs human" inbox. If a human disagrees with a rejection, they reopen with more context and the next triage cycle picks it up fresh.
3. **Governance files (`MISSION.md`, `FACTORY_RULES.md`, `CLAUDE.md`) can never be modified by the factory.** The security review hard-fails any PR that touches them. The agent cannot amend the rules it is judged by.
4. **The dispatcher is dumb on purpose.** Pure bash on a 30-minute cron, reading GitHub labels as the only shared state - no database, no message bus, no LLM deciding what to run. An earlier version asked a model what to dispatch and it hallucinated runs for work that did not exist. It dispatches up to `MAX_PARALLEL=4` workflows, in a fixed priority order: validate a PR, implement an issue, triage. Finishing in-flight work before starting new work is load-bearing - reversed, the factory triages forever while its own PRs rot.
5. **Flood protection.** Non-owner accounts are capped at 3 issues per UTC day; excess get `factory:rate-limited` and re-evaluated after midnight.
6. **Per-node budget caps.** Every workflow node has a `maxBudgetUsd`. Triage batches max 10 issues per run and truncates each body to ~2KB.

### Workflows in this repo

Defined in [`.archon/workflows/`](.archon/workflows):

| Workflow | Job |
|---|---|
| `dark-factory-triage.yaml` | Batch-classify untriaged issues against `MISSION.md` + `FACTORY_RULES.md`. Outputs structured JSON, applies labels and comments deterministically via `gh`. |
| `dark-factory-fix-github-issue.yaml` | The workhorse. A Dark-Factory-owned fork of Archon's bundled `fix-github-issue`, adapted for this repo's uv-managed Python service: classify → research → plan → implement → validation (ruff/mypy/pytest + the MISSION invariant guard) → draft PR → smart review → self-fix → simplify. Every AI node references a `.md` command file (no inline prompts). |
| `dark-factory-validate-pr.yaml` | Independent gate. Static checks + tests, then parallel AI review (behavioral validation, the API journey against a running service, security check, code review), synthesized verdict, auto-merge or fix-and-retry. The fix step is folded in as a fresh-context node so the second-pass validator stays a true holdout. |
| `dark-factory-comprehensive-test.yaml` | Weekly regression. Boots the service against stub providers, drives four API scenarios with `curl`, synthesizes a report, and files a GitHub issue for anything that broke. This is what closes the self-healing loop: the factory finds its own bugs and queues them for itself. |

**The orchestrator is not in this repo.** It is a ~100-line bash script on the VPS
(`/opt/dark-factory/orchestrator.sh`) driven by cron. Deliberately so - it holds no state
of its own, and everything it reads is visible in this repo's issues, PRs and labels.
The one thing it does read from here first is the stop button, `scripts/factory-stop.sh`.

The mixed-provider benchmark suite is archived in [`docs/archive/benchmark-dynachat/`](docs/archive/benchmark-dynachat). It is not part of the factory loop and it is not run.

### The gate

`python harness/ci.py` is the one entrypoint a product wires up to decide whether a build is
good, and `FACTORY.md` is the honest account of what it does and does not cover: static
checks, the unit suite, an API journey against a live process with stub providers, the
holdout scenarios the builder cannot read, and a mutation set that breaks the product on
purpose and requires the gate to notice. `.factory/locks/floor.json` is the ratchet: the
numbers the gate must at least reach, raised only by human commits.

No product currently supplies `harness/` or a floor, so there is nothing for the gate to run.
`.github/workflows/gate.yml` detects that and reports `GATE_SKIPPED no harness/ci.py -
no product is currently specified (see requirements.md)` rather than failing every PR; the
mechanism - `harness/ci.py --quick` on every pull request and push to `main`, plus the full
gate as a second, allowed-to-fail job - resumes the moment a product adds its own
`harness/ci.py`.

### Making the gate binding

**Right now that check blocks nothing.** `main` has no branch protection and no ruleset,
it still accepts merge commits and rebase merges even though the rules say squash only
(two merge commits are already in its history), and no check has ever been required to
pass. The workflow reports; it does not stop anything. Turning it into a gate is five
clicks in GitHub's settings, which no code in this repository can do for itself. For the
owner, in order:

1. Open the repository on github.com → **Settings** → **General** → *Pull Requests*.
   Untick **Allow merge commits** and **Allow rebase merging**, leave **Allow squash
   merging** ticked, and tick **Automatically delete head branches**. Nothing saves
   separately on that page; the tickboxes save themselves.
2. Go to **Settings** → **Rules** → **Rulesets** → **New ruleset** → *New branch ruleset*.
   Name it `main`, set **Enforcement status** to **Active**.
3. Under *Target branches* choose **Add target** → **Include default branch**.
4. Under *Rules* tick **Require a pull request before merging** (set required approvals to
   **0** - every PR here is owner-authored and the factory's review is a comment, so
   requiring an approval would deadlock the loop), and tick **Require status checks to
   pass**. Then **Add checks**, search for `quick gate (static + unit)` and add it. Do not
   add the full-gate job: it is informational and allowed to fail.
5. Under *Bypass list* add yourself as the repository owner, so the direct pushes to
   `main` that `FACTORY_RULES.md` §12 depends on - editing the rules themselves - still
   work. Then **Create**.

The check only appears in step 4's search once the workflow has run at least once, so
merge a PR (or push) first and add the check afterwards.

One consequence worth knowing before you switch it on: the validator merges with a plain
`gh pr merge --squash`, which a required check will refuse until it has finished running.
That call will need to wait for the check or use `--auto`. It is in `.archon/workflows/`,
which is human-authored.

---

## The Product

**No product is currently specified.** The Virtual Agent - a multilingual push-to-talk voice
assistant, previously described here in full - moved to `alaehassouni-a11y/firstRepo` on
2026-09-27 along with its product harness
(https://github.com/alaehassouni-a11y/firstRepo/pull/54). `requirements.md` is a placeholder
and `MISSION.md` no longer names product invariants; a new product starts by writing its
requirements, then its harness under `harness/`, then its own PRD and mission invariants,
following the shape the Virtual Agent had (visible in firstRepo's history if a reference is
useful).

---

## Quick Start

There is nothing product-specific to run right now. The factory scaffolding itself needs
only [uv](https://docs.astral.sh/uv/) and `gh`; a product adds its own prerequisites,
service, and checks under its own README section here once one exists.

---

## Contributing

You contribute to this repo the same way the factory does: **file an issue.** Don't open a PR - the factory will. If your issue is well-scoped and in line with `MISSION.md`, the next triage cycle will accept it, and a workflow run will open the implementing PR. If it gets rejected, read the comment, sharpen the issue, and reopen.

With no product specified, the most useful issue right now is a new `requirements.md`.

That's the whole point of the experiment.
