---
description: Run Dark Factory validation — the Python service (ruff + ruff format + mypy + pytest), the iOS manifest check, and the MISSION invariant guard.
argument-hint: (no arguments — reads $ARTIFACTS_DIR/implementation.md and git diff)
---

# Dark Factory Validation

**Workflow ID**: $WORKFLOW_ID

---

## Your Mission

Run the Virtual Agent's validation suite and fix any failures. The product is one
Python/FastAPI service under `app/backend/` (uv-managed) plus a SwiftUI iOS app under
`app/ios/` that cannot be compiled on this machine (see `CLAUDE.md` for the
authoritative command list). This validate step runs the same checks a human would run
before committing: exactly the rungs of `python harness/ci.py --quick`.

**Golden rule**: run each check, read the error, fix the root cause (not the
test), re-run until green. Never modify tests to make them pass — that's an
explicit FACTORY_RULES.md §2 violation.

---

## Phase 1: SCOPE — What Did the Implementation Touch?

The diff may be service-only, app-only, wiki-only, docs-only, or a mix. Run only the
checks that apply, so we don't waste tokens re-validating untouched layers.

```bash
git diff --name-only $BASE_BRANCH...HEAD
```

Classify each changed file:

| Path prefix            | Layer     |
|------------------------|-----------|
| `app/backend/`         | service   |
| `app/ios/`             | app       |
| `virtualagent/resources/` | wiki   |
| `docs/API.md`          | contract (service AND app must both be checked) |
| `*.md`, `docs/`        | docs only |
| `.github/`, `deploy/`, `harness/`, `.factory/`, `FACTORY_RULES.md`, `MISSION.md`, `CLAUDE.md` | **forbidden — see hard rules** |

**Hard rules (FACTORY_RULES.md §5):**

- If the diff touches `FACTORY_RULES.md`, `MISSION.md`, `CLAUDE.md` or `docs/virtualagent.prd.md` — STOP and
  write a validation BLOCKED artifact. Governance files are not factory-editable.
- If the diff touches `.github/`, `deploy/`, `harness/`, `.factory/`, `.env*`, or `.archon/config.yaml` —
  STOP and write a validation BLOCKED artifact.
- If the diff touches `app/backend/auth.py`, `app/backend/rate_limit.py`, or the language-set
  definitions in `app/backend/languages.py` — STOP and write a validation BLOCKED artifact.
- If nothing under `app/` changed and only docs or wiki files changed, run the
  fast path (see §5.4 below). A wiki change still needs the service to index it: run
  Phase 2.5 (pytest) so `test_wiki.py` exercises the reader against the fixture wiki, and
  confirm the new file has a `#` heading and is `.md` or `.txt`.

**PHASE_1_CHECKPOINT:**
- [ ] Touched layers identified
- [ ] No protected files modified

---

## Phase 2: SERVICE CHECKS (if the service layer touched)

Commands per `CLAUDE.md` §Lint, Format, Type Check and §Testing. All tool commands run
from `app/backend/` so `pyproject.toml` config (ruff rules, mypy settings, pytest asyncio
mode) is picked up.

### 2.1 Ensure deps are installed

```bash
# uv sync is idempotent — fast no-op if .venv is already populated.
(cd app/backend && uv sync --all-extras)
```

### 2.2 Ruff lint

```bash
cd app/backend && uv run ruff check .
```

**If fails:**
1. Try auto-fix: `cd app/backend && uv run ruff check --fix .`
2. Re-run `cd app/backend && uv run ruff check .`
3. If still failing, manually fix the reported issues

**Record result**: Pass / Fail (fixed)

### 2.3 Ruff format check

```bash
cd app/backend && uv run ruff format --check .
```

**If fails:**
1. Auto-fix — **scoped to files this branch modified** so we never reformat unrelated (protected) files:
   ```bash
   git diff --name-only origin/main -- 'app/backend/*.py' 'app/backend/**/*.py' \
     | xargs -r uv run --project app/backend ruff format
   ```
   Do NOT run `uv run ruff format .` repo-wide — that has caused PRs to be auto-rejected for touching protected files (`auth.py`, `rate_limit.py`) with cosmetic-only collateral.
