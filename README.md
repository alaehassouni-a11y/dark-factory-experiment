# The Dark Factory Experiment (Virtual Agent)

**A public Dark Factory experiment.** This repository is a working product that is built, reviewed, and merged almost entirely by AI coding agents. Humans do two things: file issues and promote releases. Everything in between - triage, implementation, code review, testing, merging - is handled by Archon workflows running on a cron.

Two honest caveats, because they are the design and not an asterisk. This runs at **level 4, not level 5**: the factory does not write its own issues. And there is a deliberate **human-authored perimeter** it is never allowed to touch - the session token check, the daily turn cap, the language set, the deploy configs, the holdout, the ratchet, and the three governance files that define its own rules. The list is in `FACTORY_RULES.md`, and a PR touching any of it is auto-rejected before anything else is evaluated. An autonomous system is only as trustworthy as the things it cannot change about itself.

The product itself is the **Virtual Agent**: a spoken assistant for a business's clients. A client opens an iPhone app, speaks or types in French, English, German or Arabic, and the agent answers aloud in that language, live, from a wiki built out of the `virtualagent/resources` folder in this repository. When the wiki does not cover the question the agent searches the web and says so. When neither does, it says it does not know. But the *real* point of this repo is the factory that builds it.

> **History.** Until 2026-09-03 this repository built DynaChat, a RAG chat interface over a
> YouTube channel's transcripts. The product was replaced in place from a four-sentence
> requirement (`requirements.md`); the factory, its rules and its incident log carried
> over. The old application is in git history, not in the tree.

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

