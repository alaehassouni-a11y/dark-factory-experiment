from __future__ import annotations

import json

import httpx

from backend import rate_limit
from conftest import parse_sse


async def open_session(
    client: httpx.AsyncClient, client_id: str = "device-1", hint: str | None = None
):
    body: dict[str, object] = {"client_id": client_id}
    if hint:
        body["language_hint"] = hint
    r = await client.post("/api/sessions", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    return data, {"Authorization": f"Bearer {data['session_token']}"}


async def test_health_version_and_languages_are_public(client: httpx.AsyncClient) -> None:
    health = (await client.get("/api/health")).json()
    assert health["status"] == "ok"
    assert health["wiki_documents"] == 3 and health["wiki_chunks"] >= 3
    assert health["languages"] == ["ar", "de", "en", "fr"]
    assert health["web_search"] == "configured"
    assert (await client.get("/api/version")).status_code == 200
    codes = [entry["code"] for entry in (await client.get("/api/languages")).json()]
    assert codes == ["ar", "de", "en", "fr"]


async def test_create_session_greets_in_the_hint_language(client: httpx.AsyncClient) -> None:
    data, _ = await open_session(client, hint="fr")
    assert data["language"] == "fr"
    assert data["greeting"]["voice_locale"] == "fr-FR"
    assert data["greeting"]["text"].startswith("Bonjour")
    assert data["session_token"].startswith("st_")


async def test_create_session_without_hint_greets_in_english(client: httpx.AsyncClient) -> None:
    data, headers = await open_session(client)
    assert data["language"] is None
    assert data["greeting"]["language"] == "en"
    transcript = (await client.get(f"/api/sessions/{data['session_id']}", headers=headers)).json()
    assert transcript["turns"][0] == {
        "role": "agent",
        "text": data["greeting"]["text"],
        "language": "en",
        "kind": "question",
        "source": "none",
    }


async def test_create_session_rejects_unsupported_hint_and_missing_client(
    client: httpx.AsyncClient,
) -> None:
    assert (
        await client.post("/api/sessions", json={"client_id": "x", "language_hint": "es"})
    ).status_code == 422
    assert (await client.post("/api/sessions", json={})).status_code == 422


async def test_session_is_private_to_its_token(client: httpx.AsyncClient) -> None:
    a, a_headers = await open_session(client, "A")
    _, b_headers = await open_session(client, "B")
    sid = a["session_id"]
    assert (await client.get(f"/api/sessions/{sid}", headers=a_headers)).status_code == 200
    assert (await client.get(f"/api/sessions/{sid}", headers=b_headers)).status_code == 403
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 401
    assert (
        await client.get(f"/api/sessions/{sid}", headers={"Authorization": "Basic abc"})
    ).status_code == 401
    assert (await client.get("/api/sessions/s_nope", headers=a_headers)).status_code == 404
    assert (await client.post(f"/api/sessions/{sid}/turns", json={"text": "hi"})).status_code == 401


async def test_delete_ends_the_session(client: httpx.AsyncClient) -> None:
    data, headers = await open_session(client)
    sid = data["session_id"]
    assert (await client.delete(f"/api/sessions/{sid}", headers=headers)).status_code == 204
    assert (await client.get(f"/api/sessions/{sid}", headers=headers)).status_code == 404


async def test_turn_streams_the_documented_event_sequence(client: httpx.AsyncClient) -> None:
    data, headers = await open_session(client)
    r = await client.post(
        f"/api/sessions/{data['session_id']}/turns",
        json={"text": "What are the shop opening hours?"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = parse_sse(r.text)
    names = [name for name, _ in frames]
    assert names[0] == "language"
    assert names[-1] is None and frames[-1][1] == "[DONE]"
    assert names.index("sentence") < names.index("sources") < names.index("turn")
    language = json.loads(frames[0][1])
    assert language == {
        "language": "en",
        "voice_locale": "en-US",
        "confidence": language["confidence"],
    }
    tokens = "".join(json.loads(d) for n, d in frames if n is None and d != "[DONE]")
    assert tokens == "We are open from nine to six, Monday to Saturday."
    sentence = json.loads(next(d for n, d in frames if n == "sentence"))
    assert sentence == {"index": 0, "text": tokens, "language": "en", "voice_locale": "en-US"}
    sources = json.loads(next(d for n, d in frames if n == "sources"))
    assert sources[0]["kind"] == "wiki" and sources[0]["location"] == "opening-hours.md"
    turn = json.loads(next(d for n, d in frames if n == "turn"))
    assert turn == {"kind": "answer", "source": "wiki", "language": "en"}

    transcript = (await client.get(f"/api/sessions/{data['session_id']}", headers=headers)).json()
    assert transcript["language"] == "en"
    assert [t["role"] for t in transcript["turns"]] == ["agent", "client", "agent"]


async def test_turn_rejects_empty_text(client: httpx.AsyncClient) -> None:
    data, headers = await open_session(client)
    r = await client.post(
        f"/api/sessions/{data['session_id']}/turns", json={"text": "   "}, headers=headers
    )
    assert r.status_code == 422


async def test_turn_cap_returns_429_with_reset_time(client: httpx.AsyncClient) -> None:
    data, headers = await open_session(client, "heavy")
    for _ in range(rate_limit.DAILY_TURN_CAP):
        rate_limit.check_and_record("heavy")
    r = await client.post(
        f"/api/sessions/{data['session_id']}/turns", json={"text": "hello"}, headers=headers
    )
    assert r.status_code == 429
    body = r.json()
    assert "resets_at" in body and body["resets_at"].endswith("Z")
    assert "detail" in body


async def test_turns_from_two_sessions_of_one_client_share_the_cap(
    client: httpx.AsyncClient,
) -> None:
    a, a_headers = await open_session(client, "same-device")
    b, b_headers = await open_session(client, "same-device")
    for _ in range(rate_limit.DAILY_TURN_CAP - 1):
        rate_limit.check_and_record("same-device")
    ok = await client.post(
        f"/api/sessions/{a['session_id']}/turns", json={"text": "hello there"}, headers=a_headers
    )
    assert ok.status_code == 200
    capped = await client.post(
        f"/api/sessions/{b['session_id']}/turns", json={"text": "hello again"}, headers=b_headers
    )
    assert capped.status_code == 429
