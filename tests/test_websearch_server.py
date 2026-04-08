import pytest

from mcp_servers.servers.websearch import server as websearch_server
from mcp_servers.servers.websearch.server import ScrapeResult, TierAttempt


@pytest.fixture
def bypass_url_validation(monkeypatch):
    monkeypatch.setattr(
        websearch_server, "_validate_read_website_url", lambda _url: None
    )


def test_normalize_mode_accepts_supported_values():
    assert websearch_server._normalize_mode("precision") == "precision"
    assert websearch_server._normalize_mode(" FULL ") == "full"


def test_normalize_mode_rejects_unsupported_values():
    assert websearch_server._normalize_mode("detailed") is None


def test_coerce_force_tier_accepts_int_and_string():
    int_value, int_error = websearch_server._coerce_force_tier(2)
    assert int_value == 2
    assert int_error is None

    string_value, string_error = websearch_server._coerce_force_tier("2")
    assert string_value == 2
    assert string_error is None


def test_coerce_force_tier_rejects_invalid_values():
    _, invalid_error = websearch_server._coerce_force_tier(4)
    assert invalid_error is not None
    assert "Invalid force_tier" in invalid_error

    _, invalid_string_error = websearch_server._coerce_force_tier("fast")
    assert invalid_string_error is not None
    assert "Invalid force_tier" in invalid_string_error


async def test_read_website_rejects_missing_scheme():
    result = await websearch_server.read_website("x.com/test")
    assert "URL must start with http:// or https://" in result


def test_validate_read_website_url_rejects_loopback_ip():
    result = websearch_server._validate_read_website_url(
        "http://127.0.0.1:8000/private"
    )
    assert result is not None
    assert "not allowed" in result


def test_validate_read_website_url_rejects_localhost_name():
    result = websearch_server._validate_read_website_url("https://localhost:3000")
    assert result is not None
    assert "not allowed" in result


def test_validate_read_website_url_rejects_cgnat_range():
    result = websearch_server._validate_read_website_url("https://100.64.0.1/path")
    assert result is not None
    assert "not allowed" in result


async def test_read_website_rejects_invalid_mode(bypass_url_validation):
    result = await websearch_server.read_website("https://example.com", mode="detailed")
    assert "ERROR: Invalid mode" in result


async def test_read_website_rejects_invalid_force_tier(bypass_url_validation):
    result = await websearch_server.read_website("https://example.com", force_tier="4")
    assert "ERROR: Invalid force_tier" in result


async def test_read_website_rejects_force_tier3_when_disabled(
    monkeypatch, bypass_url_validation
):
    monkeypatch.delenv(websearch_server._UNSAFE_TIER3_ENV, raising=False)

    result = await websearch_server.read_website("https://example.com", force_tier=3)

    assert "force_tier=3 is disabled by default" in result


