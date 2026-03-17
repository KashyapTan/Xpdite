import pytest

from mcp_servers.servers.websearch import server as websearch_server


@pytest.fixture
def bypass_url_validation(monkeypatch):
    monkeypatch.setattr(websearch_server, "_validate_read_website_url", lambda _url: None)


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
    assert "Invalid force_tier" in invalid_error

    _, invalid_string_error = websearch_server._coerce_force_tier("fast")
    assert "Invalid force_tier" in invalid_string_error


async def test_read_website_rejects_missing_scheme():
    result = await websearch_server.read_website("x.com/test")
    assert "URL must start with http:// or https://" in result


def test_validate_read_website_url_rejects_loopback_ip():
    result = websearch_server._validate_read_website_url("http://127.0.0.1:8000/private")
    assert "not allowed" in result


def test_validate_read_website_url_rejects_localhost_name():
    result = websearch_server._validate_read_website_url("https://localhost:3000")
    assert "not allowed" in result


def test_validate_read_website_url_rejects_cgnat_range():
    result = websearch_server._validate_read_website_url("https://100.64.0.1/path")
    assert "not allowed" in result


async def test_read_website_rejects_invalid_mode(bypass_url_validation):
    result = await websearch_server.read_website("https://example.com", mode="detailed")
    assert "ERROR: Invalid mode" in result


async def test_read_website_rejects_invalid_force_tier(bypass_url_validation):
    result = await websearch_server.read_website("https://example.com", force_tier="4")
    assert "ERROR: Invalid force_tier" in result


async def test_read_website_rejects_force_tier3_when_disabled(monkeypatch, bypass_url_validation):
    monkeypatch.delenv(websearch_server._UNSAFE_TIER3_ENV, raising=False)

    result = await websearch_server.read_website("https://example.com", force_tier=3)

    assert "force_tier=3 is disabled by default" in result


async def test_read_website_formats_success_metadata(monkeypatch, bypass_url_validation):
    async def _scrape_success(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        return "tier1_curl_cffi", "Example content " * 20

    monkeypatch.setattr(websearch_server, "scrape", _scrape_success)

    result = await websearch_server.read_website("https://example.com", mode="precision")

    assert "SOURCE: https://example.com" in result
    assert "METHOD: tier1_curl_cffi" in result
    assert "MODE: precision" in result
    assert "CHARS: original=" in result


async def test_read_website_warns_on_minimal_content(monkeypatch, bypass_url_validation):
    async def _scrape_tiny(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        return "tier1_curl_cffi", "tiny"

    monkeypatch.setattr(websearch_server, "scrape", _scrape_tiny)

    result = await websearch_server.read_website("https://example.com")

    assert result.startswith("WARNING:")


async def test_read_website_errors_when_all_tiers_fail(monkeypatch, bypass_url_validation):
    async def _scrape_none(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        return None

    monkeypatch.setattr(websearch_server, "scrape", _scrape_none)

    result = await websearch_server.read_website("https://example.com")

    assert result.startswith("ERROR: Failed to read website content")


async def test_scrape_twitter_uses_twikit_first(monkeypatch):
    calls = {"tier1": 0}

    async def _twitter_success(_url: str):
        return "tweet text"

    async def _tier1_should_not_run(_url: str, _mode: str):
        calls["tier1"] += 1
        return None

    monkeypatch.setattr(websearch_server, "handle_twitter", _twitter_success)
    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_should_not_run)

    label, content = await websearch_server.scrape("https://x.com/user/status/123", "precision")

    assert label == "twitter_twikit"
    assert content == "tweet text"
    assert calls["tier1"] == 0


async def test_scrape_twitter_falls_to_jina_when_twikit_fails(monkeypatch):
    async def _twitter_fail(_url: str):
        return None

    async def _tier1_5_success(_url: str):
        return "jina content"

    monkeypatch.setattr(websearch_server, "handle_twitter", _twitter_fail)
    monkeypatch.setattr(websearch_server, "tier1_5_jina", _tier1_5_success)

    label, content = await websearch_server.scrape(
        "https://x.com/user/status/123",
        "precision",
        allow_external_relays=True,
    )

    assert label == "tier1_5_jina"
    assert content == "jina content"


async def test_scrape_skips_tier1_for_js_domain(monkeypatch):
    calls = {"tier1": 0, "tier2": 0}

    async def _tier1_should_not_run(_url: str, _mode: str):
        calls["tier1"] += 1
        return None

    async def _tier2_success(_url: str, _mode: str):
        calls["tier2"] += 1
        return "tier2 content"

    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_should_not_run)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_success)

    label, content = await websearch_server.scrape(
        "https://x.com/user/status/123",
        "precision",
        skip_twitter=True,
    )

    assert calls["tier1"] == 0
    assert calls["tier2"] == 1
    assert label == "tier2_camoufox"
    assert content == "tier2 content"


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

    result = await websearch_server.scrape(
        "https://example.com",
        "precision",
        force_tier=1,
        allow_external_relays=True,
    )

    assert result is None
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
        return "tier2 content"

    async def _tier3_should_not_run(_url: str, _mode: str):
        calls["tier3"] += 1
        return "tier3 content"

    monkeypatch.setattr(websearch_server, "tier1_curl", _tier1_should_not_run)
    monkeypatch.setattr(websearch_server, "tier1_5_jina", _jina_should_not_run)
    monkeypatch.setattr(websearch_server, "tier2_camoufox", _tier2_success)
    monkeypatch.setattr(websearch_server, "tier3_nodriver", _tier3_should_not_run)

    label, content = await websearch_server.scrape(
        "https://example.com",
        "precision",
        force_tier=2,
        allow_external_relays=True,
    )

    assert label == "tier2_camoufox"
    assert content == "tier2 content"
    assert calls["tier1"] == 0
    assert calls["jina"] == 0
    assert calls["tier2"] == 1
    assert calls["tier3"] == 0


