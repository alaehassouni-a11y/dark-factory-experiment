from __future__ import annotations

from backend.agent.events import LanguageEvent, SentenceEvent, SourcesEvent, TokenEvent, TurnEvent
from backend.agent.pipeline import Agent
from backend.agent.prompts import NO_ANSWER_MARKER, QUESTION_MARKER
from backend.languages import ASK_LANGUAGE_TEXT, NO_ANSWER_TEXTS
from backend.sessions.store import Session
from backend.wiki.index import WikiIndex
from conftest import FakeLLM, SpySearch


async def run(agent: Agent, session: Session, text: str) -> list:
    return [e async for e in agent.respond(session, text)]


def last_turn(events: list) -> TurnEvent:
    return [e for e in events if isinstance(e, TurnEvent)][-1]


async def test_covered_question_is_answered_from_the_wiki(agent: Agent, search: SpySearch) -> None:
    session = Session.new("c")
    events = await run(agent, session, "What are the shop opening hours?")
    assert isinstance(events[0], LanguageEvent)
    assert events[0].language == "en" and events[0].voice_locale == "en-US"
    turn = last_turn(events)
    assert turn.kind == "answer" and turn.source == "wiki"
    assert turn.text == "We are open from nine to six, Monday to Saturday."
    assert search.queries == []
    sources = next(e for e in events if isinstance(e, SourcesEvent))
    assert sources.sources[0].kind == "wiki"
    assert sources.sources[0].location == "opening-hours.md"
    assert [e.text for e in events if isinstance(e, SentenceEvent)] == [
        "We are open from nine to six, Monday to Saturday."
    ]
    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == turn.text
    assert session.language == "en"
    assert [t.role for t in session.turns] == ["client", "agent"]


async def test_sentences_stream_before_the_turn_ends(wiki: WikiIndex, search: SpySearch) -> None:
    llm = FakeLLM("First sentence. Second one! Third?")
    agent = Agent(wiki=wiki, llm=llm, search=search)
    events = await run(agent, Session.new("c"), "What are the shop opening hours?")
    sentences = [e for e in events if isinstance(e, SentenceEvent)]
    assert [s.text for s in sentences] == ["First sentence.", "Second one!", "Third?"]
    assert [s.index for s in sentences] == [0, 1, 2]
    assert events.index(sentences[0]) < events.index(last_turn(events))


async def test_uncovered_question_falls_back_to_the_web(agent: Agent, search: SpySearch) -> None:
    events = await run(agent, Session.new("c"), "Wer hat die Mona Lisa gemalt?")
    turn = last_turn(events)
    assert turn.source == "web" and turn.language == "de"
    assert search.queries == [("Wer hat die Mona Lisa gemalt?", "de")]
    sources = next(e for e in events if isinstance(e, SourcesEvent))
    assert sources.sources[0].kind == "web" and sources.sources[0].url == "https://example.org/page"


async def test_model_declining_the_wiki_moves_on_to_the_web(
    wiki: WikiIndex, search: SpySearch
) -> None:
    def script(messages: list[dict[str, str]]) -> str:
        return NO_ANSWER_MARKER if "Wiki excerpts" in messages[0]["content"] else "From the web."

    llm = FakeLLM(script)
    agent = Agent(wiki=wiki, llm=llm, search=search)
    events = await run(agent, Session.new("c"), "What are the shop opening hours on Christmas?")
    turn = last_turn(events)
    assert turn.source == "web" and turn.text == "From the web."
    assert len(llm.calls) == 2
    assert not any(NO_ANSWER_MARKER in e.text for e in events if isinstance(e, TokenEvent))


