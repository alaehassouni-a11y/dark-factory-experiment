"""The wiki is a folder, not part of the code: a file dropped into it is knowledge within
one poll interval, with no restart. These tests drive `reindex_if_changed` directly rather
than waiting on the poll timer."""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest

from backend.main import app, reindex_if_changed
from backend.wiki.index import WikiIndex, folder_signature
from conftest import FakeLLM, parse_sse


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    # Make sure the mtime moves even on filesystems with coarse timestamps.
    stamp = time.time() + 2
    os.utime(path, (stamp, stamp))


def test_signature_changes_only_when_wiki_files_change(tmp_path: Path) -> None:
    empty = folder_signature(tmp_path)
    _write(tmp_path / "hours.md", "# Hours\n\nNine to six.\n")
    one = folder_signature(tmp_path)
    assert one != empty
    assert folder_signature(tmp_path) == one, "no change, same signature"
    _write(tmp_path / "README.md", "# not indexed\n")
    _write(tmp_path / "notes.pdf", "not a wiki format")
    assert folder_signature(tmp_path) == one, "README and unknown formats do not count"
    _write(tmp_path / "hours.md", "# Hours\n\nNine to seven.\n")
    assert folder_signature(tmp_path) != one, "an edit counts"
    (tmp_path / "hours.md").unlink()
    assert folder_signature(tmp_path) == empty, "removal counts"


async def test_rebuild_reuses_embeddings_of_unchanged_chunks(tmp_path: Path) -> None:
    llm = FakeLLM()
    _write(tmp_path / "a.md", "# A\n\nAlpha text.\n")
    _write(tmp_path / "b.md", "# B\n\nBeta text.\n")
    first = await WikiIndex.build(tmp_path, llm)
    sent = len(llm.embedded)
    assert sent == 2
    _write(tmp_path / "c.md", "# C\n\nGamma text.\n")
    second = await WikiIndex.build(tmp_path, llm, previous=first)
    assert second.document_count == 3
    assert llm.embedded[sent:] == ["C\nGamma text."], "only the new chunk was embedded"
    assert second.signature != first.signature


@pytest.fixture
async def live(tmp_path: Path):
    """The real app wired to a temporary, initially one-document wiki."""
    llm = FakeLLM("Answered from the wiki.")
    _write(tmp_path / "hours.md", "# Opening hours\n\nWe are open nine to six.\n")
    index = await WikiIndex.build(tmp_path, llm)
    from backend.agent.pipeline import Agent
    from conftest import SpySearch

    app.state.wiki = index
    app.state.wiki_root = tmp_path
    app.state.search = SpySearch()
    app.state.agent = Agent(wiki=index, llm=llm, search=app.state.search)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, llm, tmp_path


async def test_a_dropped_file_becomes_knowledge_without_a_restart(live) -> None:
    client, llm, folder = live
    before = (await client.get("/api/health")).json()
    assert before["wiki_documents"] == 1

    assert await reindex_if_changed(app, llm) is False, "nothing changed yet"

    _write(folder / "returns.md", "# Returns policy\n\nReturns are accepted within thirty days.\n")
    assert await reindex_if_changed(app, llm) is True

    after = (await client.get("/api/health")).json()
    assert after["wiki_documents"] == 2
    assert after["wiki_indexed_at"] >= before["wiki_indexed_at"]

    session = (await client.post("/api/sessions", json={"client_id": "c"})).json()
    r = await client.post(
        f"/api/sessions/{session['session_id']}/turns",
        json={"text": "What is your returns policy?"},
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    frames = parse_sse(r.text)
    turn = next(d for n, d in frames if n == "turn")
    sources = next(d for n, d in frames if n == "sources")
    assert '"source": "wiki"' in turn
    assert "returns.md" in sources


async def test_a_failed_rebuild_keeps_the_previous_index(live, monkeypatch) -> None:
    client, llm, folder = live

    async def boom(*args, **kwargs):
        raise RuntimeError("embeddings provider had a bad minute")

    monkeypatch.setattr(WikiIndex, "build", classmethod(lambda cls, *a, **k: boom()))
    _write(folder / "new.md", "# New\n\nNew text.\n")
    assert await reindex_if_changed(app, llm) is False
    assert (await client.get("/api/health")).json()["wiki_documents"] == 1
