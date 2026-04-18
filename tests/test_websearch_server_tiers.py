import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mcp_servers.servers.websearch import server as websearch_server


class _Closable:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True

    async def aclose(self):
        self.closed = True


class _BrowserExit:
    def __init__(self):
        self.exited = False

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True


class _FakeCurlResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = "",
        headers: dict[str, str] | None = None,
        url: str = "https://example.com/final",
    ):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.url = url


class _FakeCurlSession:
    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs
        self.calls: list[tuple] = []
        self.responses: list[_FakeCurlResponse] = []

    async def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class _FakeHttpxClient:
    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs
        self.responses: list[SimpleNamespace] = []
        self.calls: list[tuple] = []

    async def get(self, url: str, headers: dict[str, str] | None = None):
        self.calls.append((url, headers))
        return self.responses.pop(0)

    async def aclose(self):
        self.closed = True


class _AsyncCamoufoxContext:
    def __init__(self, browser, **kwargs):
        self.browser = browser
        self.kwargs = kwargs

    async def __aenter__(self):
        return self.browser

    async def __aexit__(self, exc_type, exc, tb):
        self.browser.exited = True


class _FakePage:
    def __init__(self, html: str, url: str):
        self._html = html
        self.url = url
        self.routes: list[str] = []
        self.goto_calls: list[tuple] = []
        self.closed = False

    async def route(self, pattern: str, handler):
        self.routes.append(pattern)

    async def goto(self, url: str, **kwargs):
        self.goto_calls.append((url, kwargs))

    async def content(self) -> str:
        return self._html

    async def close(self):
        self.closed = True


class _FakePooledBrowser:
    def __init__(self, page: _FakePage):
        self.page = page

    async def new_page(self):
        return self.page


@pytest.fixture(autouse=True)
def reset_websearch_globals(monkeypatch):
    monkeypatch.setattr(websearch_server, "_curl_session_instance", None)
    monkeypatch.setattr(websearch_server, "_httpx_client_instance", None)
    monkeypatch.setattr(websearch_server, "_httpx_noredirect_client_instance", None)
    monkeypatch.setattr(websearch_server, "_camoufox_pool", None)


@pytest.mark.asyncio
async def test_session_factories_and_cleanup_close_resources():
    curl_session = _Closable()
    httpx_client = _Closable()
    httpx_noredirect_client = _Closable()
    pooled_browser = _BrowserExit()
    pool = asyncio.Queue()
    pool.put_nowait(pooled_browser)

    websearch_server._curl_session_instance = curl_session
    websearch_server._httpx_client_instance = httpx_client
    websearch_server._httpx_noredirect_client_instance = httpx_noredirect_client
    websearch_server._camoufox_pool = pool

    await websearch_server.cleanup_http_clients()

    assert curl_session.closed is True
    assert httpx_client.closed is True
    assert httpx_noredirect_client.closed is True
    assert pooled_browser.exited is True
    assert websearch_server._camoufox_pool is None


@pytest.mark.asyncio
async def test_session_helpers_create_cached_clients():
    curl_session = _FakeCurlSession(timeout=20)
    httpx_client = _FakeHttpxClient(timeout=20, follow_redirects=True)
    httpx_noredirect = _FakeHttpxClient(timeout=10, follow_redirects=False)
    camoufox_browser = SimpleNamespace(exited=False)

    curl_requests_module = SimpleNamespace(AsyncSession=lambda **kwargs: curl_session)
    httpx_module = SimpleNamespace(
        AsyncClient=lambda **kwargs: (
            httpx_client if kwargs.get("follow_redirects") else httpx_noredirect
        )
    )
    browserforge_module = SimpleNamespace(Screen=lambda **kwargs: kwargs)
    camoufox_module = SimpleNamespace(
        AsyncCamoufox=lambda **kwargs: _AsyncCamoufoxContext(camoufox_browser, **kwargs)
    )

    with patch.dict(
        sys.modules,
        {
            "curl_cffi": SimpleNamespace(requests=curl_requests_module),
            "curl_cffi.requests": curl_requests_module,
            "httpx": httpx_module,
            "browserforge": SimpleNamespace(fingerprints=browserforge_module),
            "browserforge.fingerprints": browserforge_module,
            "camoufox": SimpleNamespace(async_api=camoufox_module),
            "camoufox.async_api": camoufox_module,
        },
        clear=False,
    ):
        assert await websearch_server._get_curl_session() is curl_session
        assert await websearch_server._get_httpx_client() is httpx_client
        assert await websearch_server._get_httpx_noredirect_client() is httpx_noredirect
        assert await websearch_server._create_camoufox_browser() is camoufox_browser


