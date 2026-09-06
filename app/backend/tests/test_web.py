from __future__ import annotations

import httpx
import respx

from backend.search.web import BraveSearch

BASE = "https://search.test/res/v1"


async def test_unconfigured_search_is_unavailable_and_returns_nothing() -> None:
    s = BraveSearch(api_key="", base_url=BASE)
    assert not s.available
    assert await s.search("anything", "en") == []


@respx.mock
async def test_results_are_parsed_in_the_client_language() -> None:
    route = respx.get(f"{BASE}/web/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Louvre",
                            "url": "https://example.org/louvre",
                            "description": "Leonardo painted it.",
                        },
                        {"title": "No url", "description": "dropped"},
                    ]
                }
            },
        )
    )
    s = BraveSearch(api_key="k", base_url=BASE)
    results = await s.search("Qui a peint la Joconde ?", "fr")
    assert [r.url for r in results] == ["https://example.org/louvre"]
    assert results[0].snippet == "Leonardo painted it."
    request = route.calls.last.request
    assert request.headers["X-Subscription-Token"] == "k"
    assert request.url.params["search_lang"] == "fr"


@respx.mock
async def test_rate_limited_or_broken_provider_yields_no_results() -> None:
    respx.get(f"{BASE}/web/search").mock(return_value=httpx.Response(429, text="slow down"))
    assert await BraveSearch(api_key="k", base_url=BASE).search("q", "en") == []
    respx.get(f"{BASE}/web/search").mock(side_effect=httpx.ConnectError("down"))
    assert await BraveSearch(api_key="k", base_url=BASE).search("q", "en") == []


class FakeAnswerer:
    """What OpenRouter hands back for a search-backed model: text plus the pages cited."""

    def __init__(self, text: str, pages: list[tuple[str, str]], fail: bool = False) -> None:
        self.text, self.pages, self.fail = text, pages, fail
        self.calls: list[tuple[list[dict[str, str]], str]] = []

    async def complete(
        self, messages: list[dict[str, str]], model: str
    ) -> tuple[str, list[tuple[str, str]]]:
        self.calls.append((messages, model))
        if self.fail:
            raise RuntimeError("provider had a bad minute")
        return self.text, self.pages


async def test_perplexity_turns_an_answer_and_its_pages_into_results() -> None:
    from backend.search.web import PerplexitySearch

    llm = FakeAnswerer(
        "La Joconde a été peinte par **Léonard de Vinci**[1][3]. Elle est au Louvre.[2]",
        [
            ("La Joconde - Wikipédia", "https://fr.wikipedia.org/wiki/La_Joconde"),
            ("Le Louvre", "https://www.louvre.fr/joconde"),
            ("La Joconde - Wikipédia", "https://fr.wikipedia.org/wiki/La_Joconde"),
        ],
    )
    search = PerplexitySearch(llm)
    assert search.available and search.name == "perplexity"
    results = await search.search("Qui a peint la Joconde ?", "fr")
    assert [r.url for r in results] == [
        "https://fr.wikipedia.org/wiki/La_Joconde",
        "https://www.louvre.fr/joconde",
    ], "one result per page, duplicates dropped"
    assert results[0].title == "La Joconde - Wikipédia"
    assert results[0].snippet == "La Joconde a été peinte par Léonard de Vinci. Elle est au Louvre."
    assert results[1].snippet == ""
    messages, model = llm.calls[0]
    assert model == "perplexity/sonar"
    assert (
        "in French" in messages[0]["content"]
        and messages[1]["content"] == "Qui a peint la Joconde ?"
    )


async def test_perplexity_without_cited_pages_is_no_web_source() -> None:
    from backend.search.web import PerplexitySearch

    assert await PerplexitySearch(FakeAnswerer("Some answer.", [])).search("q", "en") == []
    assert await PerplexitySearch(FakeAnswerer("", [("T", "https://x")])).search("q", "en") == []


async def test_perplexity_provider_failure_is_no_results_not_a_crash() -> None:
    from backend.search.web import PerplexitySearch

    assert (
        await PerplexitySearch(FakeAnswerer("x", [("T", "https://x")], fail=True)).search("q", "de")
        == []
    )


async def test_a_page_without_a_title_is_named_by_its_host() -> None:
    from backend.search.web import PerplexitySearch

    results = await PerplexitySearch(
        FakeAnswerer("Answer.", [("", "https://example.org/a/b")])
    ).search("q", "en")
    assert results[0].title == "example.org"
