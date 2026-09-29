# CLAUDE.md

Instructions for AI coding agents working in this repository. Read this before making any code changes.

This file covers **how the code is written**. For *what* to build, see `MISSION.md`. For *how the factory operates*, see `FACTORY_RULES.md`. When this file and those conflict, MISSION.md wins on scope, FACTORY_RULES.md wins on process, and CLAUDE.md wins on code style.

---

## Project Overview

This repository is a **dark factory**: an unattended AI software factory (Archon workflows under `.archon/`, rules in `FACTORY_RULES.md`, the account of what the gate covers in `FACTORY.md`).

**No product is currently specified.** The Virtual Agent, the product built here from 2026-09-03 to 2026-09-27, moved to `alaehassouni-a11y/firstRepo` (https://github.com/alaehassouni-a11y/firstRepo/pull/54) together with its code, harness, PRD, API contract and conventions. There is no application code in this tree, so there are no code conventions, build commands, environment variables, deployment steps or footguns to record yet.

A new product starts by writing its requirements in `requirements.md`, then a PRD under `docs/`, then `MISSION.md` reconciled with it. The product's own code conventions, layout, test and lint commands, contract invariants and protected files are then added to this file in the same human-authored change, and `.factory/protected-paths.txt` is extended to match.

---

## Repo Layout

```
dark-factory-experiment/
├── requirements.md          # The requirement (currently a placeholder: no product)
├── MISSION.md               # The product compressed to what the factory must obey
├── FACTORY_RULES.md         # How the factory operates - every workflow reads this
├── CLAUDE.md                # This file
├── FACTORY.md               # The honest account of what the gate covers and the incident log
├── README.md                # Human-facing overview
├── docs/archive/            # Past work kept for the record (the DynaChat benchmark)
├── .factory/
│   └── protected-paths.txt  # Paths the factory may not touch
├── scripts/factory-stop.sh  # The stop button
└── .archon/                 # Factory workflows and command files (config.yaml is gitignored: it holds a token)
```

A product adds its own code folders, `harness/` (with a `harness/ci.py` entrypoint, which `.github/workflows/gate.yml` runs when present), and `.factory/locks/` for its ratchet.

---

## Commit and PR Conventions

- **Commit messages:** conventional commits - `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`, `test:`. Subject under 72 characters. Body explains *why*.
- **PR title:** same prefix as the first commit, under 72 characters.
- **PR body:** must include `Fixes #N` (or `Closes #N` / `Resolves #N`) on its own line. Missing this fails validation.
- **New dependencies:** PR body must include a "Dependencies" section: what it does, why existing dependencies do not work, evidence of maintenance. See FACTORY_RULES.md §2.
- **One issue per PR.** File a new issue for anything else you notice.

---

## Dos and Don'ts

**Do:**
- Read MISSION.md and FACTORY_RULES.md before any non-trivial task
- Run the product's gate (`python harness/ci.py`, when the product supplies one) before declaring a PR done
- Add tests for every bug fix and every feature

**Don't:**
- Modify `MISSION.md`, `FACTORY_RULES.md`, or `CLAUDE.md` - see FACTORY_RULES.md §5
- Modify `.github/`, `deploy/`, any `.env*`, `harness/`, or `.factory/`
- "Improve" code that was not part of the issue - scope discipline is enforced by the validator

---

## Protected paths (factory auto-rejects PRs touching these)

The authoritative list is `.factory/protected-paths.txt`. Any PR touching these must be human-authored:

- `deploy/**` - a product's deployment stack
- `harness/**` and `.factory/**` - the gate, the holdout, the mutation set, the ratchet, the decisions log. A builder that can edit its own judge can pass it
- `scripts/factory-stop.sh` - the stop button
- `MISSION.md`, `FACTORY_RULES.md`, `CLAUDE.md`, `.github/**`, `.env*`, `.archon/config.yaml`
- Any invariant-bearing product file the product lists in `.factory/protected-paths.txt`
