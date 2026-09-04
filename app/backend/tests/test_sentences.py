from __future__ import annotations

from backend.agent.sentences import SentenceSplitter


def test_emits_sentences_as_they_complete() -> None:
    s = SentenceSplitter()
    assert s.feed("We open at nine") == []
    assert s.feed(". We close") == ["We open at nine."]
    assert s.feed(" at six! ") == ["We close at six!"]
    assert s.flush() == []


def test_decimal_points_do_not_split() -> None:
    s = SentenceSplitter()
    assert s.feed("Delivery costs 9.50 euros today. ") == ["Delivery costs 9.50 euros today."]


def test_arabic_question_mark_and_newlines_are_boundaries() -> None:
    s = SentenceSplitter()
    assert s.feed("هل يمكنني المساعدة؟ نعم\nبالتأكيد") == ["هل يمكنني المساعدة؟", "نعم"]
    assert s.flush() == ["بالتأكيد"]


def test_flush_returns_the_unterminated_tail_once() -> None:
    s = SentenceSplitter()
    s.feed("Open nine to six")
    assert s.flush() == ["Open nine to six"]
    assert s.flush() == []
