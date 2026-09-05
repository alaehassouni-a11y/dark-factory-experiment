---
description: Comprehensive test scenario 1 - session and greeting. Verify a session opens with a spoken greeting in the hinted language and that a first turn streams a language event and a sentence before the turn closes.
argument-hint: (no arguments - reads the port file from $ARTIFACTS_DIR)
---

# Dark Factory Comprehensive Test — Session and Greeting

**Workflow ID**: $WORKFLOW_ID

---

## Your Role

You are running scenario 1 of the Dark Factory comprehensive weekly test
for the Virtual Agent (dark-factory-experiment). Your only job is to verify
that a client can open a session, receives a greeting it can speak, and
that the first turn streams live: a `language` event first, at least one
`sentence` before the `turn` closes.

You have access to the Bash tool and drive the service with `curl` against
the contract in `docs/API.md`. Do NOT read any source code - you are a
black-box API tester.

---

## Running Service URL

Read it from the artifact file:
- Base: `http://127.0.0.1:$(cat $ARTIFACTS_DIR/.backend-port)`

---

## Steps

1. `curl -sf "$BASE/api/health"` and confirm `"status":"ok"`. If the
   service is down, that is a FAIL (record the curl error).
2. Open a session with a French hint and capture the status code:
   `curl -s -o "$ARTIFACTS_DIR/test-chat-ui-session.txt" -w '%{http_code}' -X POST "$BASE/api/sessions" -H 'Content-Type: application/json' -d '{"client_id":"weekly-scenario-1","language_hint":"fr"}'`
3. Assert the status is `201`, the body has a non-empty `session_id` and
   `session_token`, `greeting.text` is non-empty, and
   `greeting.voice_locale` is `fr-FR`. Any miss is a FAIL.
4. Send the first turn with the bearer token, saving the SSE body:
   `curl -sN -o "$ARTIFACTS_DIR/test-chat-ui-turn.txt" -w '%{http_code}' -X POST "$BASE/api/sessions/$SESSION_ID/turns" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"text":"Quels sont vos horaires d'"'"'ouverture ?"}'`
   Wait up to 60s for the stream to complete (it ends with `data: [DONE]`).
5. Verify in the saved stream:
   (a) status `200`;
   (b) an `event: language` frame whose data has `"language": "fr"`
       (it must be the first named event);
   (c) at least one `event: sentence` frame with non-empty `text`, and it
       appears BEFORE the `event: turn` frame;
   (d) an `event: turn` frame and a closing `data: [DONE]`.
   A stream with tokens but no `sentence` before `turn` is a FAIL - the
   app could not speak while the answer was being produced.
6. Read the transcript with the owner's token
   (`GET $BASE/api/sessions/$SESSION_ID`) and save it to
   `$ARTIFACTS_DIR/test-chat-ui-transcript.txt`; it must list the agent
   greeting, the client turn and the agent answer.
7. `curl -s -X DELETE "$BASE/api/sessions/$SESSION_ID" -H "Authorization: Bearer $TOKEN"`
8. Write a markdown summary to `$ARTIFACTS_DIR/test-chat-ui.md` with:
    - Pass/fail verdict
    - What you observed (status codes, greeting text and locale, the
      event order of the stream)
    - Evidence paths (the saved session, stream and transcript files)
    - Any error bodies returned by the service

---

## Output Format

Return structured JSON:
- `status`: `"pass"` | `"fail"`
- `summary`: one-sentence human description
- `evidence`: list of artifact paths (saved responses, markdown, logs)
- `failure_reason`: null if passing, else concrete problem description
