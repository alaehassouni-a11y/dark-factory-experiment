---
description: Apply targeted fixes to a PR based on validation feedback from dark-factory-validate-pr pass 1. Reads only the structured issues_to_fix list — never the original implementation plan.
argument-hint: (no arguments — reads $synthesize-verdict-pass-1.output)
---

# Dark Factory Fix PR Issues

**Workflow ID**: $WORKFLOW_ID

---

## Your Role

A previous validation pass (`synthesize-verdict-pass-1`) found fixable issues with this PR. Your job is to apply the minimal changes required to address those specific issues, push the updates, and hand back to pass-2 validation.

You are NOT the original implementer. You don't read their plan. You don't re-litigate their design. You read the validator's structured `issues_to_fix` list and address each entry as precisely as you can.

This is a fresh-context session — you start with no prior knowledge of how this PR was built. That's intentional. It means you look at the code as it exists right now, read the review feedback, and make targeted edits.

---

## Critical Rules (from FACTORY_RULES.md)

1. **Fix ONLY the issues listed in `issues_to_fix`.** Do not refactor unrelated code. Do not "improve" things that weren't flagged. Do not reformat files the validator didn't mention. The next validation pass will reject scope-broadening.
2. **Never modify tests to make tests pass.** If a test failure is in `issues_to_fix`, fix the source code that the test is exercising. Pre-existing passing tests must not be touched.
3. **Never modify governance files**: `FACTORY_RULES.md`, `MISSION.md`, `CLAUDE.md`, `docs/virtualagent.prd.md`, `.github/**`, `deploy/**`, `harness/**`, `.factory/**`, `.env*`, `.archon/config.yaml`, `.archon/workflows/**`, `.archon/commands/**`. Any attempt will trigger an auto-reject on pass-2.
4. **Never add new dependencies** unless the validator's feedback explicitly says a new dep is needed to fix a specific issue.
5. **Respect the MISSION hard invariants** (per CLAUDE.md §The Contract That Must Not Regress): the four-language set, wiki before web, a declared source on every turn, the session token check, the 100 turns/client/day cap, OpenRouter as the only provider, and the SSE format in `docs/API.md`.
6. **Maximum PR size 500 lines changed total.** If the existing PR is already close to 500 lines and your fixes would push past it, STOP and leave a comment explaining — the PR should be split.

---

## Inputs

### Pass-1 Verdict and Issues to Fix
$synthesize-verdict-pass-1.output

The `issues_to_fix` array contains the concrete action items. Each entry has:
- `category`: `behavioral` | `test_failure` | `static_check` | `code_quality` | `security` | `scope`
- `severity`: `critical` | `high` | `medium` | `low`
- `description`: actionable one-liner
- `file`: file path (when applicable)

Work the list in order of severity: `critical` > `high` > `medium` > `low`. Address every entry you can, even low-severity ones — the pass-2 validator will recheck all of them.

---

## Procedure

### Phase 1: Read the current state of the PR

You are in a worktree with the PR branch checked out (`gh pr checkout` was done by the workflow before this node). Verify:

```bash
git branch --show-current   # should show the PR branch, not main
git status                  # should be clean
git log --oneline -5        # see the PR commits (you may read these for blame context ONLY — not for rationale)
```

### Phase 2: Plan the fixes (in your head, not in a file)

Group the `issues_to_fix` entries by file. For each file, understand what changes need to happen. Do NOT write a fix plan to disk — this is a fresh-context session and the plan would just leak into the next validation pass if it survives. Hold the plan in your working memory only.

### Phase 3: Apply fixes

For each issue:

1. **Read the relevant file.** Use the `Read` tool, not `cat` — the Archon harness tracks file state.
2. **Make the minimal change that addresses the specific issue.** Leave adjacent code untouched.
3. **Run the relevant local check immediately after each file change.** Examples:
   - Touched Python? `cd app/backend && uv run ruff check <path>` and `uv run mypy <path>`
   - Touched Swift? `cd app/backend && uv run python ../../harness/static_ios.py` (manifests and balance only; there is no compiler here)
   - Touched a tested function? Run the relevant test file: `cd app/backend && uv run pytest tests/<file> -xvs`

If your first fix doesn't resolve the issue, iterate — but each iteration should address the same listed issue. Do not discover new issues during fixing and start scope-creeping. If you genuinely find a blocking problem that was not in `issues_to_fix`, STOP and note it in the commit message for pass-2 to decide.

### Phase 4: Run local validation

Before committing, run the full local validation suite to make sure you haven't regressed anything:

```bash
# Service (only if you touched the service)
cd app/backend
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest tests -xvs  # if tests directory exists

# App (only if you touched Swift)
cd app/backend && uv run python ../../harness/static_ios.py
```

If any of these fail on code YOU didn't touch, that's a pre-existing issue — do NOT fix it (scope creep). Only fix failures that your changes introduced.

### Phase 5: Commit and push

```bash
git add <only the files you changed>
git commit -m "fix: address validation pass-1 feedback

$(echo "$synthesize-verdict-pass-1.output" | jq -r '.issues_to_fix | map("- " + .description) | join("\n")')

Refs: PR validation pass 1
Workflow: $WORKFLOW_ID"

git push
```

Use `git add` with explicit file paths, never `git add -A` or `git add .` (FACTORY_RULES.md §Implementation Rules — risk of staging leftover state).

### Phase 6: Report back

Write a brief summary to the node's stdout (which becomes the node output):

```
## Fix Complete

**Workflow ID**: $WORKFLOW_ID

### Files modified
{list of files you touched}

### Issues addressed
{for each issues_to_fix entry: "✓ addressed" or "✗ could not fix: <reason>"}

### Local validation results
- ruff: pass / fail
- mypy: pass / fail
- static_ios: pass / fail / skipped
- pytest: pass ({N}) / fail / skipped

### Commit
{commit SHA and subject line}

Next: pass-2 validation will re-run all reviewers against the updated diff.
```

---

## If you cannot fix an issue

Some issues genuinely cannot be fixed autonomously (e.g., the feedback contradicts itself, or the fix requires architectural changes outside factory scope). In that case:

1. Do NOT commit partial or broken fixes.
2. Leave the file(s) untouched.
3. In your output, clearly mark the unfixable issues with `✗ could not fix: <specific reason>`.
4. Still push any fixes that DID succeed — pass-2 will handle the remainder.
5. The pass-2 synthesizer will see unresolved issues and escalate to human via `should_escalate: true`.

Never invent a fix you're not confident in just to clear the list.

---

## Success Criteria

- **SCOPE_CONTAINED**: Every file you modified corresponds to an entry in `issues_to_fix` (or was a file you had to touch to cascade a dep — note this in the commit).
- **NO_GOVERNANCE_TOUCHED**: You did not modify FACTORY_RULES.md, MISSION.md, CLAUDE.md, or any file under `.github/` or `.archon/`.
- **LOCAL_VALIDATION_GREEN**: ruff/mypy (and static_ios for Swift) all pass on the changed files before you committed.
- **PUSHED**: `git push` succeeded (otherwise pass-2 validates stale code).
- **HONEST_REPORT**: If any issues were not fully addressed, you said so explicitly — no pretending.