The mixed-provider benchmark under [`.archon/workflows/benchmark/`](.archon/workflows/benchmark) is where that gets measured rather than assumed - a matrix varying the plan and implement models independently to find out where reasoning actually pays for itself. Read `BENCHMARK-PLAYBOOK.md` there before quoting any number from it; it documents a known prompt-parity confound in the premium baseline cell. The benchmark predates the Virtual Agent and its cells were measured against the previous product.

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
                │ auto-deploys│  → blue/green swap on the VPS
                └──────┬──────┘
                       │  human promotes periodically
                       ▼
                ┌─────────────┐
                │  release/*  │  human-cut stable
                └─────────────┘
```

### Labels are the state machine

The orchestrator does not hold state itself. It reads GitHub labels and decides what to do next:

**Issues:** `factory:triaging` → `factory:accepted` → `factory:in-progress` → (PR opened) or `factory:rejected` (closed with reason).

**PRs:** `factory:implementing` → `factory:needs-review` → `factory:approved` (auto-merged) or `factory:needs-fix` → back to review (max 2 fix attempts) → `factory:needs-human` (escalated).

**Priority:** Triage tags every accepted issue `priority:critical|high|medium|low` so the orchestrator picks the highest-impact work first.

### The non-negotiable rules

These come from research on every prior Dark Factory attempt (StrongDM, Spotify Honk, Steve Yegge's Gas Town) and the failure modes they hit:

1. **The validator never reads the implementation plan.** It checks the *outcome* against the *issue*, not the approach. This is StrongDM's "holdout" pattern - it's what stops an agent from gaming its own acceptance criteria. Above that sits a second holdout the builder cannot even read: `.factory/holdout/run.py`, written from the PRD before the code existed.
2. **Triage has only two verdicts: accept or reject.** No "needs human" inbox. If a human disagrees with a rejection, they reopen with more context and the next triage cycle picks it up fresh.
3. **Governance files (`MISSION.md`, `FACTORY_RULES.md`, `CLAUDE.md`) can never be modified by the factory.** The security review hard-fails any PR that touches them. The agent cannot amend the rules it is judged by.
4. **The dispatcher is dumb on purpose.** Pure bash on a 30-minute cron, reading GitHub labels as the only shared state - no database, no message bus, no LLM deciding what to run. An earlier version asked a model what to dispatch and it hallucinated runs for work that did not exist. It dispatches up to `MAX_PARALLEL=4` workflows, in a fixed priority order: fix a PR, validate a PR, implement an issue, triage. Finishing in-flight work before starting new work is load-bearing - reversed, the factory triages forever while its own PRs rot.
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

The mixed-provider benchmark suite lives separately in [`.archon/workflows/benchmark/`](.archon/workflows/benchmark). It is not part of the factory loop.

### The gate

`python harness/ci.py` is the one entrypoint that decides whether a build is good, and
`FACTORY.md` is the honest account of what it does and does not cover. In short: static
checks, the unit suite, the API journey from `FACTORY_RULES.md` §4 against a live
process with stub providers, the holdout scenarios the builder cannot read, and a
mutation set that breaks the product on purpose and requires the gate to notice.
`.factory/locks/floor.json` is the ratchet: the numbers the gate must at least reach,
raised only by human commits.

---

## The Product

What the factory is actually building. The requirement is four sentences in
[`requirements.md`](requirements.md); the PRD written from them is
[`docs/virtualagent.prd.md`](docs/virtualagent.prd.md); `MISSION.md` is that PRD
compressed to what the factory has to obey.

### Architecture

```
┌──────────────────────┐      HTTPS /api/*      ┌──────────────────────────────┐
│    iPhone app        │ ─────────────────────► │      Service (FastAPI)       │
│  SwiftUI, iOS 17+    │                        │                              │
│                      │  ◄── SSE: language,    │  detect language             │
│  SFSpeechRecognizer  │      tokens, sentence, │      │                       │
│  AVSpeechSynthesizer │      sources, turn     │  wiki index ── BM25 + cosine │
│                      │                        │      │        (RRF fused)    │
└──────────────────────┘                        │  confident? ── yes ─► compose│
                                                │      │ no                    │
                                                │  web search (Brave) ► compose│
                                                │      │ none                  │
                                                │  "I do not know", source none│
                                                │                              │
                                                │  model: Claude Sonnet via    │
                                                │  OpenRouter, streamed and    │
                                                │  split into sentences        │
                                                └──────────────────────────────┘
                                                        ▲
                                          virtualagent/resources/*.md, *.txt
                                          (indexed at startup, baked into the image)
```

- **Client:** a native SwiftUI iPhone app under `app/ios/`, no third-party dependencies. The device does the listening and the speaking; the service decides what is said and in which voice locale.
- **Service:** one Python 3.11 FastAPI process under `app/backend/`, managed with `uv`. No database: sessions and the daily turn counter live in process.
- **Wiki:** every `.md` and `.txt` file under `virtualagent/resources/`, chunked and indexed at startup (BM25 over words plus cosine over embeddings, fused with reciprocal rank fusion). Adding a file to the folder is the only way the wiki grows.
- **Inference:** OpenRouter only - `anthropic/claude-sonnet-4.6` for answers, `openai/text-embedding-3-small` for the index.
- **Web fallback:** Brave Search, in the client's language, only when the wiki has no confident answer.
- **API:** documented in [`docs/API.md`](docs/API.md). Every agent turn streams as Server-Sent Events: the detected language first, then tokens, a `sentence` event each time one completes (the app speaks it immediately), the sources, and a closing `turn` that declares `wiki`, `web` or `none`.

### What cannot change

`MISSION.md` lists the hard invariants; the short version is that the supported languages are exactly French, English, German and Arabic, the wiki is always consulted before the web, every turn declares its source, a session is private to the client that opened it, the cap is 100 turns per client per day, and OpenRouter is the only provider.

---

## Quick Start

### Prerequisites

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- An [OpenRouter](https://openrouter.ai) API key
- Optional: a [Brave Search](https://brave.com/search/api/) API key for the web fallback
- For the app: a Mac with Xcode 15+ and [XcodeGen](https://github.com/yonaskolb/XcodeGen)

### Run the service

1. Create `app/.env` (gitignored) from `app/backend/.env.example`. The minimum is an `OPENROUTER_API_KEY`.

2. Install and start:

```bash
cd app/backend && uv sync --all-extras
```

```bash
cd app && uv --project backend run uvicorn backend.main:app --reload --port 8000
```

The service indexes `virtualagent/resources` at startup and refuses to start if it cannot. Check it with:

```bash
curl http://localhost:8000/api/health
```

3. Talk to it without the app, straight from the API:

```bash
curl -s -X POST http://localhost:8000/api/sessions -H 'Content-Type: application/json' -d '{"client_id":"me","language_hint":"fr"}'
```

Then send a turn with the returned token as a bearer token and watch the stream (see `docs/API.md`).

Or use the developer console, a single static page that types or listens, streams the answer, speaks each sentence as it arrives and shows every turn's source. Serve it on a fixed origin and allow that origin on the service:

```bash
python -m http.server 8080 --directory tools/dev-console
```

with `CORS_ORIGINS=http://localhost:8080` in `app/.env`, then open http://localhost:8080. It is a tool for people testing the service, not a client of the product; the iOS app remains the only client.

### Run the app

See [`app/ios/README.md`](app/ios/README.md): `xcodegen generate`, open the project, run on a simulator or an iPhone pointed at the service's LAN address. The app has not yet been compiled on a Mac; expect to fix the first build.

### Checks

```bash
python harness/ci.py --quick
```

runs static checks and the unit suite. `python harness/ci.py` is the whole gate, including the API journey against a live service with stub providers, the holdout and the mutation set; it needs no secrets. The individual tools, from `app/backend/`:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest
```

---

## Contributing

You contribute to this repo the same way the factory does: **file an issue.** Don't open a PR - the factory will. If your issue is well-scoped and in line with `MISSION.md`, the next triage cycle will accept it, and a workflow run will open the implementing PR. If it gets rejected, read the comment, sharpen the issue, and reopen.

To teach the agent something, add a Markdown file to `virtualagent/resources/` and open an issue asking for it to be merged; a merge to `main` is a deploy.

That's the whole point of the experiment.
