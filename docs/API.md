# Virtual Agent API

The service behind the iOS app. It detects the client's language, answers from the
wiki or the web, and streams every agent turn as text plus ready-to-speak sentences so
the app can speak while the answer is still being produced.

**Base URL:** `http://localhost:8000` (development)

## Authentication

There are no accounts. A session is created anonymously and returns a **session
token**; every later call on that session carries it as a bearer token. A request with
no token gets `401`; a request with a token that belongs to a different session gets
`403`. This is MISSION hard invariant 4.

| Endpoint | Token required |
|---|---|
| `GET /api/health`, `GET /api/version`, `GET /api/languages` | No |
| `POST /api/sessions` | No (this call issues the token) |
| Every other `/api/sessions/...` route | Yes (`Authorization: Bearer <session_token>`) |

---

## System

### `GET /api/health`

Reports that the service is up and that the wiki loaded. `wiki_indexed_at` moves whenever
the service re-indexes the folder after a file was added, changed or removed; the wiki is
watched, not deployed.

**Response `200`:**
```json
{
  "status": "ok",
  "wiki_documents": 3,
  "wiki_chunks": 27,
  "wiki_indexed_at": "2026-09-06T09:12:03Z",
  "languages": ["ar", "de", "en", "fr"],
  "web_search": "configured"
}
```

`web_search` is `"configured"` or `"unconfigured"`. When unconfigured, the fallback path
produces `source: "none"` turns rather than failing.

### `GET /api/version`

```json
{ "version": "0.1.0" }
```

### `GET /api/languages`

The supported set, with the voice locale the app should use for speech recognition and
synthesis in each.

```json
[
  { "code": "ar", "name": "Arabic",  "voice_locale": "ar-SA" },
  { "code": "de", "name": "German",  "voice_locale": "de-DE" },
  { "code": "en", "name": "English", "voice_locale": "en-US" },
  { "code": "fr", "name": "French",  "voice_locale": "fr-FR" }
]
```

---

## Sessions

### `POST /api/sessions`

Open a session. The response carries the token and the agent's opening question.

**Request:**
```json
{
  "client_id": "8B0F0C9A-5C1E-4D9A-9C2B-3E4F5A6B7C8D",
  "language_hint": "fr"
}
```

- `client_id` (required): an identifier the app generates once and keeps. The daily
  turn cap is counted per `client_id`.
- `language_hint` (optional): one of `ar`, `de`, `en`, `fr`. Used for the greeting only;
  the session language is set by what the client actually says. Any other value is
  `422`.

**Response `201`:**
```json
{
  "session_id": "s_9f1c2e",
  "session_token": "st_2c5b...",
  "language": "fr",
  "greeting": {
    "text": "Bonjour, comment puis-je vous aider ?",
    "language": "fr",
    "voice_locale": "fr-FR"
  }
}
```

`language` is `null` when no hint was given; the greeting is then in English.

### `POST /api/sessions/{session_id}/turns`

Send what the client said and receive the agent's turn as a Server-Sent Events stream.

**Request:**
```json
{ "text": "Quels sont vos horaires d'ouverture ?" }
```

**Response `200`, `Content-Type: text/event-stream`.** Events arrive in this order:

```
event: language
data: {"language": "fr", "voice_locale": "fr-FR", "confidence": 0.6}

data: "Nous "
data: "sommes ouverts "
data: "de 9h à 18h."

event: sentence
data: {"index": 0, "text": "Nous sommes ouverts de 9h à 18h.", "language": "fr", "voice_locale": "fr-FR"}

event: sources
data: [{"kind": "wiki", "title": "Opening hours", "location": "opening-hours.md", "snippet": "We are open 9:00-18:00 ..."}]

event: turn
data: {"kind": "answer", "source": "wiki", "language": "fr"}

data: [DONE]
```

- **Token frames** are unnamed `data:` lines carrying a JSON-encoded string, so a token
  containing a newline survives. Render them as they arrive.
- **`sentence`** fires each time a complete sentence is available. Speak it immediately
  with the given `voice_locale`; this is what makes the agent live. Sentences are
  numbered from 0 within the turn.
- **`language`** is the detected language for this turn and is emitted first. When the
  client could not be understood as any supported language and the session has no
  language yet, `language` is `null` and the turn is a question asking the client to
  continue in a supported language, in English.
- **`sources`** lists what the answer drew from. `kind` is `wiki` (with `location`, the
  file path under `virtualagent/resources`) or `web` (with `url`). The array is empty
  when the turn's source is `none`.
- **`turn`** closes the turn. `kind` is `answer`, `question` (the agent is asking the
  client something) or `no_answer` (the agent said it does not know). `source` is
  `wiki`, `web` or `none` (MISSION hard invariant 3). A `question` turn has source
  `none` when it is about language, and `wiki` or `web` when it is a clarification.
- **`data: [DONE]`** terminates the stream.

**Errors:**
- `401` no bearer token
- `403` the token belongs to a different session
- `404` unknown session
- `422` empty `text`
- `429` the client has used its 100 turns in the last 24 hours (MISSION hard invariant 5). Body: `{"detail": "...", "resets_at": "<ISO 8601>"}`

### `GET /api/sessions/{session_id}`

The transcript, owner only.

**Response `200`:**
```json
{
  "session_id": "s_9f1c2e",
  "language": "fr",
  "created_at": "2026-09-03T10:00:00Z",
  "turns": [
    { "role": "agent", "text": "Bonjour, comment puis-je vous aider ?", "language": "fr", "kind": "question", "source": "none" },
    { "role": "client", "text": "Quels sont vos horaires d'ouverture ?", "language": "fr" },
    { "role": "agent", "text": "Nous sommes ouverts de 9h à 18h.", "language": "fr", "kind": "answer", "source": "wiki" }
  ]
}
```

### `DELETE /api/sessions/{session_id}`

Ends the session and discards its transcript. `204`. Owner only.

---

## The voice contract with the app

The service decides **what** is said and in **which voice locale**; the device's own
speech engines do the listening and the speaking. The app:

1. Recognises speech in the session's current language (the device locale if it is one
   of the four, else English, until the first `language` event).
2. Sends the transcript as a turn.
3. Speaks each `sentence` event as it arrives, in its `voice_locale`.
4. Switches its recogniser to the `language` event's locale for the next turn.

Nothing in the API is specific to speech input: typed text goes through the same route.