@pytest.mark.asyncio
async def test_return_camoufox_browser_handles_pool_and_close_paths(monkeypatch):
    browser = _BrowserExit()
    pool = asyncio.Queue(maxsize=1)
    websearch_server._camoufox_pool = pool

    await websearch_server._return_camoufox_browser(browser)
    assert pool.get_nowait() is browser

    websearch_server._camoufox_pool = asyncio.Queue(maxsize=1)
    websearch_server._camoufox_pool.put_nowait(object())
    await websearch_server._return_camoufox_browser(browser)
    assert browser.exited is True


def test_validate_read_website_url_handles_missing_hosts_and_dns_failures(monkeypatch):
    assert "host is missing" in websearch_server._validate_read_website_url("https:///path")

    monkeypatch.setattr(
        websearch_server.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            websearch_server.socket.gaierror("boom")
        ),
    )
    assert "Could not resolve host" in websearch_server._validate_read_website_url(
        "https://example.invalid"
    )


def test_extract_returns_text_content():
    html = """
    <html>
      <head><script>alert('x')</script></head>
      <body><article><h1>Heading</h1><p>Hello world</p></article></body>
    </html>
    """

    result = websearch_server.extract(html, "full", "https://example.com")

    assert "Heading" in result
    assert "Hello world" in result


@pytest.mark.asyncio
async def test_tier1_curl_handles_redirects_and_extracts_text(monkeypatch):
    session = _FakeCurlSession()
    session.responses = [
        _FakeCurlResponse(status_code=302, headers={"location": "/next"}, url="https://example.com/start"),
        _FakeCurlResponse(status_code=200, text="<html>good</html>" * 60, url="https://example.com/next"),
    ]

    async def _get_session():
        return session

    async def _validate(url: str):
        return None

    monkeypatch.setattr(websearch_server, "_get_curl_session", _get_session)
    monkeypatch.setattr(websearch_server, "_validate_read_website_url_async", _validate)
    monkeypatch.setattr(websearch_server.random, "choice", lambda values: values[0])
    monkeypatch.setattr(websearch_server, "has_js_wall", lambda _html: False)
    monkeypatch.setattr(websearch_server, "extract", lambda _html, _mode, _url="": "content" * 50)

    result = await websearch_server.tier1_curl("https://example.com/start", "full")

    assert result == ("content" * 50, "<html>good</html>" * 60)
    assert session.calls[0][0] == "https://example.com/start"
    assert session.calls[1][0] == "https://example.com/next"


