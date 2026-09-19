#!/usr/bin/env python3
"""The E2E rung: FACTORY_RULES.md section 4, the whole journey, against a live process.

Returns the number of steps asserted, or None if the journey broke.

This IS the journey, not a floor under it. The Virtual Agent's only client is an iOS
app that cannot run here, so the journey is the API contract the app is written against
(`docs/API.md`), driven exactly as the app drives it: open a session, send what the
client said, read the stream. The providers are the stubs `serve.py` started, which is
why the gate can prove that the wiki was consulted first and the web was NOT touched
while it had an answer - the stub counts its calls.

What it asserts, beyond the happy turn: the SSE framing the iOS parser depends on
(`language` first, `sources` before `turn`, `[DONE]` last, sentence indexes from zero),
that the agent is LIVE (a sentence is ready to speak before the last token frame, which
is the product's one adjective and the one property a batch-then-emit agent fails), the
authentication ORDER (401 before 404 before 403), the daily cap and its `resets_at`, the
wiki-declined-then-web path and a genuine no-answer, and the watched wiki: a document
written into the folder is answering questions seconds later, with no restart.

Run it against a service `serve.py` already started:

    python harness/e2e.py --port 9411

What this does NOT prove, stated rather than hidden: that the real providers behave, and
that the app speaks. The first is the mocked-boundary policy in CLAUDE.md; the second is
the gap FACTORY.md names.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN_DIR = HERE / ".run"

# Which stub counter the web fallback under test increments. The default provider
# (Perplexity Sonar through OpenRouter) is a chat completion, not a Brave query.
WEB_COUNTER = {"perplexity": "research", "brave": "web_search"}

# The document the journey teaches the running agent, and the question only it answers.
LIVRAISON_DOC = """\
# Livraison à domicile

