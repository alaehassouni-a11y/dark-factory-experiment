from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

import ingest

TODAY = dt.date(2026, 9, 6)


def test_markdown_with_one_title_is_kept_whole(tmp_path: Path) -> None:
    src = tmp_path / "hours.md"
    src.write_text("# Opening hours\n\nNine to six.\n\n## Sunday\n\nClosed.\n", encoding="utf-8")
    docs = ingest.import_file(src, today=TODAY)
    assert [d.title for d in docs] == ["Opening hours"]
    assert docs[0].body.startswith(
        "<!-- imported from: hours.md on 2026-09-06 by tools/wiki/ingest.py -->\n# Opening hours\n"
    )
    assert docs[0].sections == 1


def test_several_titles_become_one_file_per_topic(tmp_path: Path) -> None:
    src = tmp_path / "faq.md"
    src.write_text(
        "Intro line.\n\n# Delivery\n\nTwo days.\n\n# Returns\n\nThirty days.\n", encoding="utf-8"
    )
    docs = ingest.import_file(src, today=TODAY)
    assert [d.title for d in docs] == ["Delivery", "Returns"]
    assert "Intro line." in docs[0].body, "the preamble travels with the first topic"
    assert "Thirty days." in docs[1].body


def test_no_split_keeps_one_file_and_demotes_later_titles(tmp_path: Path) -> None:
    src = tmp_path / "faq.md"
    src.write_text("# Delivery\n\nTwo days.\n\n# Returns\n\nThirty days.\n", encoding="utf-8")
    docs = ingest.import_file(src, split=False, today=TODAY)
    assert len(docs) == 1
    assert "\n## Returns\n" in docs[0].body


def test_plain_text_without_headings_gets_a_title_from_the_filename(tmp_path: Path) -> None:
    src = tmp_path / "delivery_times.txt"
    src.write_text(
        "We deliver within two working days.\r\n\r\n\r\n\r\nExpress is next day.\r\n",
        encoding="utf-8",
    )
    docs = ingest.import_file(src, today=TODAY)
    assert docs[0].title == "Delivery times"
    body = docs[0].body
    assert (
        "# Delivery times\n\nWe deliver within two working days.\n\nExpress is next day.\n" in body
    )
    assert "\r" not in body and "\n\n\n" not in body


def test_links_images_and_html_are_reduced_to_spoken_text() -> None:
    raw = "# T\n\nSee [our shop](https://x.example/shop) ![logo](l.png) <br> today.<b>Now</b>\n\nPage 3 of 9\n"
    out = ingest.clean(raw)
    assert " ".join(out.split()) == "# T See our shop today.Now"
    assert "http" not in out and "<" not in out and "Page 3" not in out
    assert "\n\n\n" not in out


def test_html_goes_through_the_converter(tmp_path: Path) -> None:
    src = tmp_path / "hours.html"
    src.write_text(
        "<html><body><h1>Horaires</h1><p>Ouvert de 9h à 18h.</p><h2>Dimanche</h2><p>Fermé.</p></body></html>",
        encoding="utf-8",
    )
    docs = ingest.import_file(src, today=TODAY)
    assert docs[0].title == "Horaires"
    assert "Ouvert de 9h à 18h." in docs[0].body
    assert "## Dimanche" in docs[0].body


def test_slugify_is_ascii_and_stable() -> None:
    assert ingest.slugify("Horaires d'ouverture") == "horaires-d-ouverture"
    assert ingest.slugify("Öffnungszeiten & Lieferung") == "offnungszeiten-lieferung"
    assert ingest.slugify("ساعات العمل") == "document"


def test_cli_writes_files_and_refuses_to_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "in" / "hours.md"
    src.parent.mkdir()
    src.write_text("# Opening hours\n\nNine to six.\n", encoding="utf-8")
    out = tmp_path / "wiki"
    assert ingest.main([str(src.parent), "--out", str(out)]) == 0
    assert (
        (out / "opening-hours.md")
        .read_text(encoding="utf-8")
        .startswith("<!-- imported from: hours.md")
    )
    assert "IMPORT_DONE written=1" in capsys.readouterr().out

    assert ingest.main([str(src), "--out", str(out)]) == 0
    assert "exists" in capsys.readouterr().out
    assert ingest.main([str(src), "--out", str(out), "--force"]) == 0
    assert "wrote" in capsys.readouterr().out


def test_cli_skips_unsupported_and_readme(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "README.md").write_text("# readme\n", encoding="utf-8")
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8")
    assert ingest.main([str(tmp_path), "--out", str(tmp_path / "wiki"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "a README is not knowledge" in out and "unsupported" in out
    assert "IMPORT_DONE written=0 skipped=2 failed=0 (dry run)" in out
