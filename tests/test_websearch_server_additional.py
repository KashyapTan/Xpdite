from types import SimpleNamespace

import pytest

from mcp_servers.servers.websearch import server as websearch_server
from mcp_servers.servers.websearch.server import ScrapeResult, TierAttempt


class _FakeRedirectResponse:
    def __init__(self, url: str, status_code: int, location: str | None = None):
        self.request = SimpleNamespace(url=url)
        self.status_code = status_code
        self.headers = {} if location is None else {"location": location}


class _FakeRedirectClient:
    def __init__(self, responses: list[_FakeRedirectResponse]):
        self._responses = list(responses)

    async def get(self, _url: str, headers: dict[str, str] | None = None):
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def clear_validation_cache():
    websearch_server._url_validation_cache.clear()


def test_environment_feature_flags_and_bool_force_tier(monkeypatch):
    monkeypatch.setenv(websearch_server._EXTERNAL_RELAY_ENV, "YES")
    monkeypatch.setenv(websearch_server._UNSAFE_TIER3_ENV, "1")

    assert websearch_server._external_relays_enabled() is True
    assert websearch_server._unsafe_tier3_enabled() is True
    assert websearch_server._coerce_force_tier(True)[1] is not None


@pytest.mark.asyncio
async def test_resolve_safe_redirect_chain_follows_redirects(monkeypatch):
    validations: list[str] = []
    client = _FakeRedirectClient(
        [
            _FakeRedirectResponse(
                "https://example.com/start",
                302,
                location="/next",
            ),
            _FakeRedirectResponse("https://example.com/next", 200),
        ]
    )

    async def _validate(url: str):
        validations.append(url)
        return None

    async def _get_client():
        return client

    monkeypatch.setattr(websearch_server, "_get_httpx_noredirect_client", _get_client)
    monkeypatch.setattr(
        websearch_server, "_validate_read_website_url_async", _validate
    )

    resolved = await websearch_server._resolve_safe_redirect_chain(
        "https://example.com/start"
    )

    assert resolved == "https://example.com/next"
    assert validations[0] == "https://example.com/start"
    assert validations.count("https://example.com/next") >= 1


def test_helper_predicates_detect_js_domains_and_walls():
    assert websearch_server.is_medium("https://medium.com/story") is True
    assert websearch_server.needs_js("https://x.com/user/status/1") is True
    assert websearch_server.has_js_wall("Please enable JavaScript to continue.") is True
    assert (
        websearch_server.is_js_skeleton(
            "<html><div id='root'></div>" + (" " * 10000),
            "tiny",
        )
        is True
    )


def test_truncate_for_mcp_and_format_scrape_result(monkeypatch):
    monkeypatch.setattr(websearch_server, "_MAX_RETURN_CHARS", 25)

    truncated, was_truncated = websearch_server._truncate_for_mcp("x" * 30)
    assert truncated == "x" * 25
    assert was_truncated is True

    failure = websearch_server._format_scrape_result(
        ScrapeResult(
            url="https://example.com",
            mode="full",
            success=False,
            warnings=["All tiers failed"],
            suggestions=["Enable relays"],
            tier_attempts=[
                TierAttempt(tier="tier1_curl", success=False, error="Timeout")
            ],
        )
    )
    success = websearch_server._format_scrape_result(
        ScrapeResult(
            url="https://example.com",
            mode="precision",
            success=True,
            content="useful content that is definitely longer than the cap",
            content_length=52,
            winning_tier="tier1_curl",
            total_elapsed_seconds=1.2,
            warnings=["Sparse"],
            suggestions=["Retry"],
        )
    )

    assert "Tier Results:" in failure
    assert "Suggestions:" in failure
    assert "[TRUNCATED]" in success
    assert "WARNINGS:" in success
    assert "SUGGESTIONS:" in success


def test_search_web_pages_handles_empty_and_error_results(monkeypatch):
    class _EmptyDDGS:
        def text(self, **kwargs):
            return []

    class _BrokenDDGS:
        def text(self, **kwargs):
            raise RuntimeError("search failed")

    monkeypatch.setattr(websearch_server, "DDGS", _EmptyDDGS)
    empty = websearch_server.search_web_pages("python")
    assert empty == [{"error": "No results found", "query": "python"}]

    monkeypatch.setattr(websearch_server, "DDGS", _BrokenDDGS)
    broken = websearch_server.search_web_pages("python")
    assert broken == [{"error": "Search failed: search failed", "query": "python"}]


@pytest.mark.asyncio
async def test_run_tier_with_timeout_handles_none_and_exceptions():
    async def _none_result(_url: str, _mode: str):
        return None

    async def _explode(_url: str, _mode: str):
        raise RuntimeError("boom")

    none_attempt = await websearch_server._run_tier_with_timeout(
        _none_result,
        "https://example.com",
        "full",
        "tier1_curl",
        0.1,
    )
    error_attempt = await websearch_server._run_tier_with_timeout(
        _explode,
        "https://example.com",
        "full",
        "tier2_camoufox",
        0.1,
    )

    assert none_attempt.success is False
    assert none_attempt.error == "No content returned"
    assert error_attempt.success is False
    assert error_attempt.error == "boom"
