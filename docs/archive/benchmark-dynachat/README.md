# Mixed-provider benchmark — DynaChat era (archived)

Thirteen files that measured how different model providers compared at resolving GitHub
issues, run against **DynaChat**: the chat, retrieval and video product this repository
held until 2026-09-03, when the same four-sentence requirement was rebuilt as the Virtual
Agent. Used from 2026-05-20, last run 2026-08-11; archived here on 2026-09-19.

**Nothing here is runnable against the current product.** Every number, source path,
candidate issue and repository owner in these files belongs to DynaChat. The files the
candidates name (`app/backend/rag/`, `citations.py`, `db/repository.py`, `alembic/`, a
`user_messages` table, a 25-message cap) were deleted with it; the playbook hardcodes
another contributor's machine paths and points `gh` at the upstream repository this one
was forked from, so its scoreboard queries match nothing here.

Two hazards are why the files carry banners rather than being deleted. The cells run none
of this project's checks, so any pull request they open has been validated by nothing; and
the dispatch procedure marks issues in progress and never releases them, which is what
starved the factory from 2026-05 to 2026-08 (see `FACTORY.md`). Each cell's pull-request
body now uses a plain reference, not a closing keyword.

Kept only as a record of the experiment. The live workflows are in `.archon/workflows/`.
