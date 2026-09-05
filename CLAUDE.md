# CLAUDE.md

Instructions for AI coding agents working in this repository. Read this before making any code changes.

This file covers **how the code is written**. For *what* to build, see `MISSION.md`. For *how the factory operates*, see `FACTORY_RULES.md`. When this file and those conflict, MISSION.md wins on scope, FACTORY_RULES.md wins on process, and CLAUDE.md wins on code style.

---

## Project Overview

The **Virtual Agent** is a spoken assistant for a business's clients. An iPhone app captures what the client says, sends it to a service that detects the language (French, English, German or Arabic), answers from a wiki folder (`virtualagent/resources/` by default, watched for changes) or, failing that, from the web, and streams the answer back as text plus ready-to-speak sentences that the app speaks as they arrive. Every turn declares where its answer came from: `wiki`, `web` or `none`.

Two codebases, one contract: a Python 3.11 FastAPI service under `app/backend/` and a native SwiftUI iPhone app under `app/ios/`. The contract between them is `docs/API.md`. There is no database, no web frontend and no accounts.

---

## Tech Stack

**Service (`app/backend/`)**
- Python 3.11+ (do not rely on 3.12+ features)
- `uv` for package management (not pip, not poetry) - `pyproject.toml` is the dependency source of truth, `uv.lock` pins exact versions and is committed
- FastAPI with `uvicorn[standard]`
- `openai` SDK pointed at OpenRouter's OpenAI-compatible endpoint, for both chat completions and embeddings
- `httpx` for the one other outbound call (Brave Search)
- `python-dotenv` for the optional local `.env`
- Dev tools, pinned in `[project.optional-dependencies].dev`: `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `respx`, `pyyaml`

**App (`app/ios/`)**
- Swift 5.9, SwiftUI, iOS 17+
- Apple frameworks only: `Speech` (recognition), `AVFoundation` (synthesis, audio session), `URLSession` (networking). **No third-party dependencies.**
- The project is described by `project.yml` and generated with XcodeGen. Do not commit a generated `.xcodeproj`.

**Harness (`harness/`, `.factory/`)**
- Plain Python 3.11, stdlib only where it runs before the service's environment is guaranteed to exist (`stubs.py`, `serve.py`, `ci.py`, `appproc.py`)

---

## Repo Layout

```
dark-factory-experiment/
├── requirements.md          # The requirement, four sentences, verbatim
├── docs/
│   ├── virtualagent.prd.md  # The PRD written from those sentences - changes first, MISSION.md changes with it
│   └── API.md               # The service/app contract: every endpoint and SSE event
├── MISSION.md               # The PRD compressed to what the factory must obey
├── FACTORY_RULES.md         # How the factory operates - every workflow reads this
├── CLAUDE.md                # This file - code conventions
├── FACTORY.md               # The honest account of what the gate covers and the incident log
├── README.md                # Human-facing overview and quick start
├── virtualagent/
│   └── resources/           # THE DEFAULT WIKI and the samples. Every .md/.txt here is knowledge; production mounts a host folder here. README.md is not indexed
├── app/
│   ├── backend/
│   │   ├── main.py          # FastAPI app: lifespan builds the wiki index and wires the agent; /api/health, /api/version, /api/languages
│   │   ├── config.py        # Every env var read exactly once; every hardcoded constant
│   │   ├── languages.py     # THE supported set, names, voice locales, greetings, no-answer phrases, detection
│   │   ├── auth.py          # get_current_session: the bearer-token check every session route depends on
│   │   ├── rate_limit.py    # The 100 turns/client/24h cap. One number, one module
│   │   ├── agent/
│   │   │   ├── pipeline.py  # Agent.respond(): detect -> wiki -> web -> "I do not know". The order is code
│   │   │   ├── events.py    # The five event types one turn is made of
│   │   │   ├── prompts.py   # The system prompt and the two protocol markers
│   │   │   └── sentences.py # Incremental sentence splitter (what makes the agent live)
│   │   ├── wiki/index.py    # Read, chunk, index (BM25 + cosine, RRF), the confidence decision
│   │   ├── search/web.py    # Brave Search client; unavailable is a state, not an error
│   │   ├── sessions/store.py# In-process sessions and transcripts, 24h TTL
│   │   ├── llm/openrouter.py# The only inference client
│   │   ├── routes/sessions.py # POST /api/sessions, GET/DELETE /api/sessions/{id}, POST .../turns (SSE). The only file that knows the wire format
│   │   ├── tests/           # pytest; fakes at the provider boundary; fixtures/wiki is the test wiki
│   │   ├── pyproject.toml   # deps + ruff/mypy/pytest config
│   │   └── uv.lock
│   └── ios/
│       ├── project.yml      # XcodeGen spec
│       ├── README.md        # How to generate, run and what has NOT been verified
│       ├── VirtualAgent/    # App sources, one type per file
│       └── VirtualAgentTests/
├── harness/                 # The gate: ci.py (the ladder), static.py, unit.py, serve.py, stubs.py, e2e.py, mutations/
├── .factory/
│   ├── holdout/run.py       # Scenarios the builder is blocked from reading
│   ├── locks/floor.json     # The ratchet
│   └── decisions.md         # Product values the factory chose, and the questions it stopped to ask
├── deploy/                  # Dockerfile, docker-compose.yml (blue/green), Caddyfile, deploy.sh, .env.example
├── tools/dev-console/       # ONE static page to exercise the API from a desk: types or speaks, hears sentences, shows sources. A developer tool, NOT a client
├── tools/wiki/              # ingest.py: any document (Word, PDF, HTML, spreadsheet) -> the wiki's knowledge format. Its own uv project
├── scripts/factory-stop.sh  # The stop button
└── .archon/                 # Factory workflows and command files (config.yaml is gitignored: it holds a token)
```

**Placement rules** (where new code goes):

- New API routes → a new file in `app/backend/routes/`, one file per resource, mounted from `main.py` under the `/api` prefix. Every route on a session takes `Depends(get_current_session)`.
- New agent behaviour → `app/backend/agent/`. Keep detection (`languages.py`), retrieval (`wiki/`), search (`search/`) and composition (`agent/pipeline.py`) as separate modules with the protocol seams `pipeline.py` defines.
- New SSE event types → add the dataclass to `agent/events.py`, the encoder case to `routes/sessions.py`, the section to `docs/API.md`, and the decoder to `app/ios/VirtualAgent/Models.swift`, in the same PR.
- New source formats for the wiki → `tools/wiki/ingest.py`. The service reads `.md` and `.txt` only, on purpose; the converter does the rest and its dependencies never enter the service.
- New constants and env vars → `app/backend/config.py` only.
- New app screens or view models → `app/ios/VirtualAgent/`, one type per file, file named after the type.
- New app network calls → `app/ios/VirtualAgent/AgentAPI.swift` only. New SSE parsing → `SSEParser.swift` only. New user-facing strings → `Phrases.swift`, in all four languages.
- New wiki content → `virtualagent/resources/`. That is the only authoring surface; there is no upload path.
- The developer console (`tools/dev-console/index.html`) is for people testing the service at a desk. It is never deployed, never linked from the product, and never grows features the app does not have: MISSION.md forbids any client other than the iOS app, and this is not one.

---

## Running the Service

```bash
cd app/backend && uv sync --all-extras
```

```bash
cd app && uv --project backend run uvicorn backend.main:app --reload --port 8000
```

The service **must** be run from `app/` (not `app/backend/`): the `backend.main:app` import path requires it. Running from the wrong cwd gives `ModuleNotFoundError: No module named 'backend'`. The `--project backend` flag tells uv to use `app/backend/.venv` while cwd is `app/`.

Configuration is read from `app/.env` (gitignored; template at `app/backend/.env.example`) or the environment. `OPENROUTER_API_KEY` is required: the service refuses to import without it. Startup indexes the wiki, which calls the embeddings endpoint, so a bad key fails at boot rather than on the first turn. That is deliberate.

After startup the folder is **watched** (`WIKI_POLL_SECONDS`, default 10): a file added, edited or removed is re-indexed in the background, only its changed chunks are re-embedded, and the new index is swapped in atomically. To teach the running agent something, write a file into the folder; `/api/health` shows `wiki_indexed_at` moving. A rebuild that fails keeps the previous index and logs why.

To run without secrets or network, use the harness: `python harness/serve.py --port 8000` starts stub providers and points the service at them and at `harness/fixtures/wiki`.

To talk to it from a browser, serve `tools/dev-console/` on a fixed origin and allow that origin: `python -m http.server 8080 --directory tools/dev-console` with `CORS_ORIGINS=http://localhost:8080` in `app/.env` (or in the environment of `serve.py`). Chrome or Edge for the microphone; every browser speaks.

