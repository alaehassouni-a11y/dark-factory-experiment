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
WIKI_RESOURCES_DIR: Path = Path(
    os.environ.get("WIKI_RESOURCES_DIR", str(REPO_ROOT / "virtualagent" / "resources"))
)
WIKI_TOP_K: int = 5
# The confidence decision between wiki and web (MISSION hard invariant 2 is the ORDER;
# these are the tolerances the order is judged with, and they are judgement values).
WIKI_MIN_TERM_COVERAGE: float = 0.5
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
