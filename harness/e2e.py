#!/usr/bin/env python3
"""The E2E rung: FACTORY_RULES.md section 4, the whole journey, against a live process.

Returns the number of steps asserted, or None if the journey broke.

This IS the journey, not a floor under it. The Virtual Agent's only client is an iOS
app that cannot run here, so the journey is the API contract the app is written against
(`docs/API.md`), driven exactly as the app drives it: open a session, send what the
client said, read the stream. The providers are the stubs `serve.py` started, which is
why the gate can prove that the wiki was consulted first and the web was NOT touched
while it had an answer - the stub counts its calls.

What this does NOT prove, stated rather than hidden: that the real providers behave, and
that the app speaks. The first is the mocked-boundary policy in CLAUDE.md; the second is
the gap FACTORY.md names.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUB_PORT_FILE = HERE / ".run" / "stub-port"


def _stub_calls() -> dict[str, int]:
    port = STUB_PORT_FILE.read_text(encoding="utf-8").strip()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/_calls", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _frames(body: str) -> list[tuple[str | None, str]]:
    out: list[tuple[str | None, str]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event, data = None, []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        out.append((event, "\n".join(data)))
    return out


def _named(frames: list[tuple[str | None, str]], name: str) -> list[dict]:
    return [json.loads(d) for n, d in frames if n == name]


def run_e2e(app) -> int | None:
    steps = 0
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal steps
        steps += 1
        if not ok:
            failures.append(f"{name}: {detail}")

    def turn(session: dict, text: str) -> tuple[int, list[tuple[str | None, str]]]:
        status, body, _ = app.post(f"/api/sessions/{session['session_id']}/turns",
                                   json.dumps({"text": text}),
                                   headers={"Authorization": f"Bearer {session['session_token']}"})
        return status, _frames(body)

    # 1. It is up, the wiki loaded, and the language set is the mission's.
    status, body, _ = app.get("/api/health")
    health = json.loads(body) if status == 200 else {}
    check("health is 200 and reports the wiki loaded",
          status == 200 and health.get("wiki_documents", 0) >= 1, f"status={status} body={body[:200]}")
    check("health lists exactly the four supported languages",
          health.get("languages") == ["ar", "de", "en", "fr"], f"languages={health.get('languages')}")

    # 2. It can say what it is.
    status, _, _ = app.get("/api/version")
    check("version endpoint answers", status == 200, f"got {status}")

    # 3. A session opens with a spoken greeting.
    status, body, _ = app.post("/api/sessions", json.dumps({"client_id": "harness", "language_hint": "fr"}))
    session = json.loads(body) if status == 201 else {}
    check("a session opens with a French greeting and a voice locale",
          status == 201 and session.get("greeting", {}).get("voice_locale") == "fr-FR"
          and bool(session.get("greeting", {}).get("text")), f"status={status} body={body[:200]}")
    if not session:
        for f in failures:
            print(f"  E2E_FAIL  {f}", flush=True)
        return None

    # 4. Nobody without the token can speak on it (MISSION invariant 4).
    status, _, _ = app.post(f"/api/sessions/{session['session_id']}/turns", json.dumps({"text": "hi"}))
    check("an anonymous turn is refused", status == 401, f"got {status}")

    # 5-7. A wiki-covered French question: French, spoken sentence by sentence, from the
    #      wiki, and the web NEVER touched (MISSION invariant 2).
    before = _stub_calls()["web_search"]
    status, frames = turn(session, "Quels sont vos horaires d'ouverture ?")
    langs = _named(frames, "language")
    check("the French question is detected as French with a French voice",
          status == 200 and langs and langs[0].get("language") == "fr"
          and langs[0].get("voice_locale") == "fr-FR", f"status={status} language={langs[:1]}")
    names = [n for n, _ in frames]
    sentences = _named(frames, "sentence")
    tokens = "".join(json.loads(d) for n, d in frames if n is None and d != "[DONE]")
    check("at least one sentence is ready to speak before the turn closes, and the tokens add up",
          bool(sentences) and "turn" in names and names.index("sentence") < names.index("turn")
          and " ".join(s["text"] for s in sentences) == " ".join(tokens.split()),
          f"names={names} tokens={tokens!r}")
    turns = _named(frames, "turn")
    sources = _named(frames, "sources")
    after = _stub_calls()["web_search"]
    check("the answer comes from the wiki, names a document, and the web was not searched",
          turns and turns[-1].get("source") == "wiki" and sources and sources[0]
          and all(s.get("kind") == "wiki" and s.get("location") for s in sources[0])
          and after == before, f"turn={turns[-1:]} sources={sources[:1]} web_calls={before}->{after}")

    # 8. An uncovered German question falls back to the web, in German, naming a page.
    status, frames = turn(session, "Wer hat die Mona Lisa gemalt?")
    turns = _named(frames, "turn")
    sources = _named(frames, "sources")
    langs = _named(frames, "language")
    web_after = _stub_calls()["web_search"]
    check("an uncovered German question is answered from the web, in German, with a URL",
          status == 200 and langs and langs[0].get("language") == "de"
          and turns and turns[-1].get("source") == "web"
          and sources and sources[0] and all(s.get("kind") == "web" and s.get("url") for s in sources[0])
          and web_after == after + 1,
          f"status={status} language={langs[:1]} turn={turns[-1:]} sources={sources[:1]} web_calls={after}->{web_after}")

    # 9. Arabic is Arabic.
    status, frames = turn(session, "ما هي ساعات العمل لديكم؟")
    langs = _named(frames, "language")
    check("an Arabic question is detected as Arabic with an Arabic voice",
          status == 200 and langs and langs[0].get("language") == "ar"
          and langs[0].get("voice_locale") == "ar-SA", f"status={status} language={langs[:1]}")

    # 10. A language outside the set, on a fresh session: the agent ASKS, out loud.
    status, body, _ = app.post("/api/sessions", json.dumps({"client_id": "harness-2"}))
    fresh = json.loads(body) if status == 201 else {}
    status, frames = turn(fresh, "¿Dónde está el baño, por favor?")
    turns = _named(frames, "turn")
    langs = _named(frames, "language")
    check("an unsupported language yields a spoken question to choose a supported one",
          status == 200 and langs and langs[0].get("language") is None
          and turns and turns[-1].get("kind") == "question" and turns[-1].get("source") == "none"
          and bool(_named(frames, "sentence")),
          f"status={status} language={langs[:1]} turn={turns[-1:]}")

    # 11. The transcript is the owner's alone (MISSION invariant 4, composed).
    status_other, _, _ = app.get(f"/api/sessions/{session['session_id']}",
                                 headers={"Authorization": f"Bearer {fresh.get('session_token', '')}"})
    status_own, body, _ = app.get(f"/api/sessions/{session['session_id']}",
                                  headers={"Authorization": f"Bearer {session['session_token']}"})
    own = json.loads(body) if status_own == 200 else {}
    check("another session's token cannot read the transcript, the owner's can",
          status_other == 403 and status_own == 200 and len(own.get("turns", [])) >= 7,
          f"other={status_other} own={status_own} turns={len(own.get('turns', []))}")

    if failures:
        for f in failures:
            print(f"  E2E_FAIL  {f}", flush=True)
        return None
    return steps
