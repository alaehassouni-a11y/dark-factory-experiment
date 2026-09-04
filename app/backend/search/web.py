"""The web fallback: Brave Search's web endpoint, in the client's language.

Unavailable (no key) is a state, not an error: the pipeline turns it into a spoken
"I could not find an answer" with source `none`. A transport failure or a non-200 is
logged and reported as no results, for the same reason: the agent must never crash
mid-conversation because a third party had a bad minute.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from backend.config import WEB_SEARCH_RESULTS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str


class BraveSearch:
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