---

## Testing

**Service:**

```bash
cd app/backend
uv run pytest tests -xvs
```

All backend tool invocations run from `app/backend/` so `pyproject.toml` (ruff, mypy, pytest config) is picked up.

- `asyncio_mode = "auto"`: plain `async def` tests work.
- **Fakes sit at the provider boundary, never above it.** `conftest.py` provides `FakeLLM` (scripted replies, deterministic bag-of-words embeddings), `SpySearch` (records queries) and a `client` fixture that wires them into the real app over `httpx.ASGITransport`. The pipeline, the routes and the wiki index under test are the real ones. Do not mock `Agent`, `WikiIndex` or the routes.
- The test wiki is `tests/fixtures/wiki/`. Tests that need a specific document create a temp folder; do not add tests that depend on `virtualagent/resources/`.
- **Never hit the network from a test.** Use `respx` for httpx clients and the fakes for the model.
- Every bug fix ships a regression test that fails on `main` and passes on the branch. Every feature ships tests for its behaviour.

**App:** `VirtualAgentTests` is an XCTest target run from Xcode on a Mac (`Cmd+U`). The factory's machines have no Swift toolchain; `harness/static_ios.py` checks the manifests and the Swift files' balance only, and says so. A change to the app is verified by a person.

**The gate:**

