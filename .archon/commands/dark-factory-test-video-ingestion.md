---
description: Comprehensive test scenario 2 - wiki coverage. Verify the wiki loaded and that a wiki-covered question is answered from the wiki, naming the document it drew from.
argument-hint: (no arguments - reads the port file from $ARTIFACTS_DIR)
---

# Dark Factory Comprehensive Test — Wiki Coverage

**Workflow ID**: $WORKFLOW_ID

---

## Your Role

You are running scenario 2 of the Dark Factory comprehensive weekly test
for the Virtual Agent. Verify that the wiki is loaded and consulted: a
question the wiki covers must be answered with turn source `wiki` and a
`sources` list that names the document (MISSION hard invariants 2 and 3).

You have Bash and drive the service with `curl` against `docs/API.md`.
Do NOT read source code.

---

## Fixed Test Wiki (locked fixture, do NOT change)

The service was started by `harness/serve.py` against the harness fixture
wiki, which contains opening hours in English and in French, and a returns
policy. Any question about opening hours is wiki-covered.

---

## Running Service URL

- Base: `http://127.0.0.1:$(cat $ARTIFACTS_DIR/.backend-port)`

---

## Steps

1. Fetch `GET $BASE/api/health`, save it to
   `$ARTIFACTS_DIR/test-video-ingestion-health.txt`, and assert
   `"status":"ok"` and `wiki_documents >= 1`. A health body with
   `wiki_documents: 0` is a FAIL - the wiki did not load.
2. Open a session: `POST $BASE/api/sessions` with
   `{"client_id":"weekly-scenario-2","language_hint":"en"}`; assert `201`
   and capture `session_id` and `session_token`.
3. Send a wiki-covered question and save the SSE body to
   `$ARTIFACTS_DIR/test-video-ingestion-turn.txt`:
   `POST $BASE/api/sessions/$SESSION_ID/turns` with the bearer token and
   body `{"text":"What are your opening hours?"}`. Wait up to 60s for
   `data: [DONE]`.
4. Verify in the saved stream:
   (a) status `200` and an `event: language` frame with `"language": "en"`;
   (b) an `event: sources` frame whose data is a non-empty JSON array in
       which every entry has `"kind": "wiki"` and a non-empty `location`
       (a file path under the wiki folder, e.g. `opening-hours.md`);
   (c) an `event: turn` frame with `"source": "wiki"` and
       `"kind": "answer"`;
   (d) at least one `event: sentence` frame before `event: turn`.
5. Ask the same question in French on the same session
   (`{"text":"Quels sont vos horaires d'ouverture ?"}`), save the stream to
   `$ARTIFACTS_DIR/test-video-ingestion-turn-fr.txt`, and verify the
   `language` event says `fr`, the `turn` source is still `wiki`, and the
   `sources` entries still carry a `location`.
6. `DELETE $BASE/api/sessions/$SESSION_ID` with the bearer token.
7. Write a markdown summary to `$ARTIFACTS_DIR/test-video-ingestion.md`
   including the health counts (`wiki_documents`, `wiki_chunks`), the
   `sources` locations observed, and the evidence paths.

---

## Failure Criteria

FAIL if any of:
- Health is not `ok` or reports `wiki_documents` below 1
- The turn's `source` is anything other than `wiki` (a `web` or `none`
  answer to a wiki-covered question means the wiki was not consulted
  first)
- The `sources` array is empty, or any entry lacks `kind: "wiki"` or a
  `location`
- No `sentence` event arrived before the `turn` event
- The stream never reached `data: [DONE]` within 60s

---

## Output Format

Return structured JSON:
- `status`: `"pass"` | `"fail"`
- `summary`: one-sentence description
- `evidence`: artifact paths
- `failure_reason`: null if passing, else concrete problem
