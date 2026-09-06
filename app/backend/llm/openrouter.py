"""OpenRouter, through the OpenAI-compatible SDK. MISSION hard invariant 6: the only
inference provider. Chat completions stream text deltas; embeddings index the wiki; one
non-streaming completion serves the web fallback, which needs the answer AND the pages
OpenRouter returns with it (`url_citation` annotations, for search-backed models).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from backend.config import CHAT_MODEL, EMBEDDING_MODEL, OPENROUTER_API_KEY, OPENROUTER_BASE_URL

logger = logging.getLogger(__name__)


class OpenRouterClient:
    def __init__(
        self,
        api_key: str = OPENROUTER_API_KEY,
        base_url: str = OPENROUTER_BASE_URL,
        model: str = CHAT_MODEL,
        embedding_model: str = EMBEDDING_MODEL,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._embedding_model = embedding_model

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=cast(list[ChatCompletionMessageParam], messages),
            stream=True,
            max_tokens=400,
            temperature=0.2,
        )
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def complete(
        self, messages: list[dict[str, str]], model: str
    ) -> tuple[str, list[tuple[str, str]]]:
        """One whole reply from `model`, plus the (title, url) pages it cited, if any."""
        response = await self._client.chat.completions.create(
            model=model,
            messages=cast(list[ChatCompletionMessageParam], messages),
            max_tokens=400,
            temperature=0.2,
        )
        if not response.choices:
            return "", []
        message = response.choices[0].message
        pages: list[tuple[str, str]] = []
        raw = getattr(message, "annotations", None) or (message.model_extra or {}).get(
            "annotations"
        )
        for a in raw or []:
            cite = (
                a.get("url_citation") if isinstance(a, dict) else getattr(a, "url_citation", None)
            )
            if cite is None:
                continue
            url = cite.get("url") if isinstance(cite, dict) else getattr(cite, "url", None)
            title = cite.get("title") if isinstance(cite, dict) else getattr(cite, "title", None)
            if url:
                pages.append((title or url, url))
        return message.content or "", pages

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(model=self._embedding_model, input=texts)
        return [item.embedding for item in response.data]
