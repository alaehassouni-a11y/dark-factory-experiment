"""The agent: one client utterance in, one stream of events out.

    detect the language
      -> ask for a supported language if there is none to detect and none to keep
    search the wiki
      -> confident: compose from the wiki
    otherwise search the web
      -> results: compose from the web
    otherwise say so, in the client's language, without asking the model

The ORDER is MISSION hard invariant 2 and it is code here, not a prompt. The model is
only ever asked to compose from something that was retrieved; it is never asked to
answer from nothing (hard invariant 3).

The provider boundary is three small protocols (wiki, model, search) so the harness and
the holdout can compose the real pipeline with fakes at exactly the seam production has.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable
from typing import Protocol

from backend.agent.events import (
    Event,
    LanguageEvent,
    SentenceEvent,
    Source,
    SourcesEvent,
    TokenEvent,
    TurnEvent,
    TurnKind,
    TurnSource,
)
from backend.agent.prompts import NO_ANSWER_MARKER, QUESTION_MARKER, system_prompt
from backend.agent.sentences import SentenceSplitter
from backend.config import HISTORY_TURNS
from backend.languages import ASK_LANGUAGE_TEXT, NO_ANSWER_TEXTS, detect, voice_locale
from backend.search.web import WebResult
from backend.sessions.store import Session, Turn
from backend.wiki.index import Hit

logger = logging.getLogger(__name__)

# The longest marker, so the pipeline knows how much to buffer before it can rule one out.
_MARKER_PROBE = max(len(NO_ANSWER_MARKER), len(QUESTION_MARKER))


class ChatModel(Protocol):
    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


class WikiSearch(Protocol):
    async def search(self, query: str, top_k: int | None = None) -> list[Hit]: ...
    def is_confident(self, hits: list[Hit]) -> bool: ...


class WebSearch(Protocol):
    @property
    def available(self) -> bool: ...
    async def search(self, query: str, language: str) -> list[WebResult]: ...


class _NoAnswer(Exception):
    """The model declined the context; the pipeline moves to the next source."""


class Agent:
    def __init__(self, wiki: WikiSearch, llm: ChatModel, search: WebSearch) -> None:
        self.wiki = wiki
        self.llm = llm
        self.search = search

    async def respond(self, session: Session, text: str) -> AsyncIterator[Event]:
        detection = detect(text)
        if detection is not None:
            language: str | None = detection.language
            confidence = detection.confidence
        else:
            language = session.language
            confidence = 0.0

        session.turns.append(Turn(role="client", text=text, language=language))

        if language is None:
            # Nothing to detect and nothing to keep: the agent asks, in English, which is
            # the one case the API contract allows a null language for.
            yield LanguageEvent(language=None, voice_locale=None, confidence=0.0)
            async for ev in self._fixed_turn(
                session, ASK_LANGUAGE_TEXT, "en", kind="question", source="none"
            ):
                yield ev
            return

        session.language = language
        yield LanguageEvent(
            language=language, voice_locale=voice_locale(language), confidence=confidence
        )

        # 1. The wiki, first, always.
        hits = await self.wiki.search(text)
        if self.wiki.is_confident(hits):
            context = "\n\n".join(
                f"[{h.chunk.title} - {h.chunk.location}]\n{h.chunk.text}" for h in hits
            )
            sources = _unique(
                Source(
                    kind="wiki",
                    title=h.chunk.title,
                    location=h.chunk.location,
                    snippet=_snippet(h.chunk.text),
                )
                for h in hits
            )
            try:
                async for ev in self._compose(session, language, "wiki", context, sources):
                    yield ev
                return
            except _NoAnswer:
                logger.info("wiki excerpts retrieved but declined by the model; trying the web")

        # 2. The web, only when the wiki had nothing confident.
        if self.search.available:
            results = await self.search.search(text, language)
            if results:
                context = "\n\n".join(f"[{r.title} - {r.url}]\n{r.snippet}" for r in results)
                sources = _unique(
                    Source(kind="web", title=r.title, url=r.url, snippet=_snippet(r.snippet))
                    for r in results
                )
                try:
                    async for ev in self._compose(session, language, "web", context, sources):
                        yield ev
                    return
                except _NoAnswer:
                    logger.info("web results retrieved but declined by the model")

        # 3. Neither: say so. The model is not consulted.
        async for ev in self._fixed_turn(
            session, NO_ANSWER_TEXTS[language], language, kind="no_answer", source="none"
        ):
            yield ev

    # ------------------------------------------------------------------ helpers
    async def _fixed_turn(
        self, session: Session, text: str, language: str, *, kind: TurnKind, source: TurnSource
    ) -> AsyncIterator[Event]:
        yield TokenEvent(text)
        yield SentenceEvent(
            index=0, text=text, language=language, voice_locale=voice_locale(language)
        )
        yield SourcesEvent([])
        session.turns.append(
            Turn(role="agent", text=text, language=language, kind=kind, source=source)
        )
        yield TurnEvent(kind=kind, source=source, language=language, text=text)

    def _messages(self, session: Session, system: str) -> list[dict[str, str]]:
        history = session.turns[-HISTORY_TURNS:]
        messages = [{"role": "system", "content": system}]
        for t in history:
            messages.append(
                {"role": "user" if t.role == "client" else "assistant", "content": t.text}
            )
        return messages

    async def _compose(
        self,
        session: Session,
        language: str,
        context_kind: str,
        context: str,
        sources: list[Source],
    ) -> AsyncIterator[Event]:
        """Stream the model's reply as tokens and sentences; raise _NoAnswer if it declined.

        The first few characters are buffered so a protocol marker can be recognised before
        anything is spoken. The generator is a two-phase thing on purpose: nothing is
        yielded until the marker question is settled, so a decline never reaches the client.
        """
        messages = self._messages(session, system_prompt(language, context_kind, context))
        stream = self.llm.stream(messages)

        head = ""
        pending: list[str] = []
        kind: TurnKind = "answer"
        async for delta in stream:
            head += delta
            if len(head) >= _MARKER_PROBE or head.startswith((NO_ANSWER_MARKER, QUESTION_MARKER)):
                break
        if head.lstrip().startswith(NO_ANSWER_MARKER):
            raise _NoAnswer()
        if head.lstrip().startswith(QUESTION_MARKER):
            kind = "question"
            head = head.lstrip()[len(QUESTION_MARKER) :].lstrip()
        if head:
            pending.append(head)

        splitter = SentenceSplitter()
        full: list[str] = []
        index = 0
        locale = voice_locale(language)

        async def emit(piece: str) -> AsyncIterator[Event]:
            nonlocal index
            full.append(piece)
            yield TokenEvent(piece)
            for sentence in splitter.feed(piece):
                yield SentenceEvent(
                    index=index, text=sentence, language=language, voice_locale=locale
                )
                index += 1

        for piece in pending:
            async for ev in emit(piece):
                yield ev
        async for delta in stream:
            async for ev in emit(delta):
                yield ev
        for sentence in splitter.flush():
            yield SentenceEvent(index=index, text=sentence, language=language, voice_locale=locale)
            index += 1

        text = "".join(full).strip()
        source: TurnSource = "wiki" if context_kind == "wiki" else "web"
        yield SourcesEvent(sources)
        session.turns.append(
            Turn(role="agent", text=text, language=language, kind=kind, source=source)
        )
        yield TurnEvent(kind=kind, source=source, language=language, text=text)


def _unique(sources: Iterable[Source]) -> list[Source]:
    """One entry per document or page, in rank order, with the best-ranked snippet. The
    model sees every excerpt; the client hears each source named once."""
    seen: set[str] = set()
    out: list[Source] = []
    for s in sources:
        key = s.location or s.url or s.title
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _snippet(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
