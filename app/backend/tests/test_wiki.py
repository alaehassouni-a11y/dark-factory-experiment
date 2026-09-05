from __future__ import annotations

from pathlib import Path

from backend.wiki.index import WikiIndex, chunk_document
from conftest import FakeLLM


async def test_build_reads_every_document_except_readme(wiki: WikiIndex) -> None:
    assert wiki.document_count == 3
    assert wiki.chunk_count >= 3
    assert all(c.location != "README.md" for c in wiki.chunks)
    assert {c.title for c in wiki.chunks} == {"Opening hours", "Returns policy", "Livraison"}


async def test_covered_question_ranks_the_right_document_and_is_confident(wiki: WikiIndex) -> None:
    hits = await wiki.search("What are the shop opening hours?")
    assert hits
    assert hits[0].chunk.location == "opening-hours.md"
    assert wiki.is_confident(hits)


async def test_french_question_matches_french_document(wiki: WikiIndex) -> None:
    hits = await wiki.search("La livraison est-elle gratuite ?")
    assert hits[0].chunk.location == "livraison.md"
    assert wiki.is_confident(hits)


async def test_uncovered_question_is_not_confident(wiki: WikiIndex) -> None:
    hits = await wiki.search("Who painted the Mona Lisa in Florence?")
    assert not wiki.is_confident(hits)


async def test_empty_folder_indexes_nothing(tmp_path: Path) -> None:
    index = await WikiIndex.build(tmp_path / "missing", FakeLLM())
    assert index.document_count == 0
    assert await index.search("anything") == []
    assert not index.is_confident([])


def test_chunk_document_splits_on_headings_and_keeps_them() -> None:
    body = "# Title\n\nIntro paragraph.\n\n## Part A\n\nA text.\n\n## Part B\n\nB text.\n"
    chunks = chunk_document("Title", "t.md", body)
    assert [c.text for c in chunks] == [
        "Title\nIntro paragraph.",
        "Part A\nA text.",
        "Part B\nB text.",
    ]
    assert [c.index for c in chunks] == [0, 1, 2]


def test_chunk_document_packs_paragraphs_to_target_size() -> None:
    paragraph = "word " * 100
    body = "\n\n".join([paragraph] * 4)
    chunks = chunk_document("T", "t.md", body)
    assert len(chunks) == 4
    assert all(len(c.text) <= 800 for c in chunks)
