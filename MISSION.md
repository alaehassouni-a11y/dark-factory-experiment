# Mission

**No product is currently specified.**

The Virtual Agent - the spoken assistant this file used to compress from
`docs/virtualagent.prd.md` - moved to `alaehassouni-a11y/firstRepo` on 2026-09-27, together
with its PRD, its harness, and its wiki resources
(https://github.com/alaehassouni-a11y/firstRepo/pull/54). Nothing in this repository builds
it, or anything else, right now.

This file is the PRD compressed to the part the factory has to obey - once a product exists.
A new product starts with `requirements.md`, then a PRD under `docs/`, then this file
reconciled with it in the same commit, following the shape the Virtual Agent's mission had
(visible in firstRepo's history if a reference is useful): what the product is, who it is
for, in-scope capabilities, out-of-scope directions the factory must reject, hard invariants
the factory may never modify, allowed evolutions, the quality gates a PR must clear, and what
the product is explicitly not trying to be.

## What holds regardless of product

1. **The factory cannot modify governance files.** `MISSION.md`, `FACTORY_RULES.md`, and
   `CLAUDE.md` are the constitution. Any PR that touches them is an automatic reject. This is
   the one invariant that is not product-specific, and it stays true with no product in the
   tree.
