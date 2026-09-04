---
description: Implement a fix from investigation artifact for the Dark Factory — code changes, uv-managed Python deps, light validation, commit (no PR).
argument-hint: (reads $ARTIFACTS_DIR/investigation.md, $ARTIFACTS_DIR/plan.md)
---

# Dark Factory — Fix Issue

**Workflow ID**: $WORKFLOW_ID

---

## Your Mission

Execute the implementation plan from the investigation/plan artifact:

1. Load and validate the artifact
2. Ensure git state is correct
3. Install dependencies (the uv-managed Python service; the iOS app has none)
4. Implement the changes exactly as specified
5. Run a light inline validation (the heavy validation is done by `dark-factory-validate`)
6. Commit changes
7. Write implementation report

**Golden rule**: Follow the artifact. If something seems wrong, validate it first — don't silently deviate. And read `CLAUDE.md` before touching any code — it's the code-style contract.

---

## Phase 1: LOAD — Get the Artifact

```bash
cat "$ARTIFACTS_DIR/investigation.md" 2>/dev/null || cat "$ARTIFACTS_DIR/plan.md"
```

Extract: issue number, title, type, files to modify, implementation steps, test cases to add.

**If neither file exists**, STOP with a clear error. The upstream investigate/plan step failed.

**PHASE_1_CHECKPOINT:**
- [ ] Artifact loaded
- [ ] Steps understood

---

## Phase 2: VALIDATE ARTIFACT

Ask yourself:
- Does the proposed fix actually address the root cause?
- Are there obvious problems with the approach?
- Does the plan touch any protected files (`MISSION.md`, `FACTORY_RULES.md`, `CLAUDE.md`, `.github/`, `.env*`, `.archon/config.yaml`)? **If so, STOP.**

**PHASE_2_CHECKPOINT:**
- [ ] Plan is coherent
- [ ] No protected files in scope

---

## Phase 3: GIT-CHECK — Ensure Correct State

```bash
git branch --show-current
git worktree list
git status --porcelain
```

Archon runs this workflow inside a worktree created by the orchestrator. Use that worktree as-is. Do NOT create a new branch inside an existing worktree.

**If somehow on `main` with a clean tree** (manual invocation, no worktree): create `fix/issue-{number}-{slug}` from `$BASE_BRANCH`.

**PHASE_3_CHECKPOINT:**
- [ ] On a non-main feature branch
- [ ] Working directory clean (or clean after stashing ignored files)

---

## Phase 4: DEPENDENCIES

The Virtual Agent is one uv-managed Python service. The iOS app has no third-party dependencies and no toolchain on this machine. Follow `CLAUDE.md` §Running the Service exactly.

### 4.1 Service deps

```bash
# uv reads app/backend/pyproject.toml + uv.lock, creates .venv, installs runtime + dev deps.
(cd app/backend && uv sync --all-extras)
```

If `pyproject.toml` was modified by the plan, re-run the sync — uv will update `uv.lock` automatically.

### 4.2 Failure handling

If install fails, STOP and report the error. Do not proceed to implementation with missing dependencies — you will waste iterations on spurious failures.

**PHASE_4_CHECKPOINT:**
- [ ] Service venv populated

---

## Phase 5: IMPLEMENT — Make Changes

### 5.1 Execute each step from the artifact

For each step in the Implementation Plan:

1. Read the target file (use the Read tool)
2. Make the change exactly as specified
3. After any Python edit, spot-check with `python -m py_compile {file}` to catch syntax errors fast
4. After any Swift edit, re-read the whole file slowly: there is no compiler on this machine (`CLAUDE.md` §Testing)

### 5.2 Implementation rules

**DO:**
- Follow artifact steps in order
- Match existing code style per `CLAUDE.md` §Code Conventions
- Keep the language set in `languages.py`, the cap in `rate_limit.py`, the token check in `auth.py`, the wire format in `routes/sessions.py`
- Keep all app networking in `AgentAPI.swift` and every app string, in all four languages, in `Phrases.swift`
- Use async everywhere in the service (CLAUDE.md §Python (service))
- Fake the providers at the boundary in tests, never the network (CLAUDE.md §Testing)
- Add tests for bug fixes (regression test) and features (per FACTORY_RULES.md §3)

