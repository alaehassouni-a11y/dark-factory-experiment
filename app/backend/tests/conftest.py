"""Shared fixtures. Fakes sit at the provider boundary (model, embeddings, web search); the
pipeline, routes and wiki index under test are the real ones."""

from __future__ import annotations

import os
import re
import zlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path

# Config reads the environment once at import; set it before any backend import.
os.environ.setdefault("OPENROUTER_API_KEY", "test-not-a-real-key")
os.environ["WIKI_RESOURCES_DIR"] = str(Path(__file__).parent / "fixtures" / "wiki")

import httpx
import pytest

from backend import rate_limit
from backend.agent.pipeline import Agent
from backend.search.web import WebResult
from backend.sessions.store import store
from backend.wiki.index import WikiIndex

FIXTURE_WIKI = Path(__file__).parent / "fixtures" / "wiki"


def bag(text: str, dims: int = 256) -> list[float]:
    vec = [0.0] * dims
    for word in re.findall(r"\w+", text.lower()):
        vec[zlib.crc32(word.encode("utf-8")) % dims] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


class FakeLLM:
    """Replies come from `script`: a string, or a callable of the messages."""

    def __init__(
        self, script: str | Callable[[list[dict[str, str]]], str] = "Fixed reply."
    ) -> None:
        self.script = script
        self.calls: list[list[dict[str, str]]] = []
        self.embedded: list[str] = []  # every text sent to the embeddings endpoint

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [bag(t) for t in texts]

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        self.calls.append(messages)
        reply = self.script(messages) if callable(self.script) else self.script
        # Deltas of a few characters, so marker buffering and sentence splitting are exercised.
        for i in range(0, len(reply), 4):
            yield reply[i : i + 4]


class SpySearch:
    def __init__(self, available: bool = True, results: list[WebResult] | None = None) -> None:
        self.available = available
        self.results = (
            results
            if results is not None
            else [
                WebResult(
                    title="Example page", url="https://example.org/page", snippet="Example snippet."
                )
            ]
        )
        self.queries: list[tuple[str, str]] = []

    async def search(self, query: str, language: str) -> list[WebResult]:
        self.queries.append((query, language))
        return list(self.results)


@pytest.fixture(autouse=True)
def clean_state():
    rate_limit.reset()
    store.clear()
    yield
    rate_limit.reset()
    store.clear()


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM("We are open from nine to six, Monday to Saturday.")


@pytest.fixture
def search() -> SpySearch:
    return SpySearch()


@pytest.fixture
async def wiki(llm: FakeLLM) -> WikiIndex:
    return await WikiIndex.build(FIXTURE_WIKI, llm)


@pytest.fixture
def agent(wiki: WikiIndex, llm: FakeLLM, search: SpySearch) -> Agent:
    return Agent(wiki=wiki, llm=llm, search=search)


@pytest.fixture
async def client(agent: Agent, wiki: WikiIndex, search: SpySearch):
    from backend.main import app

    app.state.agent = agent
    app.state.wiki = wiki
    app.state.search = search
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def parse_sse(body: str) -> list[tuple[str | None, str]]:
    """(event name or None, raw data) per frame, in order."""
    frames: list[tuple[str | None, str]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event = None
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        frames.append((event, "\n".join(data_lines)))
    return frames
