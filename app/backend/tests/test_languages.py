from __future__ import annotations

import pytest

from backend import languages


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bonjour, quels sont vos horaires d'ouverture s'il vous plaît ?", "fr"),
        ("Hello, what are your opening hours please?", "en"),
        ("Hallo, wie sind Ihre Öffnungszeiten bitte?", "de"),
        ("مرحبا، ما هي ساعات العمل لديكم؟", "ar"),
        ("Je voudrais retourner un article", "fr"),
        ("Ich möchte einen Artikel zurückgeben", "de"),
        ("I would like to return an item", "en"),
    ],
)
def test_detects_each_supported_language(text: str, expected: str) -> None:
    d = languages.detect(text)
    assert d is not None
    assert d.language == expected
    assert 0.0 < d.confidence <= 1.0


@pytest.mark.parametrize(
    "text",
    ["¿Dónde está el baño, por favor?", "", "   ", "12345 67", "Missä on kirjasto?"],
)
def test_returns_none_without_evidence(text: str) -> None:
    assert languages.detect(text) is None


def test_arabic_wins_on_script_even_with_latin_words() -> None:
    d = languages.detect("مرحبا hello ما هي ساعات العمل")
    assert d is not None
    assert d.language == "ar"


def test_supported_set_and_locales_agree() -> None:
    assert set(languages.SUPPORTED_LANGUAGES) == {"fr", "en", "de", "ar"}
    assert set(languages.VOICE_LOCALES) == set(languages.SUPPORTED_LANGUAGES)
    assert set(languages.GREETINGS) == set(languages.SUPPORTED_LANGUAGES)
    assert set(languages.NO_ANSWER_TEXTS) == set(languages.SUPPORTED_LANGUAGES)


def test_payload_is_sorted_and_complete() -> None:
    payload = languages.supported_languages_payload()
    assert [p["code"] for p in payload] == ["ar", "de", "en", "fr"]
    assert all({"code", "name", "voice_locale"} <= set(p) for p in payload)


def test_tokenize_strips_latin_diacritics_and_keeps_arabic() -> None:
    assert languages.tokenize("Öffnungszeiten été") == ["offnungszeiten", "ete"]
    assert languages.tokenize("ساعات العمل") == ["ساعات", "العمل"]
