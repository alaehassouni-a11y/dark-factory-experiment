#!/usr/bin/env python3
"""Stand-ins for the two providers, so the gate runs with no secrets and no network.

    python harness/stubs.py --port 8765

Two shapes, both minimal and both deterministic:

  * OpenAI-compatible `POST /v1/chat/completions` (streaming) and `POST /v1/embeddings`,
    which is what the service speaks to OpenRouter. The reply depends only on the system
    prompt: which language it demands and whether the excerpts are wiki or web. That is
    enough for the journey to assert that the LANGUAGE the pipeline chose reached the
    model, and that the SOURCE the pipeline chose is the one it declares.
  * Brave-shaped `GET /web/search`, returning one result and counting calls.

`GET /_calls` reports how many times each endpoint was hit, which is how `e2e.py` proves
the web was NOT searched while the wiki had a confident answer (MISSION invariant 2).

Stdlib only, on purpose: this runs under whatever `python` the harness has, before the
service's own environment is guaranteed to exist.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CALLS = {"chat": 0, "embeddings": 0, "web_search": 0}
_LOCK = threading.Lock()

# Two sentences each, so the journey sees a sentence event before the turn closes.
REPLIES: dict[str, dict[str, str]] = {
    "French": {
        "wiki": "Nous sommes ouverts de neuf heures à dix-huit heures. Nous sommes fermés le dimanche.",
        "web": "D'après le web, la réponse est celle-ci. Voici ce que j'ai trouvé.",
    },
    "English": {
        "wiki": "We are open from nine to six. We are closed on Sunday.",
        "web": "According to the web, here is the answer. This is what I found.",
    },
    "German": {
        "wiki": "Wir haben von neun bis achtzehn Uhr geöffnet. Sonntags ist geschlossen.",
        "web": "Laut dem Web lautet die Antwort so. Das habe ich gefunden.",
    },
    "Arabic": {
        "wiki": "نحن نفتح من التاسعة صباحا حتى السادسة مساء. نحن مغلقون يوم الأحد.",
        "web": "وفقا للويب، هذه هي الإجابة. هذا ما وجدته.",
    },
}
_LANGUAGE = re.compile(r"Reply ONLY in (French|English|German|Arabic)")


def bag(text: str, dims: int = 256) -> list[float]:
    vec = [0.0] * dims
    for word in re.findall(r"\w+", text.lower()):
        vec[zlib.crc32(word.encode("utf-8")) % dims] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet
        return

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/_calls":
            with _LOCK:
                self._json(200, dict(CALLS))
            return
        if url.path == "/web/search":
            if not self.headers.get("X-Subscription-Token"):
                self._json(401, {"error": "missing token"})
                return
            with _LOCK:
                CALLS["web_search"] += 1
            q = parse_qs(url.query).get("q", [""])[0]
            self._json(200, {"web": {"results": [{
                "title": f"Stub result for: {q[:40]}",
                "url": "https://stub.example.org/result",
                "description": "A stub page that the web fallback can compose from.",
            }]}})
            return
        self._json(404, {"error": "unknown path"})

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/v1/embeddings":
            body = self._body()
            inputs = body.get("input", [])
            if isinstance(inputs, str):
                inputs = [inputs]
            with _LOCK:
                CALLS["embeddings"] += 1
            self._json(200, {"object": "list", "model": body.get("model", "stub"),
                             "data": [{"object": "embedding", "index": i, "embedding": bag(t)}
                                      for i, t in enumerate(inputs)],
                             "usage": {"prompt_tokens": 0, "total_tokens": 0}})
            return
        if url.path == "/v1/chat/completions":
            body = self._body()
            with _LOCK:
                CALLS["chat"] += 1
            system = next((m.get("content", "") for m in body.get("messages", [])
                           if m.get("role") == "system"), "")
            m = _LANGUAGE.search(system)
            language = m.group(1) if m else "English"
            kind = "wiki" if "Wiki excerpts" in system else "web"
            reply = REPLIES[language][kind]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for i in range(0, len(reply), 5):
                chunk = {"id": "stub", "object": "chat.completion.chunk", "model": "stub",
                         "choices": [{"index": 0, "delta": {"content": reply[i:i + 5]},
                                      "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            done = {"id": "stub", "object": "chat.completion.chunk", "model": "stub",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
            return
        self._json(404, {"error": "unknown path"})


def serve(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()
    s = serve(args.port)
    print(f"STUBS_STARTED port={args.port}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        s.shutdown()
