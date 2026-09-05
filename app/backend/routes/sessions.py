"""Sessions and turns. The only place that knows the SSE wire format in `docs/API.md`."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend import rate_limit
from backend.agent.events import (
    Event,
    LanguageEvent,
    SentenceEvent,
    SourcesEvent,
    TokenEvent,
    TurnEvent,
)
from backend.agent.pipeline import Agent
from backend.auth import get_current_session
from backend.languages import GREETINGS, SUPPORTED_LANGUAGES, voice_locale
from backend.sessions.store import Session, Turn, store

router = APIRouter()


class CreateSessionRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=200)
    language_hint: str | None = None


class TurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def get_agent(request: Request) -> Agent:
    agent = getattr(request.app.state, "agent", None)
    if not isinstance(agent, Agent):
        raise HTTPException(status_code=503, detail="Agent not initialised")
    return agent


@router.post("/sessions", status_code=201)
async def create_session(body: CreateSessionRequest) -> dict[str, object]:
    hint = body.language_hint
    if hint is not None and hint not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="language_hint must be one of ar, de, en, fr")
    session = store.create(client_id=body.client_id, language=hint)
    greeting_language = hint or "en"
    greeting = GREETINGS[greeting_language]
    session.turns.append(
        Turn(
            role="agent", text=greeting, language=greeting_language, kind="question", source="none"
        )
    )
    return {
        "session_id": session.id,
        "session_token": session.token,
        "language": session.language,
        "greeting": {
            "text": greeting,
            "language": greeting_language,
            "voice_locale": voice_locale(greeting_language),
        },
    }


@router.get("/sessions/{session_id}")
async def read_session(session: Session = Depends(get_current_session)) -> dict[str, object]:
    return session.to_dict()


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session: Session = Depends(get_current_session)) -> Response:
    store.delete(session.id)
    return Response(status_code=204)


def _sse(event: str | None, data: object) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n" if event else f"data: {payload}\n\n"


def encode(event: Event) -> str:
    if isinstance(event, LanguageEvent):
        return _sse("language", event.to_dict())
    if isinstance(event, TokenEvent):
        return _sse(None, event.text)
    if isinstance(event, SentenceEvent):
        return _sse("sentence", event.to_dict())
    if isinstance(event, SourcesEvent):
        return _sse("sources", event.to_list())
    if isinstance(event, TurnEvent):
        return _sse("turn", event.to_dict())
    raise TypeError(f"unknown event {event!r}")


@router.post("/sessions/{session_id}/turns")
async def post_turn(
    body: TurnRequest,
    session: Session = Depends(get_current_session),
    agent: Agent = Depends(get_agent),
) -> Response:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    try:
        rate_limit.check_and_record(session.client_id)
    except rate_limit.RateLimitExceeded as e:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Daily turn cap reached for this client",
                "resets_at": e.reset_at.isoformat().replace("+00:00", "Z"),
            },
        )

    async def body_stream() -> AsyncIterator[str]:
        async for event in agent.respond(session, text):
            yield encode(event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        body_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
