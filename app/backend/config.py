"""Every environment variable is read exactly once, here, and exposed as a constant.

Routes and services import the constant; nothing else reads `os.environ`.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent.parent

# Optional local env file, outside git (see .gitignore). Real secrets never live in the repo.
load_dotenv(BACKEND_DIR.parent / ".env")

# --- inference (MISSION hard invariant 6: OpenRouter is the only provider) ---------------
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
if not OPENROUTER_API_KEY:
    raise RuntimeError(
        "OPENROUTER_API_KEY is not set. The service refuses to start without its inference "
        "provider rather than starting into a crash on the first turn."
    )
OPENROUTER_BASE_URL: str = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
CHAT_MODEL: str = os.environ.get("CHAT_MODEL", "anthropic/claude-sonnet-4.6")
EMBEDDING_MODEL: str = "openai/text-embedding-3-small"

# --- the wiki -----------------------------------------------------------------------------
# The requirement names the folder: "a wiki, created from the virtualagent/resources folder".
# `or`, not a default argument: an exported-but-empty variable is "unset", not "the cwd".
WIKI_RESOURCES_DIR: Path = Path(
    os.environ.get("WIKI_RESOURCES_DIR") or str(REPO_ROOT / "virtualagent" / "resources")
)
WIKI_TOP_K: int = 5
# How often the service looks at the wiki folder for added, changed or removed files, in
# seconds. A change rebuilds the index in the background and swaps it in; no restart, no
# deploy. 0 disables the watch (the folder is then read once, at startup).
WIKI_POLL_SECONDS: int = int(os.environ.get("WIKI_POLL_SECONDS", "10"))
# The confidence decision between wiki and web (MISSION hard invariant 2 is the ORDER;
# these are the tolerances the order is judged with, and they are judgement values).
# Coverage is measured over the question's content STEMS (wiki/index.py): function words,
# question words and one- or two-letter tokens do not count, and inflections meet. 0.4
# rather than 0.5 because the bar is not the last line of defence: excerpts that pass it
# without answering are declined by the model and the turn falls through to the web.
WIKI_MIN_TERM_COVERAGE: float = 0.4
# A coverage pass also needs at least this many matching content words (or all of them,
# when the question has fewer): one shared word, "Japan" in a question about capitals
# against a wiki that mentions akadama from Japan, is not coverage.
WIKI_MIN_TERM_MATCHES: int = 2
# Measured 2026-09-06 with text-embedding-3-small against the nine-document wiki:
# covered questions score 0.53-0.75 in the document's own or a sibling Latin-script
# language and 0.36-0.38 from Arabic; every unrelated question scored 0.22 or less.
# 0.30 sits between with margin on both sides, and the model's decline is the net.
WIKI_MIN_SIMILARITY: float = 0.30
# Passages from one document that may occupy the excerpts. Five passages of the same
# document, all in the client's language, once crowded out the one passage of another
# document that held the answer.
WIKI_MAX_CHUNKS_PER_DOCUMENT: int = 2

# --- web fallback -------------------------------------------------------------------------
# Two ways to reach the web, both ending in named pages the agent composes from:
#   perplexity  Perplexity Sonar through OpenRouter (the one provider, the one key). It
#               searches, answers, and returns the pages it used. The default.
#   brave       Brave Search: links and snippets, needs its own key. Used when one is set,
#               and by the harness, whose stubs are Brave-shaped.
#   none        no web fallback; the agent says it does not know when the wiki has nothing.
BRAVE_SEARCH_API_KEY: str = os.environ.get("BRAVE_SEARCH_API_KEY", "")
WEB_SEARCH_BASE_URL: str = os.environ.get(
    "WEB_SEARCH_BASE_URL", "https://api.search.brave.com/res/v1"
)
WEB_SEARCH_RESULTS: int = 5
WEB_SEARCH_MODEL: str = "perplexity/sonar"
WEB_SEARCH_PROVIDER: str = os.environ.get("WEB_SEARCH_PROVIDER") or (
    "brave" if BRAVE_SEARCH_API_KEY else "perplexity"
)
if WEB_SEARCH_PROVIDER not in {"perplexity", "brave", "none"}:
    raise RuntimeError(
        f"WEB_SEARCH_PROVIDER={WEB_SEARCH_PROVIDER!r}: expected perplexity, brave or none"
    )

# --- sessions -----------------------------------------------------------------------------
SESSION_TTL_HOURS: int = 24
HISTORY_TURNS: int = 10

# --- serving ------------------------------------------------------------------------------
CORS_ORIGINS: list[str] = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()
]
