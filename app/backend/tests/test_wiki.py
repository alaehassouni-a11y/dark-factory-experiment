from __future__ import annotations

from pathlib import Path

from backend.wiki.index import WikiIndex, chunk_document, content_stems, stem
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


async def test_paraphrased_question_still_matches_the_document(tmp_path: Path) -> None:
    """The client does not use the document's words. Inflections (garantie / garantis,
    produits / produit) and question words (combien de temps dure) must not hide it."""
    (tmp_path / "garantie.md").write_text(
        "# Garantie des produits\n\nTous nos produits sont garantis deux ans. "
        "La reparation est gratuite en magasin.\n",
        encoding="utf-8",
    )
    (tmp_path / "horaires.md").write_text(
        "# Horaires\n\nNous sommes ouverts de neuf heures a dix-huit heures.\n", encoding="utf-8"
    )
    index = await WikiIndex.build(tmp_path, FakeLLM())
    for question in (
        "Combien de temps dure la garantie de vos produits ?",
        "Quelle est la durée de la garantie ?",
        "Est-ce que le produit est garanti ?",
        "Y a-t-il une garantie ?",
        "A quelle heure ouvrez-vous ?",
    ):
        hits = await index.search(question)
        assert hits and index.is_confident(hits), question
    assert (await index.search("Combien de temps dure la garantie ?"))[
        0
    ].chunk.location == "garantie.md"
    assert (await index.search("A quelle heure ouvrez-vous ?"))[0].chunk.location == "horaires.md"
    unrelated = await index.search("Qui a peint la Joconde ?")
    assert not index.is_confident(unrelated)


def test_stems_merge_inflections_in_the_four_languages() -> None:
    assert stem("garantie") == stem("garantis") == stem("garanti")
    assert stem("produits") == stem("produit")
    assert stem("hours") == stem("hour")
    assert stem("offnungszeiten") == stem("offnungszeit")
    assert stem("ساعات") == stem("ساعة") == stem("الساعات")
    assert stem("open") == "open" and stem("bus") == "bus", "short words are left alone"


def test_content_stems_drop_question_words_and_tiny_tokens() -> None:
    assert content_stems(["combien", "de", "temps", "dure", "la", "garantie"]) == [
        "temp",
        "dure",
        "garant",
    ]
    assert content_stems(["y", "a", "t", "il", "une", "garantie"]) == ["garant"]
    assert content_stems(["how", "long", "is", "the", "warranty"]) == ["warran"]
    assert content_stems(["كم", "ساعات", "العمل"]) == ["ساع", "عمل"]


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