@pytest.mark.asyncio
async def test_tier1_5_jina_uses_api_key_when_present(monkeypatch):
    client = _FakeHttpxClient()
    client.responses = [
        SimpleNamespace(
            text="x" * 250,
            raise_for_status=lambda: None,
        )
    ]
    async def _get_client():
        return client

    monkeypatch.setattr(websearch_server, "_get_httpx_client", _get_client)
    monkeypatch.setenv("JINA_API_KEY", "secret")

    result = await websearch_server.tier1_5_jina("https://example.com/article")

    assert result == "x" * 250
    assert client.calls[0][0] == "https://r.jina.ai/https://example.com/article"
    assert client.calls[0][1]["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_tier2_camoufox_uses_pooled_browser(monkeypatch):
    page = _FakePage("<html>content</html>" * 80, "https://example.com/final")
    browser = _FakePooledBrowser(page)
    returned: list[object] = []

    async def _return_browser(browser_obj):
        returned.append(browser_obj)

    async def _resolve_safe_url(_url, fail_open=False):
        return "https://example.com/final"

    async def _get_browser():
        return browser

    async def _validate(_url: str):
        return None

    monkeypatch.setattr(
        websearch_server,
        "_resolve_safe_redirect_chain",
        _resolve_safe_url,
    )
    monkeypatch.setattr(websearch_server, "_get_camoufox_browser", _get_browser)
    monkeypatch.setattr(websearch_server, "_return_camoufox_browser", _return_browser)
    monkeypatch.setattr(websearch_server, "_validate_read_website_url_async", _validate)
    monkeypatch.setattr(websearch_server, "has_js_wall", lambda _html: False)
    monkeypatch.setattr(websearch_server, "extract", lambda _html, _mode, _url="": "text" * 40)

    browserforge_module = SimpleNamespace(Screen=lambda **kwargs: kwargs)
    camoufox_module = SimpleNamespace(AsyncCamoufox=lambda **kwargs: None)
    with patch.dict(
        sys.modules,
        {
            "browserforge": SimpleNamespace(fingerprints=browserforge_module),
            "browserforge.fingerprints": browserforge_module,
            "camoufox": SimpleNamespace(async_api=camoufox_module),
            "camoufox.async_api": camoufox_module,
        },
        clear=False,
    ):
        result = await websearch_server.tier2_camoufox(
            "https://example.com/final",
            "full",
        )

    assert result == "text" * 40
    assert returned == [browser]
    assert page.closed is True


@pytest.mark.asyncio
async def test_tier3_nodriver_returns_extracted_content(monkeypatch):
    page = SimpleNamespace(
        url="https://example.com/final",
        get_content=lambda: asyncio.sleep(0, result="<html>content</html>" * 60),
    )
    browser = SimpleNamespace(
        get=lambda _url: asyncio.sleep(0, result=page),
        stop=lambda: None,
    )

    async def _start(**kwargs):
        return browser

    async def _resolve_safe_url(_url):
        return "https://example.com/final"

    async def _validate(_url: str):
        return None

    monkeypatch.setattr(websearch_server, "_resolve_safe_redirect_chain", _resolve_safe_url)
    monkeypatch.setattr(websearch_server, "_validate_read_website_url_async", _validate)
    monkeypatch.setattr(websearch_server, "has_js_wall", lambda _html: False)
    monkeypatch.setattr(websearch_server, "extract", lambda _html, _mode, _url="": "output" * 30)

    with patch.dict(
        sys.modules,
        {"nodriver": SimpleNamespace(start=_start)},
        clear=False,
    ):
        result = await websearch_server.tier3_nodriver(
            "https://example.com/final",
            "full",
        )

    assert result == "output" * 30


@pytest.mark.asyncio
async def test_handle_twitter_formats_tweet_metadata():
    class _GuestClient:
        async def activate(self):
            return None

        async def get_tweet_by_id(self, tweet_id: str):
            assert tweet_id == "123"
            return SimpleNamespace(
                user=SimpleNamespace(screen_name="user", name="User"),
                created_at="2026-04-18",
                full_text="Tweet body",
                favorite_count=10,
                retweet_count=2,
                reply_count=1,
                media=[SimpleNamespace(media_url_https="https://img.example.com/1.png")],
            )

    guest_module = SimpleNamespace(GuestClient=_GuestClient)
    with patch.dict(
        sys.modules,
        {
            "twikit": SimpleNamespace(guest=guest_module),
            "twikit.guest": guest_module,
        },
        clear=False,
    ):
        result = await websearch_server.handle_twitter(
            "https://x.com/user/status/123"
        )

    assert "@user" in result
    assert "Likes: 10" in result
    assert "https://img.example.com/1.png" in result


@pytest.mark.asyncio
async def test_handle_medium_and_archive_return_extracted_text(monkeypatch):
    class _AsyncSessionContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200, text="<html>article</html>" * 80)

    curl_requests_module = SimpleNamespace(AsyncSession=_AsyncSessionContext)
    monkeypatch.setattr(websearch_server, "extract", lambda _html, _mode, _url="": "article" * 60)

    with patch.dict(
        sys.modules,
        {
            "curl_cffi": SimpleNamespace(requests=curl_requests_module),
            "curl_cffi.requests": curl_requests_module,
        },
        clear=False,
    ):
        medium = await websearch_server.handle_medium("https://medium.com/story", "full")
        archive = await websearch_server.handle_archive("https://example.com/paywall", "full")

    assert medium == "article" * 60
    assert archive == "article" * 60
