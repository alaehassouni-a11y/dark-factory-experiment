"""The web fallback, in the client's language. Two implementations of one seam:

    PerplexitySearch   Perplexity Sonar through OpenRouter: it searches, answers, and names
                       the pages it used. Those pages are the sources; its answer is the
                       excerpt the agent composes the spoken reply from. The default.
    BraveSearch        Brave Search's web endpoint: links and snippets. Needs its own key.

Unavailable (no key, no pages) is a state, not an error: the pipeline turns it into a
spoken "I could not find an answer" with source `none`. A transport failure, a non-200, a
provider exception mid-turn is logged and reported as no results, for the same reason:
the agent must never crash mid-conversation because a third party had a bad minute.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

from backend.config import WEB_SEARCH_MODEL, WEB_SEARCH_RESULTS
from backend.languages import LANGUAGE_NAMES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str


class WebAnswerer(Protocol):
    async def complete(
        self, messages: list[dict[str, str]], model: str
    ) -> tuple[str, list[tuple[str, str]]]: ...


_MARKUP = re.compile(r"\*\*|__|\[\d+(?:,\s*\d+)*\]")  # bold marks and [1][2,3] reference marks

_PROMPT = """\
You are the research step of a spoken assistant. Answer the question factually from the \
web in {language_name}, in at most four short sentences of plain prose: no lists, no \
markdown, no URLs in the text. If you cannot find the answer, say so in one sentence."""


class PerplexitySearch:
    """Sonar through OpenRouter. `search` returns one result per page it cited; the first
    carries Sonar's answer as its snippet so the composing model has the substance, the
    others carry the page alone. No cited page means no web source, and therefore no
    result: an answer nobody can point at is not one this product gives."""

    name = "perplexity"

    def __init__(self, llm: WebAnswerer, model: str = WEB_SEARCH_MODEL) -> None:
        self._llm = llm
        self._model = model

    @property
    def available(self) -> bool:
        return True

    async def search(self, query: str, language: str) -> list[WebResult]:
        messages = [
            {"role": "system", "content": _PROMPT.format(language_name=LANGUAGE_NAMES[language])},
            {"role": "user", "content": query},
        ]
        try:
            text, pages = await self._llm.complete(messages, self._model)
        except Exception as e:  # the outermost boundary for a third party
            logger.error("web research failed: %s", e)
            return []
        answer = " ".join(_MARKUP.sub("", text).split())
        if not pages or not answer:
            logger.info("web research returned no cited pages; no web source")
            return []
        results: list[WebResult] = []
        seen: set[str] = set()
        for title, url in pages:
            if url in seen:
                continue
            seen.add(url)
            results.append(
                WebResult(
                    title=title or urlparse(url).netloc or url,
                    url=url,
                    snippet=answer if not results else "",
                )
            )
            if len(results) >= WEB_SEARCH_RESULTS:
                break
        return results


class BraveSearch:
    name = "brave"

    def __init__(self, api_key: str, base_url: str, timeout: float = 8.0) -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._key)

    async def search(self, query: str, language: str) -> list[WebResult]:
        if not self.available:
            return []
        params = {"q": query, "count": str(WEB_SEARCH_RESULTS), "search_lang": language}
        headers = {"Accept": "application/json", "X-Subscription-Token": self._key}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(f"{self._base}/web/search", params=params, headers=headers)
        except httpx.HTTPError as e:
            logger.error("web search transport failure: %s", e)
            return []
        if r.status_code != 200:
            logger.error("web search returned %s: %s", r.status_code, r.text[:200])
            return []
        try:
            items = r.json().get("web", {}).get("results", [])
        except ValueError:
            logger.error("web search returned a non-JSON body")
            return []
        results = []
        for item in items[:WEB_SEARCH_RESULTS]:
            url = item.get("url") or ""
            title = item.get("title") or url
            snippet = item.get("description") or ""
            if url:
                results.append(WebResult(title=title, url=url, snippet=snippet))
        return results