2. Verify: `cd app/backend && uv run ruff format --check .` — if this still fails on files outside the diff, leave them alone; record `Pass (drift remains in unmodified files)`.

**Record result**: Pass / Fail (fixed)

### 2.4 Mypy type check

```bash
cd app/backend && uv run mypy .
```

**If fails:**
1. Read each error carefully — prefer adding a real type annotation over `# type: ignore`
2. Fix by tightening types at the source, not by silencing mypy
3. `# type: ignore` is only acceptable when bridging an untyped third-party dep, with a comment explaining why

**Record result**: Pass / Fail (fixed)

### 2.5 Pytest

```bash
cd app/backend && uv run pytest tests -xvs
```

**If the implementation added no tests** for a bug fix or feature, that's a validation failure — the implement step violated FACTORY_RULES.md §2 ("Must include tests"). Either add the missing tests yourself (fakes at the provider boundary per `CLAUDE.md` §Testing — never the network) or mark validation BLOCKED with a clear reason.

**If fails:**
1. Identify which test(s) failed
2. Is it an implementation bug or test bug? Implementation bugs = fix the source. Test bugs in tests YOU just wrote = fix the test. Test bugs in pre-existing tests = **do not modify**, this likely means your change regressed something — fix the source.
3. Re-run

**Record result**: Pass ({N} tests) / Fail (fixed)

**PHASE_2_CHECKPOINT:**
- [ ] Ruff lint passes
- [ ] Ruff format passes
- [ ] Mypy passes
- [ ] Pytest passes with a non-zero count

---

## Phase 3: APP CHECKS (if the app layer touched)

There is no Swift toolchain on this machine. What can be checked is what
`harness/static_ios.py` checks, and it is honest about being less than a compile:

```bash
cd app/backend && uv run python ../../harness/static_ios.py
```

It asserts the XcodeGen spec parses and declares the iOS target with the microphone
and speech-recognition usage descriptions, the Info.plist parses, and every Swift file
is non-empty with balanced braces and parentheses.

Beyond that, read every changed Swift file once, slowly, for:
- a `Codable` model that no longer matches `docs/API.md` field for field
- a user-facing string added outside `Phrases.swift`, or added in fewer than four languages
- a `URLSession` call outside `AgentAPI.swift`, or SSE parsing outside `SSEParser.swift`
- a third-party import (there are none and there may be none)

**Record result**: Manifests pass / fail; review notes.

Then add a `## Manual verification` section to the implementation artifact listing
what a person with a Mac runs (`xcodegen generate`, build, `Cmd+U`, the flow on a
device). The validator cannot confirm an app fix; a human does (`.factory/decisions.md`
D-005).

**PHASE_3_CHECKPOINT:**
- [ ] `static_ios.py` passes
- [ ] Changed Swift files reviewed against the conventions above
- [ ] Manual verification section written

---

## Phase 4: MISSION INVARIANTS (always — cheap guard against silent regressions)

`CLAUDE.md` §The Contract That Must Not Regress lists behaviours that MUST NOT change.
If the diff touches `app/backend/agent/`, `app/backend/languages.py`,
`app/backend/wiki/`, `app/backend/search/`, `app/backend/routes/`, `app/backend/config.py`,
`app/backend/llm/`, or `app/ios/VirtualAgent/Models.swift`, verify:

- [ ] `SUPPORTED_LANGUAGES` is still exactly `{"fr", "en", "de", "ar"}` and `VOICE_LOCALES`, `LANGUAGE_NAMES`, `GREETINGS`, `NO_ANSWER_TEXTS` have exactly those keys
- [ ] `Agent.respond()` still searches the wiki first and calls the web only when the wiki has no confident answer; the fixed no-answer turn still does not consult the model
- [ ] Every turn still declares a `source` in `{wiki, web, none}` and a `kind` in `{answer, question, no_answer}`
- [ ] Every `/api/sessions/{session_id}/...` route still has `Depends(get_current_session)`
- [ ] `DAILY_TURN_CAP` is still 100 over `WINDOW_HOURS` 24, defined only in `rate_limit.py`
- [ ] Chat still goes through `OpenRouterClient`; `EMBEDDING_MODEL` is still `openai/text-embedding-3-small`
- [ ] `sentence` events still fire as sentences complete, before the `turn` event; the SSE framing in `docs/API.md` is unchanged (tokens as JSON strings in unnamed `data:` frames, `language` first, `sources` then `turn` before `data: [DONE]`)