```bash
python harness/ci.py --quick   # static + unit
python harness/ci.py           # the whole gate: + the API journey against a live process, the holdout, the mutation set
```

`python` must be a real 3.11 interpreter on PATH (on Windows the Store stub that prints "Python est introuvable" is not one). The full gate needs `uv` and nothing else: no secrets, no network.

---

## Lint, Format, Type Check

```bash
cd app/backend
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

Configured in `app/backend/pyproject.toml`: ruff line-length 100, target py311, rules E/F/W/I/B/UP/SIM/RUF (RUF001-003 ignored: the product speaks Arabic and its letters are not confusables); mypy lenient (`strict = false`, `warn_return_any = true`, `ignore_missing_imports = true`).

**Before every commit (what the validator runs):** `python harness/ci.py --quick`, and the full gate before requesting review.

---

## Code Conventions

### Python (service)

- **Async everywhere.** Routes are `async def`. Provider calls are awaited. Any sync blocking call in a request path is a bug; use `asyncio.to_thread` or do it at startup.
- **Imports:** stdlib, third-party, local, separated by blank lines. No wildcard imports. `from __future__ import annotations` at the top of every module.
- **Type hints** on every signature and return. `list[str]`, `dict[str, int]`, `X | None`; never `List`, `Optional`.
- **No `print()` in runtime code.** Module-level `logger = logging.getLogger(__name__)`. `print()` is fine in `harness/` and `.factory/`, whose contract is stdout.
- **Errors:** specific exceptions with clear messages. Never bare `except:`. `except Exception` only at the outermost boundary. A third-party failure mid-turn is logged and turned into "no results", never a 500: the agent must not crash mid-conversation.
- **Config:** every env var is read once in `config.py` and imported as a constant. Nothing else touches `os.environ`.
- **Pydantic models** for request bodies, defined in the route file that uses them.
- **Protocols at the seams.** `agent/pipeline.py` defines `ChatModel`, `WikiSearch` and `WebSearch` as `typing.Protocol`. New providers and fakes implement those; nothing imports a concrete client into the pipeline.
- **The wire format lives in one place.** Only `routes/sessions.py` encodes SSE. Only `agent/events.py` defines events.
- **Everything the agent says is spoken.** Fixed phrases (greetings, the no-answer phrase, the ask-for-a-language question) live in `languages.py`, per language, and are plain spoken prose: no markdown, no URLs.

### Swift (app)

- **SwiftUI, one type per file, file named after the type.** `@MainActor` on view models. Swift concurrency (`async`/`await`, `Task`) rather than callbacks.
- **All network calls go through `AgentAPI.swift`;** all SSE parsing through `SSEParser.swift`; all speech input through `SpeechInput.swift`; all speech output through `SpeechOutput.swift`. Views never touch `URLSession` or `AVSpeechSynthesizer`.
- **Every string the client sees or hears exists in all four languages** in `Phrases.swift`, keyed by the language code the service uses. No fifth language, no English-only fallback string outside `Phrases`.
- **Voice locales come from the service** (`voice_locale` on `language` and `sentence` events); the app never maps a language to a locale itself.
- **No third-party packages.** No `Package.swift` dependencies, no CocoaPods, no Carthage.
- **`Codable` models in `Models.swift` mirror `docs/API.md` field for field.** Unknown enum values decode to a safe case; the app must not crash on a new event.

---

## The Contract That Must Not Regress

These are the code-level shape of the MISSION.md hard invariants and the PRD's one adjective, "live". The gate (`harness/ci.py`), the holdout and the mutation set all probe them. Regressing any is an auto-reject.

1. **One definition of the language set.** `SUPPORTED_LANGUAGES` in `languages.py` is exactly `{"fr", "en", "de", "ar"}`; `LANGUAGE_NAMES`, `VOICE_LOCALES`, `GREETINGS` and `NO_ANSWER_TEXTS` have exactly those keys. Detection returns `None` rather than guessing.
2. **The order is code, not prompt.** `Agent.respond()` searches the wiki first, calls the web only when `is_confident()` is false or the model declined the excerpts, and says it does not know without consulting the model when both fail. The web is never called while the wiki has a confident answer.
3. **Every turn declares a source** from `{"wiki", "web", "none"}` and a kind from `{"answer", "question", "no_answer"}`. The model is never asked to answer from nothing.
4. **Every `/api/sessions/{session_id}/...` route depends on `get_current_session`.** 401 without a token, 404 unknown session, 403 wrong token, in that order.
5. **The cap is `DAILY_TURN_CAP = 100` over `WINDOW_HOURS = 24` in `rate_limit.py`** and is defined nowhere else. 429 carries `resets_at`.
6. **OpenRouter is the only inference provider.** `anthropic/claude-sonnet-4.6` for chat (overridable by `CHAT_MODEL` for canaries only), `openai/text-embedding-3-small` for embeddings. No other provider, no local model.
7. **The stream is live.** `sentence` events fire as each sentence completes, before the turn closes; the first sentence never waits for the last token. The SSE framing in `docs/API.md` is exact: tokens are unnamed `data:` frames carrying a JSON string, `language` comes first, `sources` and `turn` come before `data: [DONE]`. The app's parser depends on it.

---

## Environment Variables

All env var reads happen in `app/backend/config.py`.

| Variable | Required | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | **yes** | Chat completions and embeddings. The service refuses to start without it |
| `OPENROUTER_BASE_URL` | no | Default `https://openrouter.ai/api/v1`. The harness points it at the stub |
| `CHAT_MODEL` | no | Default `anthropic/claude-sonnet-4.6`. For canarying a model on the inactive colour only |
| `BRAVE_SEARCH_API_KEY` | no | The web fallback. Unset: the agent says it does not know when the wiki has nothing; `/api/health` reports `web_search: unconfigured` |
| `WEB_SEARCH_BASE_URL` | no | Default `https://api.search.brave.com/res/v1`. The harness points it at the stub |
| `WIKI_RESOURCES_DIR` | no | Default `<repo>/virtualagent/resources`. The image pins `/app/virtualagent/resources` and compose mounts the host's wiki folder there; the harness points it at its fixture wiki |
| `WIKI_POLL_SECONDS` | no | Default `10`. How often the wiki folder is checked for changes; `0` reads it once at startup |
| `CORS_ORIGINS` | no | Comma-separated browser origins. The iOS app needs none |