Livrez-vous à domicile ? Oui, nous livrons à domicile dans toute la ville, du lundi au
vendredi. La livraison à domicile est offerte à partir de cinquante euros d'achat.
"""
LIVRAISON_QUESTION = "Livrez-vous à domicile ?"


def _run_info(app) -> dict:
    """What serve.py recorded for this service port: the stub port, the web provider it
    chose, the per-run wiki folder and the service log. Keyed by port because two runs
    happen at once in the validate-pr workflow."""
    path = RUN_DIR / f"run-{app.port}.json"
    if not path.is_file():
        raise RuntimeError(f"{path} is missing: the service was not started by harness/serve.py")
    return json.loads(path.read_text(encoding="utf-8"))


def _stub_calls(info: dict) -> dict[str, int]:
    url = f"http://127.0.0.1:{info['stub_port']}/_calls"
    with urllib.request.urlopen(url, timeout=10) as r:
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


def _token_positions(frames: list[tuple[str | None, str]]) -> list[int]:
    return [i for i, (n, d) in enumerate(frames) if n is None and d != "[DONE]"]


def _health(app) -> dict:
    status, body, _ = app.get("/api/health")
    return json.loads(body) if status == 200 else {}


def run_e2e(app) -> int | None:
    steps = 0
    failures: list[str] = []
    try:
        info = _run_info(app)
    except (OSError, ValueError, RuntimeError, KeyError) as e:
        # A missing or unreadable run file is a FAILURE of the rung, not an exception the
        # gate has to interpret: the journey cannot count stub calls without it.
        print(f"  E2E_FAIL  the run file for port {app.port} is unusable: {e}", flush=True)
        return None
    provider = info["web_search"]
    web_counter = WEB_COUNTER[provider]

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

    def web_calls() -> int:
        return _stub_calls(info)[web_counter]

    def unused_web_calls() -> int:
        other = "web_search" if web_counter == "research" else "research"
        return _stub_calls(info)[other]

    # 1-3. It is up, the wiki loaded, the language set is the mission's, and the web
    #      fallback in use is the one serve.py chose - not one app/.env leaked in.
    health = _health(app)
    check("health is 200 and reports the wiki loaded",
          health.get("status") == "ok" and health.get("wiki_documents", 0) >= 1,
          f"health={health}")
    check("health lists exactly the four supported languages",
          health.get("languages") == ["ar", "de", "en", "fr"], f"languages={health.get('languages')}")
    check("the web fallback under test is the one the harness chose",
          health.get("web_search") == provider,
          f"health={health.get('web_search')} chosen={provider} (a leaked WEB_SEARCH_PROVIDER "
          f"or BRAVE_SEARCH_API_KEY configures the service under test)")

    # 4-5. It can say what it is, and which voices the app should use.
    status, _, _ = app.get("/api/version")
    check("version endpoint answers", status == 200, f"got {status}")
    status, body, _ = app.get("/api/languages")
    languages = json.loads(body) if status == 200 else []
    check("the languages endpoint names the four languages with their voice locales",
          status == 200 and [x.get("code") for x in languages] == ["ar", "de", "en", "fr"]
          and all(x.get("name") and x.get("voice_locale") for x in languages),
          f"status={status} body={body[:200]}")

    # 6. A session opens with a spoken greeting.
    status, body, _ = app.post("/api/sessions", json.dumps({"client_id": "harness", "language_hint": "fr"}))
    session = json.loads(body) if status == 201 else {}
    check("a session opens with a French greeting and a voice locale",
          status == 201 and session.get("greeting", {}).get("voice_locale") == "fr-FR"
          and bool(session.get("greeting", {}).get("text")), f"status={status} body={body[:200]}")
    status, body, _ = app.post("/api/sessions", json.dumps({"client_id": "harness-2"}))
    other = json.loads(body) if status == 201 else {}
    if not session or not other:
        for f in failures:
            print(f"  E2E_FAIL  {f}", flush=True)
        return None

    # 7-9. The authentication order, as docs/API.md states it (MISSION invariant 4):
    #      401 with no token, 404 for an unknown session even with a good-looking token,
    #      403 for a token that belongs to somebody else. The 401 comes first so an
    #      anonymous probe cannot learn which session ids exist.
    status, _, _ = app.post(f"/api/sessions/{session['session_id']}/turns", json.dumps({"text": "hi"}))
    check("an anonymous turn is refused", status == 401, f"got {status}")
    status, _, _ = app.post("/api/sessions/s_does_not_exist/turns", json.dumps({"text": "hi"}),
                            headers={"Authorization": f"Bearer {session['session_token']}"})
    check("an unknown session is 404 even with a valid-looking token", status == 404, f"got {status}")
    status, _, _ = app.post(f"/api/sessions/{session['session_id']}/turns", json.dumps({"text": "hi"}),
                            headers={"Authorization": f"Bearer {other['session_token']}"})
    check("another session's token cannot speak on this session", status == 403, f"got {status}")

    # 10. An empty utterance is a malformed body, not a turn.
    status, _, _ = app.post(f"/api/sessions/{session['session_id']}/turns", json.dumps({"text": ""}),
                            headers={"Authorization": f"Bearer {session['session_token']}"})
    check("an empty text is refused as unprocessable", status == 422, f"got {status}")

    # 11-14. A wiki-covered French question: French, spoken sentence by sentence WHILE the
    #        answer is still being produced, framed as the app's parser expects, from the
    #        wiki, and the web NEVER touched (MISSION invariant 2).
    before = web_calls()
    status, frames = turn(session, "Quels sont vos horaires d'ouverture ?")
    langs = _named(frames, "language")
    check("the French question is detected as French with a French voice",
          status == 200 and langs and langs[0].get("language") == "fr"
          and langs[0].get("voice_locale") == "fr-FR", f"status={status} language={langs[:1]}")
    names = [n for n, _ in frames]
    sentences = _named(frames, "sentence")
    tokens = "".join(json.loads(d) for n, d in frames if n is None and d != "[DONE]")
    positions = _token_positions(frames)
    live = bool(sentences) and bool(positions) and names.index("sentence") < positions[-1]
    check("a sentence is ready to speak before the last token arrives, and the tokens add up",
          live and " ".join(s["text"] for s in sentences) == " ".join(tokens.split()),
          f"first_sentence={names.index('sentence') if 'sentence' in names else None} "
          f"last_token={positions[-1] if positions else None} names={names} tokens={tokens!r}")
    check("the stream is framed as docs/API.md says: language first, sources before turn, "
          "[DONE] last, sentences numbered from zero",
          names and names[0] == "language" and "sources" in names and "turn" in names
          and names.index("sources") < names.index("turn")
          and frames[-1] == (None, "[DONE]")
          and [s.get("index") for s in sentences] == list(range(len(sentences))),
          f"names={names} last={frames[-1] if frames else None} "
          f"indexes={[s.get('index') for s in sentences]}")
    turns = _named(frames, "turn")
    sources = _named(frames, "sources")
    after = web_calls()
    check("the answer comes from the wiki, names a document, and the web was not searched",
          turns and turns[-1].get("source") == "wiki" and sources and sources[0]
          and all(s.get("kind") == "wiki" and s.get("location") for s in sources[0])
          and after == before, f"turn={turns[-1:]} sources={sources[:1]} web_calls={before}->{after}")

    # 15. An uncovered German question falls back to the web, in German, naming a page -
    #     through the provider under test, and through that one only.
    idle_before = unused_web_calls()
    status, frames = turn(session, "Wer hat die Mona Lisa gemalt?")
    turns = _named(frames, "turn")
    sources = _named(frames, "sources")
    langs = _named(frames, "language")
    web_after = web_calls()
    check("an uncovered German question is answered from the web, in German, with a URL",
          status == 200 and langs and langs[0].get("language") == "de"
          and turns and turns[-1].get("source") == "web"
          and sources and sources[0] and all(s.get("kind") == "web" and s.get("url") for s in sources[0])
          and web_after == after + 1 and unused_web_calls() == idle_before,
          f"status={status} language={langs[:1]} turn={turns[-1:]} sources={sources[:1]} "
          f"{web_counter}={after}->{web_after}")

    # 16. Arabic is Arabic.
    status, frames = turn(session, "ما هي ساعات العمل لديكم؟")
    langs = _named(frames, "language")
    check("an Arabic question is detected as Arabic with an Arabic voice",
          status == 200 and langs and langs[0].get("language") == "ar"
          and langs[0].get("voice_locale") == "ar-SA", f"status={status} language={langs[:1]}")

    # 17. The wiki had excerpts and the model declined them: the turn falls through to the
    #     web rather than speaking the decline (pipeline.py's _NoAnswer).
    before = web_calls()
    status, frames = turn(session, "Quels sont vos horaires d'ouverture stubdecline ?")
    turns = _named(frames, "turn")
    sources = _named(frames, "sources")
    tokens = "".join(json.loads(d) for n, d in frames if n is None and d != "[DONE]")
    check("wiki excerpts the model declines fall through to the web, and the decline is never spoken",
          status == 200 and turns and turns[-1].get("source") == "web"
          and turns[-1].get("kind") == "answer"
          and sources and sources[0] and all(s.get("kind") == "web" for s in sources[0])
          and "NO_ANSWER" not in tokens and web_calls() == before + 1,
          f"status={status} turn={turns[-1:]} sources={sources[:1]} tokens={tokens[:120]!r} "
          f"{web_counter}={before}->{web_calls()}")

    # 18. Neither source answered: the agent says so, in the client's language, with no
    #     source at all (MISSION invariant 3) - and the model is not asked to invent one.
    status, frames = turn(session, "Wer hat die Mona Lisa gemalt stubdeclineall?")
    turns = _named(frames, "turn")
    sources = _named(frames, "sources")
    check("when nothing answers, the agent says it does not know, in German, with source none",
          status == 200 and turns and turns[-1].get("kind") == "no_answer"
          and turns[-1].get("source") == "none" and turns[-1].get("language") == "de"
          and sources and sources[-1] == [] and bool(_named(frames, "sentence")),
          f"status={status} turn={turns[-1:]} sources={sources[-1:]}")

    # 19. A language outside the set, on a fresh session: the agent ASKS, out loud.
    status, frames = turn(other, "¿Dónde está el baño, por favor?")
    turns = _named(frames, "turn")
    langs = _named(frames, "language")
    check("an unsupported language yields a spoken question to choose a supported one",
          status == 200 and langs and langs[0].get("language") is None
          and turns and turns[-1].get("kind") == "question" and turns[-1].get("source") == "none"
          and bool(_named(frames, "sentence")),
          f"status={status} language={langs[:1]} turn={turns[-1:]}")

    # 20. The transcript is the owner's alone (MISSION invariant 4, composed).
    status_other, _, _ = app.get(f"/api/sessions/{session['session_id']}",
                                 headers={"Authorization": f"Bearer {other.get('session_token', '')}"})
    status_own, body, _ = app.get(f"/api/sessions/{session['session_id']}",
                                  headers={"Authorization": f"Bearer {session['session_token']}"})
    own = json.loads(body) if status_own == 200 else {}
    check("another session's token cannot read the transcript, the owner's can",
          status_other == 403 and status_own == 200 and len(own.get("turns", [])) >= 7,
          f"other={status_other} own={status_own} turns={len(own.get('turns', []))}")

    # 21-23. The wiki is watched, not deployed: a document written into the folder is
    #        knowledge within seconds, answers a question nothing else answers, and is
    #        gone again when it is removed. No restart, no re-deploy, no web call.
    wiki_dir = Path(info["wiki_dir"])
    baseline = _health(app)
    documents = baseline.get("wiki_documents", 0)
    indexed_at = baseline.get("wiki_indexed_at")
    document = wiki_dir / "livraison.md"
    document.write_text(LIVRAISON_DOC, encoding="utf-8")
    grown = _await_health(app, documents + 1, indexed_at)
    check("a document written into the wiki folder is indexed within seconds, with no restart",
          grown.get("wiki_documents") == documents + 1
          and grown.get("wiki_indexed_at") != indexed_at,
          f"before={documents}@{indexed_at} after={grown.get('wiki_documents')}@"
          f"{grown.get('wiki_indexed_at')}")
    before = web_calls()
    status, frames = turn(session, LIVRAISON_QUESTION)
    turns = _named(frames, "turn")
    sources = _named(frames, "sources")
    check("the new document answers the question it alone covers, from the wiki",
          status == 200 and turns and turns[-1].get("source") == "wiki"
          and sources and any(s.get("location") == "livraison.md" for s in sources[0])
          and web_calls() == before,
          f"status={status} turn={turns[-1:]} sources={sources[:1]} "
          f"{web_counter}={before}->{web_calls()}")
    document.unlink()
    shrunk = _await_health(app, documents, grown.get("wiki_indexed_at"))
    check("removing the document removes its knowledge again",
          shrunk.get("wiki_documents") == documents
          and shrunk.get("wiki_indexed_at") != grown.get("wiki_indexed_at"),
          f"after removal={shrunk.get('wiki_documents')}@{shrunk.get('wiki_indexed_at')}")

    # 24. The daily cap, on a client id nothing else uses so the sessions above keep their
    #     budget (MISSION invariant 5: 100 turns per client per 24 hours).
    capped_id = f"harness-cap-{uuid.uuid4().hex[:8]}"
    status, body, _ = app.post("/api/sessions", json.dumps({"client_id": capped_id}))
    capped = json.loads(body) if status == 201 else {}
    allowed = 0
    refused: tuple[int, dict] = (0, {})
    if capped:
        # "zzz" is in no language the detector knows, so a counted turn costs the stubs
        # nothing: the agent asks for a language without retrieving or composing.
        for _ in range(100):
            code, _ = turn(capped, "zzz")
            if code != 200:
                break
            allowed += 1
        code, body, _ = app.post(f"/api/sessions/{capped['session_id']}/turns",
                                 json.dumps({"text": "zzz"}),
                                 headers={"Authorization": f"Bearer {capped['session_token']}"})
        refused = (code, json.loads(body) if body.strip().startswith("{") else {})
    resets_in = _hours_until(refused[1].get("resets_at"))
    check("the hundred-and-first turn of a day is 429 with a reset about 24 hours away",
          allowed == 100 and refused[0] == 429 and resets_in is not None and 23.0 <= resets_in <= 24.1,
          f"allowed={allowed} status={refused[0]} body={refused[1]} resets_in_hours={resets_in}")

    # 25. A session can be ended, and is then gone.
    deleted, _, _ = app.delete(f"/api/sessions/{other['session_id']}",
                               headers={"Authorization": f"Bearer {other['session_token']}"})
    gone, _, _ = app.get(f"/api/sessions/{other['session_id']}",
                         headers={"Authorization": f"Bearer {other['session_token']}"})
    check("a deleted session is 204 and then unknown",
          deleted == 204 and gone == 404, f"delete={deleted} then={gone}")

    if failures:
        for f in failures:
            print(f"  E2E_FAIL  {f}", flush=True)
        print(f"  E2E_LOG   {info.get('log')}", flush=True)
        return None
    return steps


def _await_health(app, documents: int, since: str | None, timeout: float = 20.0) -> dict:
    """Poll /api/health until the watcher has re-indexed, or give up and let the caller
    assert on what it last saw. A sleep would be a race chosen to be lost."""
    deadline = time.time() + timeout
    health = _health(app)
    while time.time() < deadline:
        health = _health(app)
        if health.get("wiki_documents") == documents and health.get("wiki_indexed_at") != since:
            return health
        time.sleep(0.25)
    return health


def _hours_until(when: str | None) -> float | None:
    if not when:
        return None
    try:
        moment = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment - datetime.now(UTC)).total_seconds() / 3600.0


class _LiveApp:
    """`run_e2e` against a service somebody else started, for driving the journey by hand.

    The gate composes the real `appproc.HttpApp`; this is the same three methods over a
    port that is already serving, so `python harness/e2e.py --port 9411` needs no config.
    """

    def __init__(self, port: int) -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"

    def _send(self, req: urllib.request.Request) -> tuple[int, str, dict]:
        import urllib.error

        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

    def get(self, path: str, follow: bool = False, headers: dict | None = None):
        return self._send(urllib.request.Request(self.base + path, headers=headers or {}))

    def post(self, path: str, body: str, headers: dict | None = None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        return self._send(urllib.request.Request(self.base + path, data=body.encode("utf-8"),
                                                 headers=h, method="POST"))

    def delete(self, path: str, headers: dict | None = None):
        return self._send(urllib.request.Request(self.base + path, headers=headers or {},
                                                 method="DELETE"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True,
                    help="a service already started by harness/serve.py --port <the same>")
    args = ap.parse_args()
    steps = run_e2e(_LiveApp(args.port))
    if steps is None:
        print("E2E_FAILED", flush=True)
        return 1
    print(f"E2E_PASSED steps={steps}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