Any regression on the above is an automatic validation FAIL — even if static
checks pass. Write the regression into the artifact and stop.

**PHASE_4_CHECKPOINT:**
- [ ] MISSION invariants verified (or skipped because diff didn't touch relevant files)

---

## Phase 5: ARTIFACT — Write validation.md

Write to `$ARTIFACTS_DIR/validation.md`:

```markdown
# Validation Results

**Generated**: {YYYY-MM-DD HH:MM}
**Workflow ID**: $WORKFLOW_ID
**Status**: {ALL_PASS | FIXED | BLOCKED}
**Layers touched**: {service, app, wiki, docs, or combinations}

---

## Summary

| Check              | Layer   | Result        | Details                |
|--------------------|---------|---------------|------------------------|
| Ruff lint          | service | pass / fixed  | {N} auto-fixed         |
| Ruff format        | service | pass / fixed  |                        |
| Mypy               | service | pass / fixed  | {N} type errors fixed  |
| Pytest             | service | pass ({N})    |                        |
| iOS manifests      | app     | pass / fail   | {N} checks             |
| MISSION invariants | all     | pass          | {list of invariants checked} |

---

## Files Modified During Validation

{If validation had to fix any files, list them with a one-line reason per file.}

---

## Manual verification

{App changes only: what a person with a Mac runs.}

---

## Issues Remaining

{If BLOCKED: what check failed, what was tried, what manual intervention is needed.}
```

### 5.4 Docs-only fast path

If Phase 1 determined the diff is docs-only (no files under `app/` or
`virtualagent/resources/` changed), skip Phases 2-4 entirely and write:

```markdown
# Validation Results

**Status**: ALL_PASS
**Layers touched**: docs
**Skipped**: service + app checks (no source changes)

This PR is documentation-only. Static checks and tests are not applicable.
Reviewed that only `.md` files and/or `docs/` were modified.
```

**PHASE_5_CHECKPOINT:**
- [ ] `$ARTIFACTS_DIR/validation.md` written
- [ ] Status accurately reflects what ran and what passed

---

## Phase 6: OUTPUT — Report back to the workflow

### If all pass:

```markdown
## Validation Complete

**Workflow ID**: `$WORKFLOW_ID`

Service: ruff lint / format / mypy / pytest — all pass ({N} tests)
App: manifests pass; {N} Swift files reviewed (not compiled)
MISSION invariants: verified

Artifact: `$ARTIFACTS_DIR/validation.md`

Next: proceed to create-pr.
```

### If blocked:

```markdown
## Validation BLOCKED

**Workflow ID**: `$WORKFLOW_ID`

### Failed check
{check-name}: {short error summary}

### What was tried
1. {attempt 1}
2. {attempt 2}

### Required action
{what needs manual intervention — or why this is a real bug in the implementation
that the implement step produced}

Artifact: `$ARTIFACTS_DIR/validation.md`
```

---

## Success Criteria

- **SERVICE_LINT_PASS**: `uv run ruff check .` exits 0
- **SERVICE_FORMAT_PASS**: `uv run ruff format --check .` exits 0
- **SERVICE_TYPE_PASS**: `uv run mypy .` exits 0
- **SERVICE_TESTS_PASS**: `uv run pytest tests -xvs` all green with a non-zero count
- **APP_MANIFESTS_PASS**: `harness/static_ios.py` exits 0 (if the app was touched)
- **INVARIANTS_PASS**: no regressions per CLAUDE.md §The Contract That Must Not Regress
- **ARTIFACT_WRITTEN**: `$ARTIFACTS_DIR/validation.md` exists with accurate status
