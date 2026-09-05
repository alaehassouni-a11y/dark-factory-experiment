---
description: Comprehensive test scenario 4 - language following and privacy. Verify Arabic is detected as Arabic, an unsupported language yields a spoken question with source none, and another session's token cannot read a session.
argument-hint: (no arguments - reads the port file from $ARTIFACTS_DIR)
---

# Dark Factory Comprehensive Test — Language Following and Privacy

**Workflow ID**: $WORKFLOW_ID

---

## Your Role

You are running scenario 4 of the Dark Factory comprehensive weekly test
for the Virtual Agent. Verify two MISSION hard invariants from the
outside: the agent follows the client's language within the supported set
and asks when it cannot (invariant 1), and a session is private to the
client that opened it (invariant 4).

You have Bash and drive the service with `curl` against `docs/API.md`.
Do NOT read source code.

---

## Running Service URL

- Base: `http://127.0.0.1:$(cat $ARTIFACTS_DIR/.backend-port)`

---

## Steps

1. Confirm `GET $BASE/api/health` reports `"status":"ok"`.
2. Open session A: `POST $BASE/api/sessions` with
   `{"client_id":"weekly-scenario-4a"}`; assert `201`, capture
   `SESSION_A` and `TOKEN_A`.
3. Send an Arabic question on session A (exactly):
   `{"text":"ما هي ساعات العمل لديكم؟"}`
   Save the SSE body to `$ARTIFACTS_DIR/test-conversation-history-ar.txt`
   and wait for `data: [DONE]`.
4. Verify the `event: language` frame has `"language": "ar"` and
   `"voice_locale": "ar-SA"`, and that at least one `event: sentence`
   frame precedes the `event: turn` frame. Any other language is a FAIL -
   the agent did not follow the client.
5. Open a FRESH session B (not a continuation of A):
   `POST $BASE/api/sessions` with `{"client_id":"weekly-scenario-4b"}`;
   assert `201`, capture `SESSION_B` and `TOKEN_B`.
6. Send a Spanish sentence on session B (exactly):
   `{"text":"¿Dónde está el baño, por favor?"}`
   Save the SSE body to `$ARTIFACTS_DIR/test-conversation-history-es.txt`.
7. Verify: the `event: language` frame has `"language": null`; the
   `event: turn` frame has `"kind": "question"` and `"source": "none"`;
   and at least one `event: sentence` frame exists (the agent ASKED, out
   loud, for a supported language). An `answer` turn, a `wiki` or `web`
   source, or a detected language of `es` is a FAIL.
8. Privacy: read session A with session B's token:
   `curl -s -o "$ARTIFACTS_DIR/test-conversation-history-403.txt" -w '%{http_code}' "$BASE/api/sessions/$SESSION_A" -H "Authorization: Bearer $TOKEN_B"`
   The status MUST be `403`. Then read session A with no token at all and
   assert `401`. Then read it with `TOKEN_A`, save the transcript to
   `$ARTIFACTS_DIR/test-conversation-history-transcript.txt`, and assert
   `200` with the greeting, the Arabic client turn and the agent answer
   listed in `turns`.
9. `DELETE` both sessions with their own tokens.
10. Write a markdown summary to `$ARTIFACTS_DIR/test-conversation-history.md`
    including the detected languages, the verbatim `turn` frame from the
    Spanish turn, the three status codes from step 8, and the evidence
    paths.

---

## Output Format

Return structured JSON:
- `status`: `"pass"` | `"fail"`
- `summary`: one-sentence description
- `evidence`: artifact paths
- `failure_reason`: null if passing, else concrete problem
