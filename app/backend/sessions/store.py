"""Sessions and their transcripts, in process.

A session is private to the client that opened it (MISSION hard invariant 4): the token
issued at creation is the only credential, and `backend.auth` checks it on every route.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from backend.config import SESSION_TTL_HOURS


@dataclass
class Turn:
    role: str  # "client" | "agent"
    text: str
    language: str | None
    kind: str | None = None  # agent turns: answer | question | no_answer
    source: str | None = None  # agent turns: wiki | web | none

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"role": self.role, "text": self.text, "language": self.language}
        if self.role == "agent":
            out["kind"] = self.kind
            out["source"] = self.source
        return out


@dataclass
class Session:
    id: str
    token: str
    client_id: str
    language: str | None
    created_at: datetime
    turns: list[Turn] = field(default_factory=list)

    @classmethod
    def new(cls, client_id: str, language: str | None = None) -> Session:
        return cls(
            id="s_" + secrets.token_hex(6),
            token="st_" + secrets.token_urlsafe(32),
            client_id=client_id,
            language=language,
            created_at=datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.id,
            "language": self.language,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "turns": [t.to_dict() for t in self.turns],
        }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, client_id: str, language: str | None = None) -> Session:
        self.prune()
        session = Session.new(client_id=client_id, language=language)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def prune(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(hours=SESSION_TTL_HOURS)
        stale = [sid for sid, s in self._sessions.items() if s.created_at <= cutoff]
        for sid in stale:
            del self._sessions[sid]
        return len(stale)

    def clear(self) -> None:
        """Test hook."""
        self._sessions.clear()

    def __len__(self) -> int:
        return len(self._sessions)


store = SessionStore()