async def test_read_website_formats_success_metadata(
    monkeypatch, bypass_url_validation
):
    async def _scrape_success(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        return ScrapeResult(
            url=_url,
            mode=_mode,
            success=True,
            content="Example content " * 20,
            content_length=len("Example content " * 20),
            winning_tier="tier1_curl",
            total_elapsed_seconds=1.5,
        )

    monkeypatch.setattr(websearch_server, "scrape_concurrent", _scrape_success)

    result = await websearch_server.read_website(
        "https://example.com", mode="precision"
    )

    assert "SOURCE: https://example.com" in result
    assert "METHOD: tier1_curl" in result
    assert "MODE: precision" in result
    assert "CHARS: original=" in result


async def test_read_website_warns_on_sparse_content(monkeypatch, bypass_url_validation):
    async def _scrape_sparse(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        return ScrapeResult(
            url=_url,
            mode=_mode,
            success=True,
            content="tiny content",
            content_length=12,
            winning_tier="tier1_curl",
            total_elapsed_seconds=0.5,
            sparse_content=True,
            warnings=["Sparse content extracted (12 chars < 300 threshold)"],
        )

    monkeypatch.setattr(websearch_server, "scrape_concurrent", _scrape_sparse)

    result = await websearch_server.read_website("https://example.com")

    assert "STATUS: SPARSE_CONTENT" in result
    assert "WARNINGS:" in result
    assert "Sparse content" in result


async def test_read_website_errors_when_all_tiers_fail(
    monkeypatch, bypass_url_validation
):
    async def _scrape_fail(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        return ScrapeResult(
            url=_url,
            mode=_mode,
            success=False,
            warnings=["All tiers failed: tier1_curl, tier2_camoufox"],
            suggestions=["Enable external relays: WEBSEARCH_ENABLE_EXTERNAL_RELAYS=1"],
            tier_attempts=[
                TierAttempt(tier="tier1_curl", success=False, error="Timeout"),
                TierAttempt(tier="tier2_camoufox", success=False, error="No content"),
            ],
        )

    monkeypatch.setattr(websearch_server, "scrape_concurrent", _scrape_fail)

    result = await websearch_server.read_website("https://example.com")

    assert result.startswith("ERROR: Failed to fetch")
    assert "Suggestions:" in result


async def test_read_website_detects_access_restriction(
    monkeypatch, bypass_url_validation
):
    async def _scrape_restricted(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        return ScrapeResult(
            url=_url,
            mode=_mode,
            success=True,
            content="Please log in to continue. Subscribe to access this content.",
            content_length=60,
            winning_tier="tier1_curl",
            total_elapsed_seconds=1.0,
            access_restriction_detected=True,
            sparse_content=True,
            warnings=["Access restriction detected: please log in"],
            suggestions=["Try external relays (WEBSEARCH_ENABLE_EXTERNAL_RELAYS=1)"],
        )

    monkeypatch.setattr(websearch_server, "scrape_concurrent", _scrape_restricted)

    result = await websearch_server.read_website("https://example.com")

    assert "STATUS:" in result
    assert "ACCESS_RESTRICTED" in result
    assert "SUGGESTIONS:" in result


async def test_scrape_twitter_uses_twikit_first(monkeypatch):
    calls = {"tier1": 0}

    async def _twitter_success(_url: str):
        # Must exceed _SPARSE_CHAR_THRESHOLD (500 chars) to be accepted
        return "tweet text with enough content to pass threshold " * 20

    async def _tier1_should_not_run(_url: str, _mode: str):
        calls["tier1"] += 1
        return None

    monkeypatch.setattr(websearch_server, "handle_twitter", _twitter_success)
    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_should_not_run)

    result = await websearch_server.scrape_concurrent(
        "https://x.com/user/status/123", "precision"
    )

    assert result.success
    assert result.winning_tier == "twitter_twikit"
    assert calls["tier1"] == 0


async def test_scrape_twitter_falls_to_concurrent_tiers_when_twikit_fails(monkeypatch):
    async def _twitter_fail(_url: str):
        return None

    async def _tier2_success(_url: str, _mode: str):
        return "tier2 content with enough chars " * 100

    monkeypatch.setattr(websearch_server, "handle_twitter", _twitter_fail)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_success)

    result = await websearch_server.scrape_concurrent(
        "https://x.com/user/status/123",
        "precision",
    )

    # Since Twitter failed and x.com is a JS domain, tier2 should be used
    assert result.success
    assert result.winning_tier == "tier2_camoufox"


async def test_scrape_concurrent_skips_tier1_for_js_domain(monkeypatch):
    calls = {"tier1": 0, "tier2": 0}

    async def _twitter_fail(_url: str):
        return None

    async def _tier1_should_not_run(_url: str, _mode: str):
        calls["tier1"] += 1
        return None

    async def _tier2_success(_url: str, _mode: str):
        calls["tier2"] += 1
        return "tier2 content with enough chars " * 100

    monkeypatch.setattr(websearch_server, "handle_twitter", _twitter_fail)
    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_should_not_run)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_success)

    result = await websearch_server.scrape_concurrent(
        "https://x.com/user/status/123",
        "precision",
    )

    assert calls["tier1"] == 0  # Tier 1 should be skipped for JS domain
    assert calls["tier2"] == 1
    assert result.success
    assert result.winning_tier == "tier2_camoufox"


async def test_scrape_force_tier1_does_not_escalate(monkeypatch):
    calls = {"jina": 0, "tier2": 0, "tier3": 0}

    async def _tier1_fail(_url: str, _mode: str):
        return None

    async def _jina_should_not_run(_url: str):
        calls["jina"] += 1
        return "jina content"

    async def _tier2_should_not_run(_url: str, _mode: str):
        calls["tier2"] += 1
        return "tier2 content"

    async def _tier3_should_not_run(_url: str, _mode: str):
        calls["tier3"] += 1
        return "tier3 content"

    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_fail)
    monkeypatch.setattr(websearch_server, "tier1_5_jina", _jina_should_not_run)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_should_not_run)
    monkeypatch.setattr(websearch_server, "tier3_nodriver", _tier3_should_not_run)

    result = await websearch_server.scrape_concurrent(
        "https://example.com",
        "precision",
        force_tier=1,
        allow_external_relays=True,
    )

    assert not result.success
    assert calls["jina"] == 0
    assert calls["tier2"] == 0
    assert calls["tier3"] == 0


