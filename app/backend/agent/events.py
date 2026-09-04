"""The events one agent turn is made of, in the order the stream emits them.

    LanguageEvent          once, first
    TokenEvent             zero or more, as the model produces text
    SentenceEvent          zero or more, each time a sentence completes (speak it now)
    SourcesEvent           once
    TurnEvent              once, last

`backend.routes.sessions` encodes these as Server-Sent Events exactly as `docs/API.md`
describes; nothing else knows the wire format.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

TurnKind = Literal["answer", "question", "no_answer"]
TurnSource = Literal["wiki", "web", "none"]


@dataclass(frozen=True)
class Source:
    kind: Literal["wiki", "web"]
    title: str
    snippet: str
    location: str | None = None  # wiki: path under virtualagent/resources
    url: str | None = None  # web

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"kind": self.kind, "title": self.title, "snippet": self.snippet}
        if self.kind == "wiki":
            d["location"] = self.location
        else:
            d["url"] = self.url
        return d


@dataclass(frozen=True)
class LanguageEvent:
    language: str | None
    voice_locale: str | None
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class SentenceEvent:
    index: int
    text: str
    language: str
    voice_locale: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SourcesEvent:
    sources: list[Source] = field(default_factory=list)

    def to_list(self) -> list[dict[str, object]]:
        return [s.to_dict() for s in self.sources]


@dataclass(frozen=True)
class TurnEvent:
    kind: TurnKind
    source: TurnSource
    language: str
    text: str

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "source": self.source, "language": self.language}


Event = LanguageEvent | TokenEvent | SentenceEvent | SourcesEvent | TurnEvent
