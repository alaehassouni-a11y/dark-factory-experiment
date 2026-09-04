"""The session token check. MISSION hard invariant 4: a session is private to its client.

Every `/api/sessions/{session_id}/...` route depends on `get_current_session`. A request
with no bearer token is 401, an unknown session is 404, and a token that belongs to a
different session is 403. The order matters: the 401 comes first so an anonymous probe
learns nothing about which ids exist.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from backend.sessions.store import Session, store


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def get_current_session(
    session_id: str, authorization: str | None = Header(default=None)
) -> Session:
    token = _bearer(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Session token required")
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    if not secrets.compare_digest(session.token, token):
        raise HTTPException(status_code=403, detail="Token does not belong to this session")
    return session