async def test_scrape_force_tier2_skips_tier1_and_jina(monkeypatch):
    calls = {"tier1": 0, "jina": 0, "tier2": 0, "tier3": 0}

    async def _tier1_should_not_run(_url: str, _mode: str):
        calls["tier1"] += 1
        return None

    async def _jina_should_not_run(_url: str):
        calls["jina"] += 1
        return "jina content"

    async def _tier2_success(_url: str, _mode: str):
        calls["tier2"] += 1
        return "tier2 content with enough chars " * 100

    async def _tier3_should_not_run(_url: str, _mode: str):
        calls["tier3"] += 1
        return "tier3 content"

    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_should_not_run)
    monkeypatch.setattr(websearch_server, "tier1_5_jina", _jina_should_not_run)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_success)
    monkeypatch.setattr(websearch_server, "tier3_nodriver", _tier3_should_not_run)

    result = await websearch_server.scrape_concurrent(
        "https://example.com",
        "precision",
        force_tier=2,
        allow_external_relays=True,
    )

    assert result.success
    assert result.winning_tier == "tier2_camoufox"
    assert calls["tier1"] == 0
    assert calls["jina"] == 0
    assert calls["tier2"] == 1
    assert calls["tier3"] == 0


async def test_read_website_accepts_force_tier_string(
    monkeypatch, bypass_url_validation
):
    async def _scrape_success(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        assert force_tier == 2
        return ScrapeResult(
            url=_url,
            mode=_mode,
            success=True,
            content="tier2 content " * 100,
            content_length=len("tier2 content " * 100),
            winning_tier="tier2_camoufox",
            total_elapsed_seconds=2.0,
        )

    monkeypatch.setattr(websearch_server, "scrape_concurrent", _scrape_success)

    result = await websearch_server.read_website(
        "https://x.com/StockSavvyShay/status/2033677491135766994",
        mode="full",
        force_tier="2",
    )

    assert "METHOD: tier2_camoufox" in result
    assert "MODE: full" in result


async def test_read_website_relays_disabled_by_default(
    monkeypatch, bypass_url_validation
):
    monkeypatch.delenv(websearch_server._EXTERNAL_RELAY_ENV, raising=False)

    async def _scrape_capture_relays(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        assert allow_external_relays is False
        return ScrapeResult(
            url=_url,
            mode=_mode,
            success=True,
            content="content " * 100,
            content_length=len("content " * 100),
            winning_tier="tier1_curl",
            total_elapsed_seconds=1.0,
        )

    monkeypatch.setattr(websearch_server, "scrape_concurrent", _scrape_capture_relays)

    result = await websearch_server.read_website(
        "https://example.com", mode="precision"
    )
    assert "METHOD: tier1_curl" in result


async def test_read_website_relays_enabled_with_env(monkeypatch, bypass_url_validation):
    monkeypatch.setenv(websearch_server._EXTERNAL_RELAY_ENV, "1")

    async def _scrape_capture_relays(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        assert allow_external_relays is True
        return ScrapeResult(
            url=_url,
            mode=_mode,
            success=True,
            content="content " * 100,
            content_length=len("content " * 100),
            winning_tier="tier1_5_jina",
            total_elapsed_seconds=1.0,
        )

    monkeypatch.setattr(websearch_server, "scrape_concurrent", _scrape_capture_relays)

    result = await websearch_server.read_website(
        "https://example.com", mode="precision"
    )
    assert "METHOD: tier1_5_jina" in result


async def test_read_website_mode_isolation_across_concurrent_calls(
    monkeypatch, bypass_url_validation
):
    async def _scrape_echo_mode(
        _url: str,
        mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        await websearch_server.asyncio.sleep(0)
        content = f"mode={mode} " * 100
        return ScrapeResult(
            url=_url,
            mode=mode,
            success=True,
            content=content,
            content_length=len(content),
            winning_tier="tier1_curl",
            total_elapsed_seconds=1.0,
        )

    monkeypatch.setattr(websearch_server, "scrape_concurrent", _scrape_echo_mode)

    precision_result, full_result = await websearch_server.asyncio.gather(
        websearch_server.read_website("https://example.com/a", mode="precision"),
        websearch_server.read_website("https://example.com/b", mode="full"),
    )

    assert "mode=precision" in precision_result
    assert "MODE: precision" in precision_result
    assert "mode=full" in full_result
    assert "MODE: full" in full_result


# ── Access Restriction Detection Tests ──────────────────────────────


def test_detect_access_restriction_finds_login_signals():
    text = "Please log in to continue viewing this content."
    is_restricted, signals = websearch_server._detect_access_restriction(text)
    assert is_restricted
    assert any("log in" in s for s in signals)


def test_detect_access_restriction_finds_paywall_signals():
    text = "Subscribe now to read the full article. Premium content."
    is_restricted, signals = websearch_server._detect_access_restriction(text)
    assert is_restricted
    assert any("paywall" in s for s in signals)


def test_detect_access_restriction_returns_false_for_normal_content():
    text = "This is a normal article about programming in Python. " * 100
    is_restricted, signals = websearch_server._detect_access_restriction(text)
    assert not is_restricted
    assert signals == []


def test_detect_access_restriction_handles_empty_text():
    is_restricted, signals = websearch_server._detect_access_restriction("")
    assert not is_restricted
    assert signals == []


# ── Concurrent Execution Tests ──────────────────────────────────────


async def test_scrape_concurrent_returns_early_on_good_result(monkeypatch):
    """Test that concurrent scrape returns as soon as a good result is found."""
    calls = {"tier1": 0, "tier2": 0}

    async def _tier1_fast_success(_url: str, _mode: str):
        calls["tier1"] += 1
        return (
            "Good content " * 500,
            "<html>raw</html>",
        )  # Large enough to trigger early return

    async def _tier2_slow(_url: str, _mode: str):
        calls["tier2"] += 1
        await websearch_server.asyncio.sleep(5)  # Slow tier
        return "tier2 content"

    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_fast_success)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_slow)

    result = await websearch_server.scrape_concurrent(
        "https://example.com",
        "precision",
    )

    assert result.success
    assert result.winning_tier == "tier1_curl"
    # Tier 2 might have started (due to stagger) but should be cancelled
    assert calls["tier1"] == 1


async def test_scrape_concurrent_handles_tier1_failure_gracefully(monkeypatch):
    """Test that if tier1 fails quickly, browser tiers start immediately."""
    calls = {"tier1": 0, "tier2": 0}

    async def _tier1_fail(_url: str, _mode: str):
        calls["tier1"] += 1
        return None  # Fail fast

    async def _tier2_success(_url: str, _mode: str):
        calls["tier2"] += 1
        return "Good tier2 content " * 500

    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_fail)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_success)

    result = await websearch_server.scrape_concurrent(
        "https://example.com",
        "precision",
    )

    assert result.success
    assert result.winning_tier == "tier2_camoufox"
    assert calls["tier1"] == 1
    assert calls["tier2"] == 1