async def test_read_website_accepts_force_tier_string(monkeypatch, bypass_url_validation):
    async def _scrape_success(
        _url: str,
        _mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        assert force_tier == 2
        return "tier2_camoufox", "tier2 content " * 20

    monkeypatch.setattr(websearch_server, "scrape", _scrape_success)

    result = await websearch_server.read_website(
        "https://x.com/StockSavvyShay/status/2033677491135766994",
        mode="full",
        force_tier="2",
    )

    assert "METHOD: tier2_camoufox" in result
    assert "MODE: full" in result


async def test_read_website_relays_disabled_by_default(monkeypatch, bypass_url_validation):
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
        return "tier1_curl_cffi", "content " * 20

    monkeypatch.setattr(websearch_server, "scrape", _scrape_capture_relays)

    result = await websearch_server.read_website("https://example.com", mode="precision")
    assert "METHOD: tier1_curl_cffi" in result


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
        return "tier1_5_jina", "content " * 20

    monkeypatch.setattr(websearch_server, "scrape", _scrape_capture_relays)

    result = await websearch_server.read_website("https://example.com", mode="precision")
    assert "METHOD: tier1_5_jina" in result


async def test_read_website_mode_isolation_across_concurrent_calls(monkeypatch, bypass_url_validation):
    async def _scrape_echo_mode(
        _url: str,
        mode: str,
        force_tier=None,
        skip_twitter=False,
        allow_external_relays=False,
        allow_unsafe_tier3=False,
    ):
        await websearch_server.asyncio.sleep(0)
        return "tier1_curl_cffi", f"mode={mode} " * 20

    monkeypatch.setattr(websearch_server, "scrape", _scrape_echo_mode)

    precision_result, full_result = await websearch_server.asyncio.gather(
        websearch_server.read_website("https://example.com/a", mode="precision"),
        websearch_server.read_website("https://example.com/b", mode="full"),
    )

    assert "mode=precision" in precision_result
    assert "MODE: precision" in precision_result
    assert "mode=full" in full_result
    assert "MODE: full" in full_result
