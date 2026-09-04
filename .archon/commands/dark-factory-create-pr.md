---
description: Create a draft PR for the Dark Factory fix workflow, filling in the repo's PR template from implementation artifacts.
argument-hint: (reads workflow artifacts and $classify-issue.output)
---

Create a draft pull request for the current branch.

## Context

- **Issue**: $ARGUMENTS
- **Classification**: $classify-issue.output
- **Issue title**: $classify-issue.output.title

## Instructions

1. Check git status — ensure all changes are committed. If uncommitted changes exist, stage and commit them with a conventional-commits prefix (`feat:`, `fix:`, `chore:`, etc. per CLAUDE.md §Commit and PR Conventions).
2. Push the branch: `git push -u origin HEAD`
3. Read implementation artifacts from `$ARTIFACTS_DIR/` for context:
   - `$ARTIFACTS_DIR/investigation.md` or `$ARTIFACTS_DIR/plan.md`
   - `$ARTIFACTS_DIR/implementation.md`
   - `$ARTIFACTS_DIR/validation.md`
4. Check if a PR already exists for this branch: `gh pr list --head $(git branch --show-current)`
   - If PR exists, skip creation and capture its number.
5. Look for the project's PR template at `.github/pull_request_template.md`, `.github/PULL_REQUEST_TEMPLATE.md`, or `docs/PULL_REQUEST_TEMPLATE.md`. Read whichever one exists.
6. Create a DRAFT PR: `gh pr create --draft --base $BASE_BRANCH`
   - **Title**: use the conventional-commits prefix matching the first commit (`feat:`, `fix:`, `chore:`, etc.), imperative mood, under 72 chars.
   - **Body**: if a PR template was found, fill in **every section** with details from the artifacts. Don't skip sections or leave placeholders. If no template, write a body with summary, changes, validation evidence, and `Fixes #...`.
   - **Required**: the body MUST contain `Fixes #N` (or `Closes #N` / `Resolves #N`) on its own line — CLAUDE.md §Commit and PR Conventions enforces this so the validator can extract the linked issue.
   - **New dependencies**: if the implementation added any dependencies (to `app/backend/pyproject.toml`; the iOS app takes none), include a "Dependencies" section per FACTORY_RULES.md §2 explaining what the dependency does, why existing dependencies don't work, and evidence of active maintenance.
7. Add the `factory:needs-review` label so the orchestrator picks this PR up for validation:
   ```bash
   gh pr edit --add-label "factory:needs-review"
   ```
8. Capture PR identifiers:
   ```bash
   PR_NUMBER=$(gh pr view --json number -q '.number')
   echo "$PR_NUMBER" > "$ARTIFACTS_DIR/.pr-number"
   PR_URL=$(gh pr view --json url -q '.url')
   echo "$PR_URL" > "$ARTIFACTS_DIR/.pr-url"
   ```
