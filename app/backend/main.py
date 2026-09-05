"""FastAPI application entry point: lifespan wiring and route registration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as get_version

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.agent.pipeline import Agent
from backend.config import (
    BRAVE_SEARCH_API_KEY,
    CORS_ORIGINS,
    WEB_SEARCH_BASE_URL,
    WIKI_POLL_SECONDS,
    WIKI_RESOURCES_DIR,
)
from backend.languages import SUPPORTED_LANGUAGES, supported_languages_payload
from backend.llm.openrouter import OpenRouterClient
from backend.routes import sessions
from backend.search.web import BraveSearch
from backend.wiki.index import Embedder, WikiIndex, folder_signature

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def reindex_if_changed(app: FastAPI, embedder: Embedder) -> bool:
    """Rebuild the wiki index when the folder changed; swap it in atomically.

    The wiki is a folder, not part of the code: a document dropped into it is knowledge
    within one poll interval, with no restart and no deploy. A rebuild that fails keeps
    the previous index and logs why - an agent with a stale wiki is a smaller failure
    than an agent with none, and the health endpoint shows when the index was built.
    """
    current: WikiIndex = app.state.wiki
    root = app.state.wiki_root
    if folder_signature(root) == current.signature:
        return False
    try:
        fresh = await WikiIndex.build(root, embedder, previous=current)
    except Exception:  # the outermost boundary: log, keep serving
        logger.exception("wiki re-index failed; keeping the previous index")
        return False
    app.state.wiki = fresh
    app.state.agent.wiki = fresh
    logger.info("Wiki re-indexed: %d documents, %d chunks", fresh.document_count, fresh.chunk_count)
    return True


async def _watch_wiki(app: FastAPI, embedder: Embedder, every: int) -> None:
    while True:
        await asyncio.sleep(every)
        try:
            await reindex_if_changed(app, embedder)
        except Exception:  # the watcher must outlive any single failure
            logger.exception("wiki watch iteration failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: index the wiki (which needs the embedding provider), wire the agent.

    An index that cannot be built is a startup FAILURE, not a degraded mode: an agent
    with no wiki would answer everything from the web and pass every health check.
    """
    llm = OpenRouterClient()
    logger.info("Indexing the wiki at %s", WIKI_RESOURCES_DIR)
    wiki = await WikiIndex.build(WIKI_RESOURCES_DIR, llm)
    logger.info("Wiki indexed: %d documents, %d chunks", wiki.document_count, wiki.chunk_count)
    search = BraveSearch(api_key=BRAVE_SEARCH_API_KEY, base_url=WEB_SEARCH_BASE_URL)
    app.state.wiki = wiki
    app.state.wiki_root = WIKI_RESOURCES_DIR
    app.state.search = search
    app.state.agent = Agent(wiki=wiki, llm=llm, search=search)
    watcher: asyncio.Task[None] | None = None
    if WIKI_POLL_SECONDS > 0:
        watcher = asyncio.create_task(_watch_wiki(app, llm, WIKI_POLL_SECONDS))
        logger.info("Watching %s every %ds for changes", WIKI_RESOURCES_DIR, WIKI_POLL_SECONDS)
    logger.info("Startup complete.")
    yield
    if watcher is not None:
        watcher.cancel()
    logger.info("Shutting down.")


app = FastAPI(title="Virtual Agent API", lifespan=lifespan)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(sessions.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, object]:
    wiki = getattr(app.state, "wiki", None)
    search = getattr(app.state, "search", None)
    return {
        "status": "ok",
        "wiki_documents": wiki.document_count if wiki else 0,
        "wiki_chunks": wiki.chunk_count if wiki else 0,
        "wiki_indexed_at": (wiki.built_at.isoformat().replace("+00:00", "Z") if wiki else None),
        "languages": sorted(SUPPORTED_LANGUAGES),
        "web_search": "configured" if search and search.available else "unconfigured",
    }


@app.get("/api/version")
async def version() -> dict[str, str]:
    try:
        return {"version": get_version("virtualagent-backend")}
    except PackageNotFoundError:
        raise HTTPException(status_code=503, detail="Package metadata unavailable") from None


@app.get("/api/languages")
async def languages() -> list[dict[str, str]]:
    return supported_languages_payload()
