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
