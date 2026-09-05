---
description: Comprehensive test scenario 3 - web fallback. Verify a question the wiki cannot answer falls back to the web, declares source web with page URLs, and answers in the client's language.
argument-hint: (no arguments - reads the port file from $ARTIFACTS_DIR)
---

# Dark Factory Comprehensive Test — Web Fallback

**Workflow ID**: $WORKFLOW_ID

---

## Your Role

You are running scenario 3 of the Dark Factory comprehensive weekly test
for the Virtual Agent. Verify that when the wiki has no confident answer
the agent searches the web, declares it (turn source `web`), names the
pages it drew from, and answers in the client's language (MISSION hard
invariants 2 and 3).

Context: the service runs against the harness fixture wiki (opening hours
in English and French, a returns policy) and stub providers. Anything
outside that wiki is uncovered. Use this exact uncovered question, in
German:
```
Wer hat die Mona Lisa gemalt?
```

You have Bash and drive the service with `curl` against `docs/API.md`.
Do NOT read source code.

---

## Running Service URL

- Base: `http://127.0.0.1:$(cat $ARTIFACTS_DIR/.backend-port)`

---

## Steps

1. Confirm `GET $BASE/api/health` reports `"status":"ok"`. Save the body
   to `$ARTIFACTS_DIR/test-rag-response-health.txt` and note the
   `web_search` field (`configured` is expected under the harness stubs).
2. Open a fresh session: `POST $BASE/api/sessions` with
   `{"client_id":"weekly-scenario-3"}` (no hint); assert `201` and capture
   `session_id` and `session_token`.
3. Send the uncovered German question with the bearer token and save the
   SSE body to `$ARTIFACTS_DIR/test-rag-response-turn.txt`. Wait up to 60s
   for `data: [DONE]`.
4. Verify in the saved stream:
   (a) status `200`;
   (b) an `event: language` frame with `"language": "de"` and
       `"voice_locale": "de-DE"`;
   (c) an `event: sources` frame whose data is a non-empty JSON array in
       which every entry has `"kind": "web"` and a non-empty `url`;
   (d) an `event: turn` frame with `"source": "web"` and
       `"language": "de"`;
   (e) at least one `event: sentence` frame, with `"language": "de"`,
       before the `turn` frame (the answer is spoken in German).
5. Read the transcript (`GET $BASE/api/sessions/$SESSION_ID` with the
   bearer token), save it to `$ARTIFACTS_DIR/test-rag-response-transcript.txt`,
   and verify the last agent turn records `"source": "web"`.
6. `DELETE $BASE/api/sessions/$SESSION_ID` with the bearer token.
7. Write a markdown summary to `$ARTIFACTS_DIR/test-rag-response.md`
   including the detected language, the sentence text, the URLs listed in
   `sources`, and the evidence paths.

---

## Failure Criteria

FAIL if any of:
- Response is an error or the stream never reaches `data: [DONE]`
- The `turn` source is `wiki` (the wiki does not cover the question - a
  wiki answer here is an invented one) or `none` while `web_search` is
  `configured`
- The `sources` array is empty or any entry lacks `kind: "web"` or a `url`
- The `language` event or the `turn` is not `de`

---

## Output Format

Return structured JSON:
- `status`: `"pass"` | `"fail"`
- `summary`: one-sentence description
- `evidence`: artifact paths
- `failure_reason`: null if passing, else concrete problem
