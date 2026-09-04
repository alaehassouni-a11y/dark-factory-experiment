"""FastAPI application entry point: lifespan wiring and route registration."""

from __future__ import annotations

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
    WIKI_RESOURCES_DIR,
)
from backend.languages import SUPPORTED_LANGUAGES, supported_languages_payload
from backend.llm.openrouter import OpenRouterClient
from backend.routes import sessions
from backend.search.web import BraveSearch
from backend.wiki.index import WikiIndex

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    app.state.search = search
    app.state.agent = Agent(wiki=wiki, llm=llm, search=search)
    logger.info("Startup complete.")
    yield
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