Everything else is a constant in `config.py` (top-k, the confidence tolerances, session TTL, history length). When adding configurability, add the constant there with a sensible default. **Never commit `.env` files.**

---

## Deployment

The service ships via Docker Compose to a VPS, blue/green behind Caddy. Source of truth is `deploy/`; the runbook is `deploy/README.md`. The real `.env` lives only on the host at `/opt/virtualagent/.env` and is never in git or in an LLM context.

- `deploy/Dockerfile` builds one image: the service plus a copy of `virtualagent/resources/` as the default wiki. **The live wiki is a folder on the host** (`WIKI_DIR` in the host `.env`), mounted read-only over that copy in both colours; a document dropped there is indexed within seconds with no image build and no flip. Code still deploys blue/green, with a healthcheck that only passes once the wiki is indexed.
- `app-blue` and `app-green` are identical except for name; neither publishes a host port; `deploy/upstream.conf` (gitignored, written by `deploy.sh`) names the live one.
- `deploy.sh` runs from a systemd timer on the host and is mirrored by hand; the copy here is the source of truth.
- Zero downtime is a hard requirement. Any change under `deploy/` must keep both colours, the healthcheck, the internal-only ports and the `import /etc/caddy/upstream.conf` line.

The factory's lane: inside the repo, inside the PR. `deploy/` is protected (FACTORY_RULES.md §5); deployment work is human-authored. If an issue needs a new secret, the workflow says so and a human adds it to the host's `.env`.