async def test_model_may_ask_a_clarifying_question(wiki: WikiIndex, search: SpySearch) -> None:
    llm = FakeLLM(f"{QUESTION_MARKER} Which day do you mean?")
    agent = Agent(wiki=wiki, llm=llm, search=search)
    events = await run(agent, Session.new("c"), "What are the shop opening hours?")
    turn = last_turn(events)
    assert turn.kind == "question" and turn.source == "wiki"
    assert turn.text == "Which day do you mean?"
    assert QUESTION_MARKER not in "".join(e.text for e in events if isinstance(e, TokenEvent))


async def test_no_wiki_and_no_web_says_so_without_the_model(wiki: WikiIndex) -> None:
    llm = FakeLLM("must not be used")
    agent = Agent(wiki=wiki, llm=llm, search=SpySearch(available=False))
    events = await run(agent, Session.new("c"), "Qui a peint la Joconde ?")
    turn = last_turn(events)
    assert turn.kind == "no_answer" and turn.source == "none" and turn.language == "fr"
    assert turn.text == NO_ANSWER_TEXTS["fr"]
    assert llm.calls == []


async def test_web_with_no_results_also_says_so(wiki: WikiIndex) -> None:
    llm = FakeLLM("must not be used")
    agent = Agent(wiki=wiki, llm=llm, search=SpySearch(results=[]))
    events = await run(agent, Session.new("c"), "من رسم الموناليزا؟")
    turn = last_turn(events)
    assert turn.source == "none" and turn.text == NO_ANSWER_TEXTS["ar"]


async def test_undetectable_language_on_a_fresh_session_asks_in_english(
    agent: Agent, llm: FakeLLM
) -> None:
    session = Session.new("c")
    events = await run(agent, session, "¿Dónde está el baño?")
    assert events[0] == LanguageEvent(language=None, voice_locale=None, confidence=0.0)
    turn = last_turn(events)
    assert turn.kind == "question" and turn.source == "none" and turn.text == ASK_LANGUAGE_TEXT
    assert session.language is None
    assert llm.calls == []


async def test_undetectable_text_keeps_the_session_language(agent: Agent) -> None:
    session = Session.new("c", language="fr")
    events = await run(agent, session, "12345")
    assert isinstance(events[0], LanguageEvent)
    assert events[0].language == "fr" and events[0].confidence == 0.0
    assert last_turn(events).language == "fr"


async def test_the_model_sees_history_and_the_language_instruction(
    agent: Agent, llm: FakeLLM
) -> None:
    session = Session.new("c")
    await run(agent, session, "What are the shop opening hours?")
    await run(agent, session, "Et le dimanche, quels sont les horaires d'ouverture ?")
    messages = llm.calls[-1]
    assert messages[0]["role"] == "system" and "Reply ONLY in French" in messages[0]["content"]
    assert [m["role"] for m in messages[1:]] == ["user", "assistant", "user"]
    assert messages[1]["content"] == "What are the shop opening hours?"


async def test_a_document_matched_by_several_passages_is_named_once(tmp_path) -> None:
    """The model sees every excerpt; the client hears each source once. A long document
    with several matching sections used to be listed once per section."""
    from pathlib import Path

    from backend.sessions.store import Session

    root = Path(tmp_path)
    (root / "watering.md").write_text(
        "# Watering a bonsai\n\n## When\n\nWater the bonsai when the soil is dry.\n\n"
        "## How\n\nWater the bonsai thoroughly.\n\n## Why\n\nA bonsai in a small pot dries fast.\n",
        encoding="utf-8",
    )
    llm = FakeLLM("Water it when the soil is dry.")
    index = await WikiIndex.build(root, llm)
    agent = Agent(wiki=index, llm=llm, search=SpySearch())
    events = [
        e async for e in agent.respond(Session.new(client_id="c"), "How do I water a bonsai?")
    ]
    sources = next(e for e in events if isinstance(e, SourcesEvent)).sources
    assert [s.location for s in sources] == ["watering.md"]
    assert len(llm.calls[0][0]["content"].split("[Watering a bonsai - watering.md]")) > 2, (
        "the model still receives every matching passage"
    )
