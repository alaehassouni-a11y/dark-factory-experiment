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
WIKI_MIN_SIMILARITY: float = 0.45

# --- web fallback -------------------------------------------------------------------------
BRAVE_SEARCH_API_KEY: str = os.environ.get("BRAVE_SEARCH_API_KEY", "")
WEB_SEARCH_BASE_URL: str = os.environ.get(
    "WEB_SEARCH_BASE_URL", "https://api.search.brave.com/res/v1"
)
WEB_SEARCH_RESULTS: int = 5

# --- sessions -----------------------------------------------------------------------------
SESSION_TTL_HOURS: int = 24
HISTORY_TURNS: int = 10

# --- serving ------------------------------------------------------------------------------
CORS_ORIGINS: list[str] = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()
]