---

## Known Footguns

1. **Sessions and the turn counter are in process.** Run one uvicorn worker. A restart forgets every session (the PRD lists durability as not-yet); two workers would each count half the turns.
2. **Language detection is a heuristic.** Arabic by script; the three Latin-script languages by function words. A very short utterance with no function word ("Horaires ?") detects as nothing, and on a fresh session the agent asks for a language. That is the designed behaviour, and improving detection within the four languages is an allowed evolution.
3. **The sentence splitter splits on `.` followed by whitespace.** "e.g. this" becomes two sentences. "9.30" survives. Known, documented in `sentences.py`.
4. **The app has never been compiled.** It was written without a Mac. Expect API-availability and concurrency diagnostics on the first build; `app/ios/README.md` says exactly what has not been verified.
5. **On Windows, `python` may be the Store stub.** The harness scripts call `python`; put a real 3.11 first on PATH or the gate exits before it starts, with a message about the Microsoft Store.
6. **`harness/mutations/run.py` mutates in place and restores with git.** It refuses a dirty tree. If it is killed mid-defect, `git status` shows one modified file; `git checkout -- <file>` is the fix.

---

## Commit and PR Conventions

- **Commit messages:** conventional commits - `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`, `test:`. Subject under 72 characters. Body explains *why*.
- **PR title:** same prefix as the first commit, under 72 characters.
- **PR body:** must include `Fixes #N` (or `Closes #N` / `Resolves #N`) on its own line. Missing this fails validation.
- **New dependencies:** PR body must include a "Dependencies" section: what it does, why existing dependencies do not work, evidence of maintenance. See FACTORY_RULES.md §2.
- **One issue per PR.** File a new issue for anything else you notice.
- **A change to `docs/API.md` and a change to the app's models travel together.** The contract has two consumers.

---

## Dos and Don'ts

**Do:**
- Read MISSION.md and FACTORY_RULES.md before any non-trivial task
- Run `python harness/ci.py` before declaring a PR done
- Keep the language set in `languages.py`, the cap in `rate_limit.py`, the token check in `auth.py`, the wire format in `routes/sessions.py`
- Keep all app networking in `AgentAPI.swift` and all app strings in `Phrases.swift`
- Add tests for every bug fix and every feature, with fakes at the provider boundary

**Don't:**
- Modify `MISSION.md`, `FACTORY_RULES.md`, or `CLAUDE.md` - see FACTORY_RULES.md §5
- Modify `.github/`, `deploy/`, any `.env*`, `harness/`, or `.factory/`
- Add a language, remove one, or alias one
- Add an inference provider, change the embedding model, or add a local model
- Call the web before the wiki, or answer without a declared source
- Add a database, an ORM, accounts, or a second client
- Add a third-party Swift package
- Parse SSE anywhere but `SSEParser.swift` on the app or encode it anywhere but `routes/sessions.py` on the service
- "Improve" code that was not part of the issue - scope discipline is enforced by the validator

---

## Protected paths (factory auto-rejects PRs touching these)

The following implement or gate the hard invariants in `MISSION.md`. Any PR touching them must be human-authored:

- `app/backend/auth.py` - the session token check (MISSION invariant 4)
- `app/backend/rate_limit.py` - the cap and its window (MISSION invariant 5)
- `app/backend/languages.py` - the `SUPPORTED_LANGUAGES`, `LANGUAGE_NAMES` and `VOICE_LOCALES` definitions (MISSION invariant 1). Detection heuristics below them are an allowed evolution; a PR that changes those three names is not
- `app/backend/agent/pipeline.py` - the order in `Agent.respond()` and the source assignment in `_compose()` (MISSION invariants 2 and 3). The confidence decision it calls, in `wiki/index.py`, is an allowed evolution
- `app/backend/routes/sessions.py` - the `Depends(get_current_session)` on every session route and the 429 path
- `app/backend/main.py` - router registration and CORS middleware
- `app/backend/config.py` - the OpenRouter constants and `EMBEDDING_MODEL` (MISSION invariant 6)
- `app/backend/llm/openrouter.py` - the only inference client
- `deploy/**` - the blue/green stack; zero downtime depends on it
- `harness/**` and `.factory/**` - the gate, the holdout, the mutation set, the ratchet, the decisions log. A builder that can edit its own judge can pass it
- `scripts/factory-stop.sh` - the stop button
- `MISSION.md`, `FACTORY_RULES.md`, `CLAUDE.md`, `.github/**`, `.env*`, `.archon/config.yaml`