# ── Legacy Scrape Wrapper Tests ─────────────────────────────────────


async def test_legacy_scrape_returns_tuple_on_success(monkeypatch):
    """Test that the legacy scrape() wrapper returns (method, content) tuple."""

    async def _tier1_success(_url: str, _mode: str):
        return ("content " * 500, "<html>raw</html>")

    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_success)

    result = await websearch_server.scrape(
        "https://example.com",
        "precision",
    )

    assert result is not None
    method, content = result
    assert method == "tier1_curl"
    assert "content" in content


async def test_legacy_scrape_returns_none_on_failure(monkeypatch):
    """Test that the legacy scrape() wrapper returns None on failure."""

    async def _tier1_fail(_url: str, _mode: str):
        return None

    async def _tier2_fail(_url: str, _mode: str):
        return None

    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_fail)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_fail)

    result = await websearch_server.scrape(
        "https://example.com",
        "precision",
    )

    assert result is None


# ── Timeout Enforcement Tests ───────────────────────────────────────


async def test_scrape_twitter_respects_timeout(monkeypatch):
    """Test that Twitter handler respects timeout and doesn't hang."""
    import asyncio

    async def _slow_twitter(_url: str):
        # Simulate a slow Twitter API call
        await asyncio.sleep(30)  # Would hang without timeout
        return "tweet content"

    async def _tier2_success(_url: str, _mode: str):
        return "tier2 content " * 500

    monkeypatch.setattr(websearch_server, "handle_twitter", _slow_twitter)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_success)

    # Should complete within global timeout, not hang for 30s
    import time

    start = time.time()
    result = await websearch_server.scrape_concurrent(
        "https://x.com/user/status/123",
        "full",
    )
    elapsed = time.time() - start

    # Should complete in less than 15s (global timeout is 12s)
    assert elapsed < 15.0, f"Took {elapsed}s, expected < 15s"

    # Should have fallen back to tier2 after Twitter timeout
    assert result.success
    assert result.winning_tier == "tier2_camoufox"

    # Should have recorded Twitter timeout in attempts
    twitter_attempts = [a for a in result.tier_attempts if a.tier == "twitter_twikit"]
    assert len(twitter_attempts) == 1
    assert not twitter_attempts[0].success
    assert "Timeout" in (twitter_attempts[0].error or "")
