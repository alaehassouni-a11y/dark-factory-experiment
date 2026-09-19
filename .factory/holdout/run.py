#!/usr/bin/env python3
"""HOLDOUT SCENARIOS for the Virtual Agent. The builder is blocked from reading this directory.

    .factory/holdout/run.py      <- here. Deny-listed per node, protected by the guard
    harness/                     <- NOT here. The builder reads everything in harness/

Everything under `harness/` sits inside the agent's optimisation loop: it can read those
checks, run them, and iterate until they are green. These assertions differ only in that
the builder never sees them, and that is the only honest reason to merge code nobody read.

═══════════════════════════════════════════════════════════════════════════════════════
WRITTEN 2026-09-03, BEFORE THE CODE. READ THIS BEFORE CITING A GREEN RESULT.
═══════════════════════════════════════════════════════════════════════════════════════

Rule 1 of a holdout is that it is written BEFORE the work, because a scenario written
after seeing the implementation is a description of the implementation. These were
written from `docs/virtualagent.prd.md` and `docs/API.md` on the day the PRD was
written, against module names that did not yet exist. The implementation was then built
until they passed. That is the property in the right order, and it is why the import
paths below are a contract rather than a description.

THE RULES THIS FILE FOLLOWS:

  1. COMPOSE. The dominant real failure is not cheating, it is feature isolation:
     components individually correct that never work together. Every scenario below
     asserts something no single unit test is positioned to see.
  2. Duplicate, do not import. Nothing here comes from `harness/` or from
     `app/backend/tests/`. The fakes below are deliberate copies of the shape the
     harness stubs have, not imports of them - importing the suite's fixtures would put
     this inside the same optimisation loop it exists to sit outside of.
  3. Assert the PROPERTY, not one algebraic consequence of it. A derived constant in a
     holdout is a second silent copy of a decision and it goes stale without anyone
     editing it.

Emits `HOLDOUT_PASSED scenarios=N assertions=M`.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND = ROOT / "app" / "backend"

# --- run under the backend's interpreter, not the harness's -------------------------
# `ci.py` invokes this with sys.executable, which is the top-level python. The app's
# dependencies live in app/backend/.venv. Re-exec once, here, under `uv run`.
#
# Unconditional rather than conditional-on-ImportError: a top-level environment that
# happens to have fastapi installed would otherwise run these scenarios against a
# DIFFERENT dependency set than the app uses, and pass or fail for reasons that have
# nothing to do with the product.
if os.environ.get("_HOLDOUT_REEXEC") != "1":
    _uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    _env = dict(os.environ, _HOLDOUT_REEXEC="1")
    sys.exit(subprocess.call([_uv, "run", "python", str(Path(__file__).resolve())],
                             cwd=BACKEND, env=_env))

# Duplicated from the harness deliberately - see rule 2. Placeholders; nothing below
# touches a network.
for _k, _v in {
    "OPENROUTER_API_KEY": "holdout-not-a-real-key",
    "WIKI_RESOURCES_DIR": str(ROOT / "virtualagent" / "resources"),
}.items():
    os.environ.setdefault(_k, _v)

# `backend` is a package under app/, so app/ is the import root - not app/backend/.
sys.path.insert(0, str(ROOT / "app"))

ASSERTIONS = 0
FAILURES: list[str] = []


def expect(name: str, ok: bool, detail: str = "") -> None:
    global ASSERTIONS
    ASSERTIONS += 1
    if not ok:
        FAILURES.append(f"{name}: {detail}")


# --- fakes at the provider boundary, the same boundary the product has ----------------
def _bag(text: str) -> list[float]:
    """A deterministic embedding: shared words give a positive cosine, nothing else does."""
    dims = 256
    vec = [0.0] * dims
    for word in re.findall(r"\w+", text.lower()):
        vec[zlib.crc32(word.encode("utf-8")) % dims] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


class FakeLLM:
    """Answers with a fixed reply and records every call, including the language it
    was asked to answer in, which the system prompt must state."""

    def __init__(self, reply: str = "Fixed reply.") -> None:
        self.reply = reply
        self.calls: list[list[dict]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_bag(t) for t in texts]

    async def stream(self, messages: list[dict]):
        self.calls.append(messages)
        for piece in self.reply.split(" "):
            yield piece + " "


class SpySearch:
    def __init__(self, available: bool = True, results: list | None = None) -> None:
        self.available = available
        self.results = results or []
        self.queries: list[str] = []

    async def search(self, query: str, language: str):
        self.queries.append(query)
        return list(self.results)


def _wiki_dir(docs: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp(prefix="holdout-wiki-"))
    for name, body in docs.items():
        (d / name).write_text(body, encoding="utf-8")
    return d


async def _collect(agent, session, text: str) -> list:
    return [e async for e in agent.respond(session, text)]


def _turn(events):
    from backend.agent.events import TurnEvent

    turns = [e for e in events if isinstance(e, TurnEvent)]
    return turns[-1] if turns else None


# ---------------------------------------------------------------------------
def scenario_the_wiki_is_asked_first_and_the_web_only_when_it_has_nothing() -> None:
    """MISSION hard invariant 2, composed across retrieval, the confidence decision, the
    fallback and the search client. A unit test of the retriever proves it ranks; a unit
    test of the fallback proves it calls search; neither can see that search is NOT
    called when the wiki was confident, because that only exists where the two meet."""
    from backend.agent.pipeline import Agent
    from backend.search.web import WebResult
    from backend.sessions.store import Session
    from backend.wiki.index import WikiIndex

    wiki = _wiki_dir({
        "opening-hours.md": "# Opening hours\n\nThe shop opening hours are nine to six, "
                            "Monday to Saturday. We are closed on Sunday.\n",
        "returns.md": "# Returns\n\nReturns are accepted within thirty days with a receipt.\n",
    })
    # Three sentences, streamed word by word by the fake: the reply is long enough that
    # "sentences arrive while the model is still talking" is observable rather than
    # true by construction. See the liveness assertions below.
    llm = FakeLLM("We are open nine to six. Monday to Saturday. We close on Sunday.")
    search = SpySearch(results=[WebResult(title="Cup", url="https://example.org/cup",
                                          snippet="France won the 1998 World Cup.")])
    index = asyncio.run(WikiIndex.build(wiki, llm))
    agent = Agent(wiki=index, llm=llm, search=search)

    covered = asyncio.run(_collect(agent, Session.new(client_id="c1"),
                                   "What are the shop opening hours?"))
    t = _turn(covered)
    expect("a wiki-covered question is answered from the wiki",
           t is not None and t.source == "wiki", f"turn={t}")
    expect("the web was NOT searched while the wiki had a confident answer",
           search.queries == [], f"queries={search.queries}")

    # --- the adjective the requirement uses is "live" --------------------------------
    # The app speaks each sentence as it completes. "A sentence event exists" and "a
    # sentence event precedes the turn event" are both true of an agent that buffers the
    # whole reply and emits every sentence at the end - that agent is mute until the last
    # token and the product it makes is not the product the PRD describes. The only
    # observable difference is POSITION IN THE STREAM: with the model still streaming,
    # a sentence must already have been handed over.
    from backend.agent.events import SentenceEvent, TokenEvent

    first_sentence = next((i for i, e in enumerate(covered) if isinstance(e, SentenceEvent)), -1)
    last_token = max((i for i, e in enumerate(covered) if isinstance(e, TokenEvent)), default=-1)
    expect("a sentence is emitted before the last token of the reply arrives",
           first_sentence >= 0 and last_token >= 0 and first_sentence < last_token,
           f"first sentence at {first_sentence}, last token at {last_token} of "
           f"{[type(e).__name__ for e in covered]}")
    indexes = [e.index for e in covered if isinstance(e, SentenceEvent)]
    expect("every sentence of the reply is handed over, numbered contiguously from zero",
           len(indexes) >= 2 and indexes == list(range(len(indexes))),
           f"sentence indexes={indexes}")

    uncovered = asyncio.run(_collect(agent, Session.new(client_id="c1"),
                                     "Who won the football world cup in 1998?"))
    t = _turn(uncovered)
    expect("an uncovered question falls back to the web", t is not None and t.source == "web",
           f"turn={t}")
    expect("the web was searched exactly once for it", len(search.queries) == 1,
           f"queries={search.queries}")

    # Neither has it: the agent says so, with source none, and the LLM is NOT consulted -
    # an LLM asked to answer from nothing is how a product starts inventing.
    calls_before = len(llm.calls)
    nothing = SpySearch(available=False)
    dry = Agent(wiki=index, llm=llm, search=nothing)
    none = asyncio.run(_collect(dry, Session.new(client_id="c1"),
                                "Who won the football world cup in 1998?"))
    t = _turn(none)
    expect("with no wiki answer and no web, the turn is no_answer with source none",
           t is not None and t.kind == "no_answer" and t.source == "none", f"turn={t}")
    expect("the model was not asked to answer from nothing",
           len(llm.calls) == calls_before, f"calls={len(llm.calls) - calls_before}")


# ---------------------------------------------------------------------------
def scenario_the_language_set_is_one_set_and_the_agent_follows_it() -> None:
    """MISSION hard invariant 1. The set, the voice locales and detection must agree,
    and an unsupported language must produce a question rather than an answer -
    composed through the assembled pipeline, not the detector alone."""
    from backend import languages
    from backend.agent.pipeline import Agent
    from backend.sessions.store import Session
    from backend.wiki.index import WikiIndex

    expect("the supported set is exactly fr, en, de, ar",
           set(languages.SUPPORTED_LANGUAGES) == {"fr", "en", "de", "ar"},
           f"set={sorted(languages.SUPPORTED_LANGUAGES)}")
    expect("every supported language has a voice locale and nothing else does",
           set(languages.VOICE_LOCALES) == set(languages.SUPPORTED_LANGUAGES),
           f"locales={sorted(languages.VOICE_LOCALES)}")

    samples = {
        "fr": "Bonjour, quels sont vos horaires d'ouverture s'il vous plaît ?",
        "en": "Hello, what are your opening hours please?",
        "de": "Hallo, wie sind Ihre Öffnungszeiten bitte?",
        "ar": "مرحبا، ما هي ساعات العمل لديكم؟",
    }
    for code, text in samples.items():
        d = languages.detect(text)
        expect(f"{code} is detected as {code}", d is not None and d.language == code,
               f"got {d}")
    expect("a language outside the set is not forced into it",
           languages.detect("¿Dónde está el baño, por favor?") is None,
           "Spanish was mapped onto a supported language")

    llm = FakeLLM("Should not be used.")
    index = asyncio.run(WikiIndex.build(_wiki_dir({"a.md": "# A\n\nSome content here.\n"}), llm))
    agent = Agent(wiki=index, llm=llm, search=SpySearch())
    session = Session.new(client_id="c2")
    events = asyncio.run(_collect(agent, session, "¿Dónde está el baño, por favor?"))
    t = _turn(events)
    expect("an undetectable language on a fresh session yields a question, not an answer",
           t is not None and t.kind == "question" and t.source == "none", f"turn={t}")
    expect("that question did not go through the model", llm.calls == [],
           f"calls={len(llm.calls)}")
    expect("the session did not adopt a language it could not detect",
           session.language is None, f"language={session.language}")


# ---------------------------------------------------------------------------
def scenario_every_session_route_is_guarded_and_tokens_do_not_cross() -> None:
    """MISSION hard invariant 4, asserted against the WIRED app rather than a decorator,
    then composed: two sessions, one token used on the other's transcript."""
    import httpx

    from backend.auth import get_current_session
    from backend.main import app

    def walk(entries, prefix: str = ""):
        """Every route the app will actually serve, (path, methods, dependency calls).

        FastAPI 0.141+ keeps an included router NESTED - an `_IncludedRouter` carrying
        `original_router` and the include prefix - instead of flattening its routes
        into `app.routes`; older versions flatten. Both shapes are walked. Adapted
        2026-09-04, the first time this ran against the real dependency set: the
        top level held three routes, all public, and every session route sat
        unexamined one level down. Only the count assertion below noticed. The
        assertions themselves are unchanged from the day they were written."""
        for r in entries:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                ctx = getattr(r, "include_context", None)
                yield from walk(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
                continue
            path = prefix + (getattr(r, "path", "") or "")
            if not path.startswith("/api"):
                continue
            dep = getattr(r, "dependant", None)
            calls = None if dep is None else frozenset(
                d.call for d in dep.dependencies if d.call is not None)
            yield (path, frozenset(getattr(r, "methods", None) or []), calls)

    routes = list(walk(app.routes))
    expect("the app actually assembled some API routes", len(routes) >= 6,
           f"found {len(routes)}")

    # The public surface is a WHITELIST. Asserting "turns are guarded" would pass while a
    # brand-new unguarded /api/sessions/{id}/export existed.
    public_allowed = {("/api/health", "GET"), ("/api/version", "GET"),
                      ("/api/languages", "GET"), ("/api/sessions", "POST")}
    unguarded = sorted({(p, m) for p, ms, calls in routes for m in ms
                        if calls is not None and not calls and m != "HEAD"
                        and (p, m) not in public_allowed})
    expect("no API route outside the known-public set is dependency-free", not unguarded,
           f"unguarded={unguarded}")

    # "Has at least one dependency" is not the invariant. A route whose guard was swapped
    # for a store lookup, or for a lookalike that 401s anonymous callers and then waves
    # any valid token through, still has dependencies. The invariant is that THE guard -
    # this object, the one `backend.auth` exports and `harness` cannot edit - is on every
    # route scoped to a session. Asserted by identity, so a same-named replacement fails.
    session_scoped = sorted({(p, m) for p, ms, calls in routes for m in ms
                             if p.startswith("/api/sessions/{session_id}") and m != "HEAD"})
    expect("the session-scoped surface is the three routes docs/API.md describes",
           len(session_scoped) >= 3,
           f"session-scoped routes={session_scoped}")
    ungoverned = sorted({(p, m) for p, ms, calls in routes for m in ms
                         if p.startswith("/api/sessions/{session_id}") and m != "HEAD"
                         and (calls is None or get_current_session not in calls)})
    expect("every session-scoped route depends on backend.auth.get_current_session itself",
           not ungoverned, f"without the real guard: {ungoverned}")

    async def cross() -> dict[str, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://holdout") as c:
            a = (await c.post("/api/sessions", json={"client_id": "A"})).json()
            b = (await c.post("/api/sessions", json={"client_id": "B"})).json()
            sid = a["session_id"]
            mine = {"Authorization": f"Bearer {a['session_token']}"}
            theirs = {"Authorization": f"Bearer {b['session_token']}"}
            body = {"text": "Bonjour, quels sont vos horaires d'ouverture ?"}
            out = {
                "read_own": (await c.get(f"/api/sessions/{sid}", headers=mine)).status_code,
                "read_other": (await c.get(f"/api/sessions/{sid}", headers=theirs)).status_code,
                "read_anon": (await c.get(f"/api/sessions/{sid}")).status_code,
                "turn_other": (await c.post(f"/api/sessions/{sid}/turns", json=body,
                                            headers=theirs)).status_code,
                "turn_anon": (await c.post(f"/api/sessions/{sid}/turns",
                                           json=body)).status_code,
                "delete_other": (await c.delete(f"/api/sessions/{sid}",
                                                headers=theirs)).status_code,
                "delete_anon": (await c.delete(f"/api/sessions/{sid}")).status_code,
            }
            # The rejected DELETEs must have rejected the DELETE, not just the response.
            out["still_there"] = (await c.get(f"/api/sessions/{sid}",
                                              headers=mine)).status_code
            return out

    r = asyncio.run(cross())
    expect("the owner can read its own session", r["read_own"] == 200, f"got {r['read_own']}")
    expect("another session's token cannot read it", r["read_other"] == 403,
           f"got {r['read_other']}")
    expect("no token cannot read it", r["read_anon"] == 401, f"got {r['read_anon']}")
    # Reading is half of invariant 4. CONTINUING someone else's conversation - burning
    # their cap, writing into their transcript - and ending it are the other half.
    expect("another session's token cannot speak on it", r["turn_other"] == 403,
           f"got {r['turn_other']}")
    expect("no token cannot speak on it", r["turn_anon"] == 401, f"got {r['turn_anon']}")
    expect("another session's token cannot delete it", r["delete_other"] == 403,
           f"got {r['delete_other']}")
    expect("no token cannot delete it", r["delete_anon"] == 401, f"got {r['delete_anon']}")
    expect("and after those refusals the session is still the owner's to read",
           r["still_there"] == 200, f"got {r['still_there']}")


# ---------------------------------------------------------------------------
def scenario_the_cap_is_one_number_and_only_one() -> None:
    """MISSION hard invariant 5, and the composed half nobody tests: SINGLE DEFINITION.
    A unit test asserting the constant passes happily while a second copy lives in a
    route module and is the one actually enforced."""
    from backend import rate_limit

    expect("the daily cap is 100", rate_limit.DAILY_TURN_CAP == 100,
           f"cap={rate_limit.DAILY_TURN_CAP}")
    expect("the window is 24 hours", rate_limit.WINDOW_HOURS == 24,
           f"window={rate_limit.WINDOW_HOURS}")

    pattern = re.compile(r"^\s*(?!#)\w*(?:DAILY_TURN_CAP|TURN_CAP|DAILY_CAP)\s*[:=]",
                         re.MULTILINE)
    definitions = []
    for py in BACKEND.rglob("*.py"):
        if {".venv", "tests", "__pycache__"} & set(py.parts):
            continue
        if pattern.search(py.read_text(encoding="utf-8", errors="replace")):
            definitions.append(str(py.relative_to(BACKEND)).replace("\\", "/"))
    expect("the cap is defined in exactly one module", definitions == ["rate_limit.py"],
           f"defined in {definitions}")


# ---------------------------------------------------------------------------
def scenario_every_turn_declares_a_source_from_the_closed_set() -> None:
    """MISSION hard invariant 3, composed over every path the pipeline has: covered,
    uncovered-with-web, uncovered-without-web, undetectable language. The set is
    closed and every path lands in it."""
    from backend.agent.pipeline import Agent
    from backend.search.web import WebResult
    from backend.sessions.store import Session
    from backend.wiki.index import WikiIndex

    llm = FakeLLM("Nine to six.")
    index = asyncio.run(WikiIndex.build(_wiki_dir({
        "hours.md": "# Hours\n\nOur opening hours are nine to six.\n"}), llm))
    web = SpySearch(results=[WebResult(title="T", url="https://example.org/t", snippet="S")])
    paths = {
        "covered": (Agent(wiki=index, llm=llm, search=web), "What are your opening hours?"),
        "uncovered+web": (Agent(wiki=index, llm=llm, search=web), "Who painted the Mona Lisa?"),
        "uncovered-web": (Agent(wiki=index, llm=llm, search=SpySearch(available=False)),
                          "Who painted the Mona Lisa?"),
        "undetectable": (Agent(wiki=index, llm=llm, search=web), "¿Dónde está el baño?"),
    }
    for name, (agent, text) in paths.items():
        t = _turn(asyncio.run(_collect(agent, Session.new(client_id="c3"), text)))
        expect(f"{name}: the turn carries a source from the closed set",
               t is not None and t.source in {"wiki", "web", "none"}, f"turn={t}")
        expect(f"{name}: the turn carries a kind from the closed set",
               t is not None and t.kind in {"answer", "question", "no_answer"}, f"turn={t}")


# ---------------------------------------------------------------------------
def scenario_openrouter_is_the_only_inference_provider() -> None:
    """MISSION hard invariant 6, and the half of it no unit test is positioned to see.

    A test of the client proves the client works against whatever it was pointed at. The
    invariant is about the SHAPE OF THE TREE: one provider, reached through one module,
    with the models that the rest of the product was tuned against. WIKI_MIN_SIMILARITY
    was measured with text-embedding-3-small; swap the embedding model and that number,
    and the confidence decision built on it, quietly mean nothing.

    The defaults are read from the SOURCE, not from the running config: this process, the
    harness and production all override the base URL, so the runtime value answers "what
    is this run pointed at", which is a different question from "what does the product
    ship pointed at"."""
    from urllib.parse import urlsplit

    from backend import config

    expect("the embedding model is the one the retrieval tuning was measured with",
           config.EMBEDDING_MODEL == "openai/text-embedding-3-small",
           f"EMBEDDING_MODEL={config.EMBEDDING_MODEL!r}")
    expect("the web fallback's research step runs on perplexity/sonar, through OpenRouter",
           config.WEB_SEARCH_MODEL == "perplexity/sonar",
           f"WEB_SEARCH_MODEL={config.WEB_SEARCH_MODEL!r}")

    source = (BACKEND / "config.py").read_text(encoding="utf-8")

    def declared_default(name: str) -> str | None:
        m = re.search(
            rf'{name}\s*:\s*str\s*=\s*os\.environ\.get\(\s*"{name}"\s*,\s*"([^"]*)"\s*\)',
            source)
        return m.group(1) if m else None

    chat_default = declared_default("CHAT_MODEL")
    expect("with no CHAT_MODEL override the product ships on anthropic/claude-sonnet-4.6",
           chat_default == "anthropic/claude-sonnet-4.6"
           and (os.environ.get("CHAT_MODEL") is not None or config.CHAT_MODEL == chat_default),
           f"declared default={chat_default!r}, runtime={config.CHAT_MODEL!r}")

    base_default = declared_default("OPENROUTER_BASE_URL")
    expect("the inference endpoint the product ships pointed at is openrouter.ai",
           base_default is not None and urlsplit(base_default).hostname == "openrouter.ai",
           f"declared default={base_default!r}")

    # One provider means one door. A second inference SDK anywhere in the service - even
    # a well-meaning "just for embeddings" - is a provider swap in progress.
    sdk = re.compile(
        r"^\s*(?:from|import)\s+(openai|anthropic|cohere|mistralai|groq|replicate|together|"
        r"google\.generativeai|google\.genai|vertexai|boto3|ollama|llama_cpp|ctransformers|"
        r"transformers|sentence_transformers|huggingface_hub)\b", re.MULTILINE)
    openai_importers: list[str] = []
    other_importers: list[str] = []
    for py in BACKEND.rglob("*.py"):
        if {".venv", "tests", "__pycache__"} & set(py.parts):
            continue
        rel = str(py.relative_to(BACKEND)).replace("\\", "/")
        found = set(sdk.findall(py.read_text(encoding="utf-8", errors="replace")))
        if "openai" in found:
            openai_importers.append(rel)
        for name in sorted(found - {"openai"}):
            other_importers.append(f"{rel}: {name}")
    expect("the OpenAI-compatible SDK is imported by exactly one module",
           sorted(openai_importers) == ["llm/openrouter.py"],
           f"imported by {sorted(openai_importers)}")
    expect("no second inference SDK is imported anywhere in the service",
           not other_importers, f"found {sorted(other_importers)}")


SCENARIOS = [
    scenario_the_wiki_is_asked_first_and_the_web_only_when_it_has_nothing,
    scenario_the_language_set_is_one_set_and_the_agent_follows_it,
    scenario_every_session_route_is_guarded_and_tokens_do_not_cross,
    scenario_the_cap_is_one_number_and_only_one,
    scenario_every_turn_declares_a_source_from_the_closed_set,
    scenario_openrouter_is_the_only_inference_provider,
]


def main() -> int:
    for fn in SCENARIOS:
        try:
            fn()
        except Exception as e:                                     # noqa: BLE001
            FAILURES.append(f"{fn.__name__} raised {type(e).__name__}: {e}")

    if FAILURES:
        for f in FAILURES:
            print(f"  HOLDOUT_FAIL  {f}", flush=True)
        print(f"HOLDOUT_FAILED scenarios={len(SCENARIOS)} assertions={ASSERTIONS} "
              f"failures={len(FAILURES)}", flush=True)
        return 1

    print(f"HOLDOUT_PASSED scenarios={len(SCENARIOS)} assertions={ASSERTIONS}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