**DON'T:**
- Refactor unrelated code or "improve" things outside the plan (CLAUDE.md §Dos and Don'ts)
- Add an inference provider, change the embedding model, add or remove a language, or let the web answer before the wiki
- Add a database, an ORM, accounts, a third-party Swift package, or a second client
- Modify `MISSION.md`, `FACTORY_RULES.md`, `CLAUDE.md`, `.github/`, `.env*`, or `.archon/config.yaml`
- Change the SSE format in `routes/sessions.py` or `docs/API.md` without changing `Models.swift` and `SSEParser.swift` in the same PR

### 5.3 Track deviations

If you must deviate from the artifact (e.g., the artifact referenced a file that has been refactored), note what changed and why in `$ARTIFACTS_DIR/implementation.md`.

**PHASE_5_CHECKPOINT:**
- [ ] All artifact steps executed
- [ ] Python files parse-clean
- [ ] Tests added where required

---

## Phase 6: VERIFY — Light inline validation

This is a fast sanity check before commit. The full, exhaustive validation is
done by the separate `dark-factory-validate` node later in the workflow — so
don't spend iterations chasing every lint warning here. Just check the code
actually compiles / parses / imports.

### 6.1 Backend sanity

If backend files were touched:

```bash
cd app && uv --project backend run python -c "import backend.main"
```

(This one stays in `app/` because the `backend.main` import path requires `app/` as the package parent — not `app/backend/`.)

If that import fails, read the traceback and fix the root cause.

### 6.2 App sanity

If Swift files were touched:

```bash
cd app/backend && uv run python ../../harness/static_ios.py
```

That checks the manifests and that every Swift file balances its braces. It is not a compile; there is no Swift toolchain here, and the PR body must carry a `## Manual verification` section for the person with a Mac.

### 6.3 What NOT to do here

- Don't run ruff/mypy/pytest — `dark-factory-validate` owns those.
- This is a tight loop to catch "did I just break imports" before we commit.

**PHASE_6_CHECKPOINT:**
- [ ] Backend imports cleanly (if touched)
- [ ] App manifests pass (if touched)

---

## Phase 7: COMMIT

### 7.1 Stage and review

```bash
git add -A
git status
```

Review carefully — make sure no stray files (venv output, `.pytest_cache`, `node_modules/`) are being staged.

### 7.2 Commit message

Use Conventional Commits per CLAUDE.md §Commit and PR Conventions. Subject line under 72 chars. Body explains **why**, not **what**.

```
{fix|feat|chore|refactor|docs|test}: {brief description}

{Problem statement from artifact — 1-2 sentences}

{Changes:}
- {change 1}
- {change 2}
- Added test for {case}

Fixes #{issue-number}
```

```bash
git commit -m "$(cat <<'EOF'
fix: {title}

{problem statement}

- {change 1}
- {change 2}

Fixes #{number}
EOF
)"
```

**PHASE_7_CHECKPOINT:**
- [ ] All changes committed
- [ ] `Fixes #N` line present in commit body

---

## Phase 8: WRITE — Implementation Report

Write to `$ARTIFACTS_DIR/implementation.md`:

```markdown
# Implementation Report

**Issue**: #{number}
**Generated**: {YYYY-MM-DD HH:MM}
**Workflow ID**: $WORKFLOW_ID

---

## Tasks Completed

| # | Task | File | Status |
|---|------|------|--------|
| 1 | {task} | `app/backend/routes/x.py` | done |
| 2 | {task} | `app/backend/tests/test_x.py` | done |

---

## Files Changed

| File | Action | Lines |
|------|--------|-------|
| `app/backend/routes/x.py` | UPDATE | +{N}/-{M} |
| `app/backend/tests/test_x.py` | CREATE | +{N} |

---

## Deviations from Investigation

{If none: "Implementation matched the investigation exactly."}

---

## Inline Sanity Check Results

| Check | Result |
|-------|--------|
| Backend import | pass |
| iOS manifests | pass |

Full validation deferred to `dark-factory-validate` node.
```

**PHASE_8_CHECKPOINT:**
- [ ] Implementation artifact written

---

## Phase 9: OUTPUT

```markdown
## Implementation Complete

**Issue**: #{number}
**Branch**: `{branch-name}`

### Changes Made

{one-line per file}

### Next Step

Proceeding to validation (`dark-factory-validate`).
```

---

## Success Criteria

- **PLAN_EXECUTED**: All investigation steps completed
- **SANITY_PASSED**: Service imports, app manifests clean (if applicable)
- **CHANGES_COMMITTED**: All changes committed with `Fixes #N` in the body
- **IMPLEMENTATION_ARTIFACT**: `$ARTIFACTS_DIR/implementation.md` written
- **READY_FOR_VALIDATE**: Workflow continues to `dark-factory-validate`
