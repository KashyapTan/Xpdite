import asyncio
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from functools import lru_cache
import ipaddress
import os
import random
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

from ddgs import DDGS
from mcp.server.fastmcp import FastMCP

from mcp_servers.servers.websearch.websearch_descriptions import (
    READ_WEBSITE_DESCRIPTION,
    SEARCH_WEB_PAGES_DESCRIPTION,
)

mcp = FastMCP("Web Search Tools")

_DEVNULL = open(os.devnull, "w")
_MAX_RETURN_CHARS = 95_000
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
_EXTERNAL_RELAY_ENV = "WEBSEARCH_ENABLE_EXTERNAL_RELAYS"
_UNSAFE_TIER3_ENV = "WEBSEARCH_ENABLE_UNSAFE_TIER3_BROWSER"
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_REDIRECT_HOPS = 8

# ── Thresholds (tuned from benchmark on 260 URLs, 2026-04-07) ───────
# Benchmark results: 83.5% success, P50=0.56s, P95=2.44s, P99=6.12s
# Content: avg=19,159 chars, median=11,061 chars, P10=557, P25=5,487
_SUCCESS_CHAR_THRESHOLD = (
    5000  # P25 threshold - content is "good enough" for early return
)
_SPARSE_CHAR_THRESHOLD = 500  # ~P10 threshold - below this = sparse content warning
_TIER1_TIMEOUT = 7.0  # P99 + buffer for tier 1 (curl)
_TIER2_TIMEOUT = 10.0  # Timeout for tier 2 (camoufox)
_TIER3_TIMEOUT = 12.0  # Timeout for tier 3 (nodriver)
_GLOBAL_TIMEOUT = 12.0  # Overall timeout for entire scrape operation
_STAGGER_DELAY = 1.5  # Delay before starting browser tiers if tier1 hasn't returned

# ── Connection pooling ──────────────────────────────────────────────
# Reuse HTTP sessions across multiple requests to avoid connection setup overhead
_curl_session_instance: Any = None
_httpx_client_instance: Any = None
_httpx_noredirect_client_instance: Any = None

# Locks to prevent race conditions during initialization
_curl_session_lock = asyncio.Lock()
_httpx_client_lock = asyncio.Lock()
_httpx_noredirect_client_lock = asyncio.Lock()

# ── Browser Pool ────────────────────────────────────────────────────
# Keep browser instances warm for faster subsequent requests
_camoufox_pool: asyncio.Queue | None = None
_camoufox_pool_lock = asyncio.Lock()
_CAMOUFOX_POOL_SIZE = 2  # Number of warm browser instances to maintain


@dataclass
class TierAttempt:
    """Result from attempting a tier."""

    tier: str
    success: bool
    content: str | None = None
    content_length: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None


@dataclass
class ScrapeResult:
    """Complete result from scraping a URL."""

    url: str
    mode: str
    success: bool
    content: str | None = None
    content_length: int = 0
    winning_tier: str | None = None
    total_elapsed_seconds: float = 0.0
    tier_attempts: list[TierAttempt] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    access_restriction_detected: bool = False
    sparse_content: bool = False


# ── Access Restriction Detection ────────────────────────────────────
ACCESS_RESTRICTION_SIGNALS = [
    "please log in",
    "please sign in",
    "sign in to continue",
    "sign in to view",
    "log in to continue",
    "log in to view",
    "create an account",
    "you don't have permission",
    "you do not have permission",
    "access denied",
    "access restricted",
    "subscription required",
    "subscribe to read",
    "subscribe to continue",
    "members only",
    "premium content",
    "unlock this article",
    "verify you are human",
    "complete the captcha",
    "prove you're not a robot",
    "enable cookies",
    "cookies are required",
    "403 forbidden",
    "401 unauthorized",
    "payment required",
    "upgrade to access",
    "join to unlock",
    "register to view",
    "login required",
    "authentication required",
]

PAYWALL_SIGNALS = [
    "subscribe now",
    "start your free trial",
    "limited articles remaining",
    "you've reached your limit",
    "become a member",
    "premium subscriber",
    "exclusive content",
    "paywall",
    "meter limit",
]


def _detect_access_restriction(text: str) -> tuple[bool, list[str]]:
    """Detect if content indicates access restriction (login/paywall/captcha)."""
    if not text:
        return False, []

    text_lower = text[:3000].lower()
    detected_signals = []

    for signal in ACCESS_RESTRICTION_SIGNALS:
        if signal in text_lower:
            detected_signals.append(signal)

    for signal in PAYWALL_SIGNALS:
        if signal in text_lower:
            detected_signals.append(f"paywall: {signal}")

    return len(detected_signals) > 0, detected_signals[:3]  # Return top 3 signals


async def _get_curl_session():
    """Get or create a reusable curl_cffi AsyncSession with thread-safe initialization."""
    global _curl_session_instance
    if _curl_session_instance is None:
        async with _curl_session_lock:
            if _curl_session_instance is None:  # Double-check pattern
                try:
                    from curl_cffi.requests import AsyncSession

                    _curl_session_instance = AsyncSession(timeout=20)
                except ImportError:
                    return None
    return _curl_session_instance


async def _get_httpx_client():
    """Get or create a reusable httpx AsyncClient with redirect following."""
    global _httpx_client_instance
    if _httpx_client_instance is None:
        async with _httpx_client_lock:
            if _httpx_client_instance is None:  # Double-check pattern
                try:
                    import httpx

                    _httpx_client_instance = httpx.AsyncClient(
                        timeout=20, follow_redirects=True
                    )
                except ImportError:
                    return None
    return _httpx_client_instance


async def _get_httpx_noredirect_client():
    """Get or create a reusable httpx AsyncClient WITHOUT redirect following."""
    global _httpx_noredirect_client_instance
    if _httpx_noredirect_client_instance is None:
        async with _httpx_noredirect_client_lock:
            if _httpx_noredirect_client_instance is None:  # Double-check pattern
                try:
                    import httpx

                    _httpx_noredirect_client_instance = httpx.AsyncClient(
                        timeout=10, follow_redirects=False
                    )
                except ImportError:
                    return None
    return _httpx_noredirect_client_instance


async def _get_camoufox_browser():
    """Get a browser from the pool or create a new one."""
    global _camoufox_pool

    async with _camoufox_pool_lock:
        if _camoufox_pool is None:
            _camoufox_pool = asyncio.Queue(maxsize=_CAMOUFOX_POOL_SIZE)

    try:
        # Try to get from pool (non-blocking)
        browser = _camoufox_pool.get_nowait()
        return browser
    except asyncio.QueueEmpty:
        # Pool empty, create new browser
        return await _create_camoufox_browser()


async def _create_camoufox_browser():
    """Create a new Camoufox browser instance."""
    try:
        from browserforge.fingerprints import Screen
        from camoufox.async_api import AsyncCamoufox

        browser = await AsyncCamoufox(
            headless=True,
            os=["windows", "macos"],
            screen=Screen(max_width=1920, max_height=1080),
            humanize=True,
            firefox_user_prefs={
                "privacy.trackingprotection.enabled": False,
                "privacy.trackingprotection.pbmode.enabled": False,
                "privacy.trackingprotection.socialtracking.enabled": False,
                "privacy.trackingprotection.fingerprinting.enabled": False,
                "privacy.trackingprotection.cryptomining.enabled": False,
                "privacy.contentblocking.category": "standard",
                "network.cookie.cookieBehavior": 0,
            },
        ).__aenter__()
        return browser
    except ImportError:
        return None
    except Exception:
        return None


async def _return_camoufox_browser(browser):
    """Return a browser to the pool or close it if pool is full."""
    global _camoufox_pool

    if browser is None:
        return

    try:
        if _camoufox_pool is not None:
            _camoufox_pool.put_nowait(browser)
        else:
            await browser.__aexit__(None, None, None)
    except asyncio.QueueFull:
        # Pool full, close this browser
        try:
            await browser.__aexit__(None, None, None)
        except Exception:
            pass
    except Exception:
        pass


async def cleanup_http_clients():
    """Clean up HTTP client resources. Call on server shutdown."""
    global \
        _curl_session_instance, \
        _httpx_client_instance, \
        _httpx_noredirect_client_instance
    global _camoufox_pool

    if _curl_session_instance is not None:
        try:
            await _curl_session_instance.close()
        except Exception:
            pass
        _curl_session_instance = None

    if _httpx_client_instance is not None:
        try:
            await _httpx_client_instance.aclose()
        except Exception:
            pass
        _httpx_client_instance = None

    if _httpx_noredirect_client_instance is not None:
        try:
            await _httpx_noredirect_client_instance.aclose()
        except Exception:
            pass
        _httpx_noredirect_client_instance = None

    # Clean up browser pool
    if _camoufox_pool is not None:
        while not _camoufox_pool.empty():
            try:
                browser = _camoufox_pool.get_nowait()
                await browser.__aexit__(None, None, None)
            except Exception:
                pass
        _camoufox_pool = None


TWITTER_DOMAINS = {"twitter.com", "x.com", "www.twitter.com", "www.x.com"}

MEDIUM_DOMAINS = {
    "medium.com",
    "towardsdatascience.com",
    "betterprogramming.pub",
    "levelup.gitconnected.com",
    "javascript.plainenglish.io",
    "uxdesign.cc",
    "hackernoon.com",
    "codeburst.io",
    "itnext.io",
    "proandroiddev.com",
    "infosecwriteups.com",
}

JS_REQUIRED_DOMAINS = {
    "x.com",
    "twitter.com",
    "www.x.com",
    "www.twitter.com",
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "linkedin.com",
    "www.linkedin.com",
    "tiktok.com",
    "www.tiktok.com",
    "reddit.com",
    "www.reddit.com",
    "notion.so",
    "www.notion.so",
    "figma.com",
    "www.figma.com",
}

JS_WALL_SIGNALS = [
    "javascript is disabled",
    "javascript must be enabled",
    "enable javascript",
    "please enable javascript",
    "enhanced tracking protection",
]

_SKELETON_RATIO = 0.04
_SKELETON_MIN_HTML = 10_000

SPA_SIGNATURES = [
    '<div id="root">',
    '<div id="app">',
    '<div id="__next">',
    '<div id="gatsby-focus-wrapper">',
    "window.__next_data__",
    "ng-version=",
    "data-reactroot",
]


@lru_cache(maxsize=4)
def _normalize_mode(mode: str) -> str | None:
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode in {"precision", "full"}:
        return normalized_mode
    return None


def _coerce_force_tier(force_tier: int | str | None) -> tuple[int | None, str | None]:
    if force_tier is None:
        return None, None

    if isinstance(force_tier, bool):
        return (
            None,
            f"ERROR: Invalid force_tier '{force_tier}'. Valid values are 1, 2, or 3.",
        )

    parsed_force_tier: int | str = force_tier
    if isinstance(force_tier, str):
        stripped_force_tier = force_tier.strip()
        if stripped_force_tier in {"1", "2", "3"}:
            parsed_force_tier = int(stripped_force_tier)
        else:
            return (
                None,
                f"ERROR: Invalid force_tier '{force_tier}'. Valid values are 1, 2, or 3.",
            )

    if parsed_force_tier not in (1, 2, 3):
        return (
            None,
            f"ERROR: Invalid force_tier '{force_tier}'. Valid values are 1, 2, or 3.",
        )

    return int(parsed_force_tier), None


@lru_cache(maxsize=128)
def _host(url: str) -> str:
    return urlparse(url).hostname or ""


def _is_public_ip_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return address.is_global


def _validate_read_website_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"ERROR: Invalid URL: {url}. URL must start with http:// or https://"

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return f"ERROR: Invalid URL: {url}. URL host is missing."
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return f"ERROR: URL host '{host}' is not allowed."

    try:
        resolved_ips = [ipaddress.ip_address(host)]
    except ValueError:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            return f"ERROR: Could not resolve host '{host}': {exc}."

        resolved_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        seen_ips: set[str] = set()
        for _family, _socktype, _proto, _canonname, sockaddr in addr_info:
            ip_text = sockaddr[0]
            if ip_text in seen_ips:
                continue
            seen_ips.add(ip_text)
            try:
                resolved_ips.append(ipaddress.ip_address(ip_text))
            except ValueError:
                continue

        if not resolved_ips:
            return f"ERROR: Could not resolve host '{host}' to an IP address."

    for resolved_ip in resolved_ips:
        if not _is_public_ip_address(resolved_ip):
            return (
                f"ERROR: URL host '{host}' resolves to non-public IP '{resolved_ip}' "
                "and is not allowed."
            )

    return None


def _external_relays_enabled() -> bool:
    return os.environ.get(_EXTERNAL_RELAY_ENV, "").strip().lower() in _TRUTHY_ENV_VALUES


def _unsafe_tier3_enabled() -> bool:
    return os.environ.get(_UNSAFE_TIER3_ENV, "").strip().lower() in _TRUTHY_ENV_VALUES


async def _resolve_safe_redirect_chain(
    url: str,
    max_hops: int = _MAX_REDIRECT_HOPS,
    *,
    fail_open: bool = False,
) -> str | None:
    client = await _get_httpx_noredirect_client()
    if client is None:
        return None

    current_url = url
    seen_urls: set[str] = set()

    try:
        for _ in range(max_hops):
            if current_url in seen_urls:
                return None
            seen_urls.add(current_url)

            if _validate_read_website_url(current_url):
                return None

            response = await client.get(
                current_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )

            if response.status_code not in _REDIRECT_STATUSES:
                return str(response.request.url)

            location = response.headers.get("location")
            if not location:
                return str(response.request.url)

            next_url = urljoin(str(response.request.url), location)
            if _validate_read_website_url(next_url):
                return None
            current_url = next_url
    except Exception:
        return url if fail_open else None

    return None


def is_twitter(url: str) -> bool:
    return _host(url) in TWITTER_DOMAINS


def is_medium(url: str) -> bool:
    host = _host(url)
    return host in MEDIUM_DOMAINS or host.endswith(".medium.com")


def needs_js(url: str) -> bool:
    return _host(url) in JS_REQUIRED_DOMAINS


def has_js_wall(html: str) -> bool:
    return any(signal in html[:3000].lower() for signal in JS_WALL_SIGNALS)


def is_js_skeleton(html: str, text: str) -> bool:
    if len(html) < _SKELETON_MIN_HTML:
        return False
    if len(text) / max(len(html), 1) < _SKELETON_RATIO:
        return True
    html_lower = html[:5000].lower()
    if (
        any(signature.lower() in html_lower for signature in SPA_SIGNATURES)
        and len(text) < 500
    ):
        return True
    return False


def extract(html: str, mode: str, url: str = "") -> str:
    if mode == "full":
        try:
            import markdownify
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "svg", "noscript", "meta", "head"]):
                tag.decompose()
            markdown_text = markdownify.markdownify(
                str(soup),
                heading_style="ATX",
                bullets="-",
                strip=["a"],
            )
            markdown_text = re.sub(r"\n{3,}", "\n\n", markdown_text).strip()
            if markdown_text and len(markdown_text) > 100:
                return markdown_text
        except Exception:
            pass

    try:
        import trafilatura

        result = trafilatura.extract(
            html,
            url=url or None,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_recall=True,
            deduplicate=True,
        )
        if result and len(result.strip()) > 100:
            return result.strip()
    except Exception:
        pass

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "header",
                "footer",
                "aside",
                "form",
                "svg",
                "noscript",
            ]
        ):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)

    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def tier1_curl(url: str, mode: str) -> tuple[str, str] | None:
    session = await _get_curl_session()
    if session is None:
        return None

    targets = ["chrome124", "chrome120", "chrome110", "edge101", "edge99"]
    try:
        current_url = url
        response = None
        seen_urls: set[str] = set()

        for _ in range(_MAX_REDIRECT_HOPS):
            if current_url in seen_urls:
                return None
            seen_urls.add(current_url)

            if _validate_read_website_url(current_url):
                return None

            response = await session.get(
                current_url,
                impersonate=random.choice(targets),
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.google.com/",
                },
                timeout=_TIER1_TIMEOUT,
                allow_redirects=False,
            )

            if response.status_code not in _REDIRECT_STATUSES:
                break

            location = response.headers.get("location")
            if not location:
                break

            next_url = urljoin(str(getattr(response, "url", current_url)), location)
            if _validate_read_website_url(next_url):
                return None
            current_url = next_url
        else:
            return None

        if response is None:
            return None

        if response.status_code == 200 and len(response.text) > 500:
            final_url = str(getattr(response, "url", url))
            if _validate_read_website_url(final_url):
                return None
            if has_js_wall(response.text):
                return None
            text = extract(response.text, mode, final_url)
            return text, response.text
        return None
    except Exception:
        return None


async def tier1_5_jina(url: str) -> str | None:
    client = await _get_httpx_client()
    if client is None:
        return None

    jina_url = f"https://r.jina.ai/{url}"
    headers = {"Accept": "text/plain", "X-Return-Format": "text"}
    api_key = os.environ.get("JINA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = await client.get(jina_url, headers=headers)
        response.raise_for_status()
        content = response.text.strip()
        return content if content and len(content) > 200 else None
    except Exception:
        return None


async def tier2_camoufox(url: str, mode: str) -> str | None:
    browser = None
    try:
        from browserforge.fingerprints import Screen
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        return None

    try:
        safe_url = await _resolve_safe_redirect_chain(url, fail_open=True)
        if not safe_url:
            return None

        # Use browser pool
        browser = await _get_camoufox_browser()
        if browser is None:
            # Fallback to creating directly if pool fails
            async with AsyncCamoufox(
                headless=True,
                os=["windows", "macos"],
                screen=Screen(max_width=1920, max_height=1080),
                humanize=True,
                firefox_user_prefs={
                    "privacy.trackingprotection.enabled": False,
                    "privacy.trackingprotection.pbmode.enabled": False,
                    "privacy.trackingprotection.socialtracking.enabled": False,
                    "privacy.trackingprotection.fingerprinting.enabled": False,
                    "privacy.trackingprotection.cryptomining.enabled": False,
                    "privacy.contentblocking.category": "standard",
                    "network.cookie.cookieBehavior": 0,
                },
            ) as fallback_browser:
                page = await fallback_browser.new_page()

                async def _enforce_safe_requests(route):
                    request = route.request
                    request_url = getattr(request, "url", "")
                    parsed = urlparse(request_url)
                    if parsed.scheme not in {"http", "https"}:
                        await route.continue_()
                        return

                    if _validate_read_website_url(request_url):
                        await route.abort()
                        return
                    await route.continue_()

                await page.route("**/*", _enforce_safe_requests)
                await page.goto(
                    safe_url, wait_until="load", timeout=int(_TIER2_TIMEOUT * 1000)
                )
                html = await page.content()
                final_url = getattr(page, "url", safe_url)
                await page.close()

            if isinstance(final_url, str) and _validate_read_website_url(final_url):
                return None
            if has_js_wall(html):
                return None
            result = extract(
                html, mode, final_url if isinstance(final_url, str) else url
            )
            return result if len(result) > 100 else None

        # Use pooled browser
        page = await browser.new_page()

        async def _enforce_safe_requests(route):
            request = route.request
            request_url = getattr(request, "url", "")
            parsed = urlparse(request_url)
            if parsed.scheme not in {"http", "https"}:
                await route.continue_()
                return

            if _validate_read_website_url(request_url):
                await route.abort()
                return
            await route.continue_()

        await page.route("**/*", _enforce_safe_requests)
        await page.goto(safe_url, wait_until="load", timeout=int(_TIER2_TIMEOUT * 1000))
        html = await page.content()
        final_url = getattr(page, "url", safe_url)
        await page.close()

        # Return browser to pool
        await _return_camoufox_browser(browser)
        browser = None  # Mark as returned

        if isinstance(final_url, str) and _validate_read_website_url(final_url):
            return None
        if has_js_wall(html):
            return None
        result = extract(html, mode, final_url if isinstance(final_url, str) else url)
        return result if len(result) > 100 else None
    except Exception:
        return None
    finally:
        # Return browser to pool if not already returned
        if browser is not None:
            await _return_camoufox_browser(browser)


async def tier3_nodriver(url: str, mode: str) -> str | None:
    try:
        import nodriver as uc
    except ImportError:
        return None

    browser = None
    try:
        safe_url = await _resolve_safe_redirect_chain(url)
        if not safe_url:
            return None

        browser = await uc.start(headless=True)
        page = await asyncio.wait_for(browser.get(safe_url), timeout=_TIER3_TIMEOUT)
        html = await asyncio.wait_for(page.get_content(), timeout=10.0)
        final_url = getattr(page, "url", safe_url)
        if isinstance(final_url, str) and _validate_read_website_url(final_url):
            return None
        if not html or has_js_wall(html):
            return None
        return extract(html, mode, final_url if isinstance(final_url, str) else url)
    except Exception:
        return None
    finally:
        if browser:
            try:
                browser.stop()
            except Exception:
                pass


async def handle_twitter(url: str) -> str | None:
    try:
        from twikit.guest import GuestClient
    except ImportError:
        return None

    match = re.search(r"/status/(\d+)", url)
    if not match:
        return None
    tweet_id = match.group(1)

    try:
        client = GuestClient()
        await client.activate()
        tweet = await client.get_tweet_by_id(tweet_id)
        if not tweet:
            return None

        lines: list[str] = []
        if hasattr(tweet, "user") and tweet.user:
            lines.append(f"@{tweet.user.screen_name} — {tweet.user.name}")
        if hasattr(tweet, "created_at") and tweet.created_at:
            lines.append(f"Posted: {tweet.created_at}")
        lines.append("")
        lines.append(
            getattr(tweet, "full_text", None) or getattr(tweet, "text", "") or ""
        )
        lines.append("")

        stats: list[str] = []
        for attr, label in [
            ("favorite_count", "Likes"),
            ("retweet_count", "Retweets"),
            ("reply_count", "Replies"),
        ]:
            if hasattr(tweet, attr):
                stats.append(f"{label}: {getattr(tweet, attr)}")
        if stats:
            lines.append("  ".join(stats))

        if getattr(tweet, "media", None):
            lines.append(f"\nMedia ({len(tweet.media)} item(s)):")
            for media in tweet.media:
                source = getattr(media, "media_url_https", None) or getattr(
                    media, "url", None
                )
                if source:
                    lines.append(f"  {source}")

        return "\n".join(lines)
    except Exception:
        return None


async def handle_medium(url: str, mode: str) -> str | None:
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        return None

    mirrors = [f"https://freedium.cfd/{url}", f"https://freedium-mirror.cfd/{url}"]
    for mirror in mirrors:
        try:
            async with AsyncSession() as session:
                response = await session.get(
                    mirror,
                    impersonate="chrome124",
                    headers={"Accept-Language": "en-US,en;q=0.9"},
                    timeout=20,
                    allow_redirects=True,
                )
            if response.status_code == 200 and len(response.text) > 500:
                text = extract(response.text, mode, url)
                if len(text) > 300:
                    return text
        except Exception:
            continue
    return None


async def handle_archive(url: str, mode: str) -> str | None:
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        return None

    try:
        async with AsyncSession() as session:
            response = await session.get(
                f"https://archive.ph/newest/{url}",
                impersonate="chrome124",
                headers={"Accept-Language": "en-US,en;q=0.9"},
                timeout=20,
                allow_redirects=True,
            )
        if response.status_code == 200 and len(response.text) > 500:
            text = extract(response.text, mode, url)
            if len(text) > 300:
                return text
    except Exception:
        pass
    return None


async def _run_tier_with_timeout(
    tier_fn,
    url: str,
    mode: str,
    tier_name: str,
    timeout: float,
) -> TierAttempt:
    """Run a tier function with timeout and return structured result."""
    import time

    start = time.perf_counter()

    try:
        async with asyncio.timeout(timeout):
            result = await tier_fn(url, mode)

        elapsed = time.perf_counter() - start

        if result is None:
            return TierAttempt(
                tier=tier_name,
                success=False,
                content_length=0,
                elapsed_seconds=elapsed,
                error="No content returned",
            )

        # Handle tuple return (text, raw_html) from tier1_curl
        content = result[0] if isinstance(result, tuple) else result
        content_length = len(content) if content else 0

        return TierAttempt(
            tier=tier_name,
            success=content_length > 0,
            content=content,
            content_length=content_length,
            elapsed_seconds=elapsed,
        )

    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - start
        return TierAttempt(
            tier=tier_name,
            success=False,
            content_length=0,
            elapsed_seconds=elapsed,
            error=f"Timeout after {timeout:.1f}s",
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        return TierAttempt(
            tier=tier_name,
            success=False,
            content_length=0,
            elapsed_seconds=elapsed,
            error=str(e)[:200],
        )


async def scrape_concurrent(
    url: str,
    mode: str,
    force_tier: int | None = None,
    skip_twitter: bool = False,
    allow_external_relays: bool = False,
    allow_unsafe_tier3: bool = False,
) -> ScrapeResult:
    """
    Scrape URL using concurrent tier execution with staggered start.

    Strategy:
    1. Start Tier 1 immediately
    2. After STAGGER_DELAY seconds (or if Tier 1 fails early), start Tier 2/3
    3. Return first result that exceeds SUCCESS_CHAR_THRESHOLD
    4. If no result exceeds threshold, return best available
    """
    import time

    start_time = time.perf_counter()

    result = ScrapeResult(url=url, mode=mode, success=False)
    best_attempt: TierAttempt | None = None  # Initialize before try block

    # Wrap EVERYTHING in the global timeout to prevent any path from hanging
    try:
        async with asyncio.timeout(_GLOBAL_TIMEOUT):
            # Handle special cases first (Twitter, Medium) - now inside timeout!
            if force_tier is None:
                if is_twitter(url) and not skip_twitter:
                    try:
                        twitter_result = await asyncio.wait_for(
                            handle_twitter(url), timeout=_TIER1_TIMEOUT
                        )
                        if (
                            twitter_result
                            and len(twitter_result) > _SPARSE_CHAR_THRESHOLD
                        ):
                            result.success = True
                            result.content = twitter_result
                            result.content_length = len(twitter_result)
                            result.winning_tier = "twitter_twikit"
                            result.total_elapsed_seconds = (
                                time.perf_counter() - start_time
                            )
                            return result
                    except asyncio.TimeoutError:
                        result.tier_attempts.append(
                            TierAttempt(
                                tier="twitter_twikit",
                                success=False,
                                error=f"Timeout after {_TIER1_TIMEOUT}s",
                                elapsed_seconds=_TIER1_TIMEOUT,
                            )
                        )
                    except Exception as e:
                        result.tier_attempts.append(
                            TierAttempt(
                                tier="twitter_twikit",
                                success=False,
                                error=str(e)[:200],
                                elapsed_seconds=time.perf_counter() - start_time,
                            )
                        )

                if is_medium(url) and allow_external_relays:
                    try:
                        medium_result = await asyncio.wait_for(
                            handle_medium(url, mode), timeout=_TIER1_TIMEOUT
                        )
                        if (
                            medium_result
                            and len(medium_result) > _SPARSE_CHAR_THRESHOLD
                        ):
                            result.success = True
                            result.content = medium_result
                            result.content_length = len(medium_result)
                            result.winning_tier = "medium_freedium"
                            result.total_elapsed_seconds = (
                                time.perf_counter() - start_time
                            )
                            return result
                    except asyncio.TimeoutError:
                        pass  # Fall through to regular tiers
                    except Exception:
                        pass

                    try:
                        archive_result = await asyncio.wait_for(
                            handle_archive(url, mode), timeout=_TIER1_TIMEOUT
                        )
                        if (
                            archive_result
                            and len(archive_result) > _SPARSE_CHAR_THRESHOLD
                        ):
                            result.success = True
                            result.content = archive_result
                            result.content_length = len(archive_result)
                            result.winning_tier = "medium_archive"
                            result.total_elapsed_seconds = (
                                time.perf_counter() - start_time
                            )
                            return result
                    except asyncio.TimeoutError:
                        pass
                    except Exception:
                        pass

            # Determine which tiers to run
            tiers_to_run: list[tuple[str, Any, float]] = []

            if force_tier == 1 or (force_tier is None and not needs_js(url)):
                tiers_to_run.append(("tier1_curl", tier1_curl, _TIER1_TIMEOUT))

            if force_tier in (None, 2):
                tiers_to_run.append(("tier2_camoufox", tier2_camoufox, _TIER2_TIMEOUT))

            if force_tier in (None, 3) and allow_unsafe_tier3:
                tiers_to_run.append(("tier3_nodriver", tier3_nodriver, _TIER3_TIMEOUT))

            if not tiers_to_run:
                result.warnings.append("No tiers available to run")
                result.suggestions.append(
                    "Enable tier 3 with WEBSEARCH_ENABLE_UNSAFE_TIER3_BROWSER=1"
                )
                result.total_elapsed_seconds = time.perf_counter() - start_time
                return result

            # Run tiers with staggered start
            pending_tasks: dict[asyncio.Task, str] = {}
            completed_attempts: list[TierAttempt] = []
            best_attempt: TierAttempt | None = None

            # Start first tier immediately
            first_tier = tiers_to_run[0]
            first_task = asyncio.create_task(
                _run_tier_with_timeout(
                    first_tier[1], url, mode, first_tier[0], first_tier[2]
                )
            )
            pending_tasks[first_task] = first_tier[0]

            # Schedule remaining tiers with stagger delay
            remaining_tiers = tiers_to_run[1:]
            stagger_task: asyncio.Task | None = None

            if remaining_tiers:

                async def _start_remaining_tiers():
                    await asyncio.sleep(_STAGGER_DELAY)
                    return "stagger_complete"

                stagger_task = asyncio.create_task(_start_remaining_tiers())

            browser_tiers_started = False

            while pending_tasks or (stagger_task and not stagger_task.done()):
                # Build wait set
                wait_set = set(pending_tasks.keys())
                if stagger_task and not stagger_task.done():
                    wait_set.add(stagger_task)

                if not wait_set:
                    break

                done, _ = await asyncio.wait(
                    wait_set, return_when=asyncio.FIRST_COMPLETED
                )

                for task in done:
                    if task is stagger_task:
                        # Stagger delay complete, start browser tiers
                        if not browser_tiers_started:
                            browser_tiers_started = True
                            for tier_name, tier_fn, tier_timeout in remaining_tiers:
                                new_task = asyncio.create_task(
                                    _run_tier_with_timeout(
                                        tier_fn, url, mode, tier_name, tier_timeout
                                    )
                                )
                                pending_tasks[new_task] = tier_name
                        continue

                    # Tier completed
                    tier_name = pending_tasks.pop(task)
                    try:
                        attempt = task.result()
                    except Exception as e:
                        attempt = TierAttempt(
                            tier=tier_name,
                            success=False,
                            error=str(e)[:200],
                        )

                    completed_attempts.append(attempt)
                    result.tier_attempts.append(attempt)

                    # Check if this result is good enough for early return
                    if (
                        attempt.success
                        and attempt.content_length >= _SUCCESS_CHAR_THRESHOLD
                    ):
                        # Cancel remaining tasks
                        for remaining_task in pending_tasks:
                            remaining_task.cancel()
                        if stagger_task and not stagger_task.done():
                            stagger_task.cancel()

                        best_attempt = attempt
                        break

                    # Track best attempt so far
                    if attempt.success:
                        if (
                            best_attempt is None
                            or attempt.content_length > best_attempt.content_length
                        ):
                            best_attempt = attempt

                    # If tier 1 failed quickly, start browser tiers immediately
                    if (
                        not browser_tiers_started
                        and tier_name == "tier1_curl"
                        and not attempt.success
                    ):
                        browser_tiers_started = True
                        if stagger_task and not stagger_task.done():
                            stagger_task.cancel()
                        for tier_name_r, tier_fn, tier_timeout in remaining_tiers:
                            new_task = asyncio.create_task(
                                _run_tier_with_timeout(
                                    tier_fn, url, mode, tier_name_r, tier_timeout
                                )
                            )
                            pending_tasks[new_task] = tier_name_r

                if (
                    best_attempt
                    and best_attempt.content_length >= _SUCCESS_CHAR_THRESHOLD
                ):
                    break

    except asyncio.TimeoutError:
        # Global timeout reached, cancel all pending
        result.warnings.append(f"Global timeout ({_GLOBAL_TIMEOUT}s) reached")

    # Finalize result
    result.total_elapsed_seconds = time.perf_counter() - start_time

    if best_attempt and best_attempt.content:
        result.success = True
        result.content = best_attempt.content
        result.content_length = best_attempt.content_length
        result.winning_tier = best_attempt.tier

        # Check for sparse content
        if best_attempt.content_length < _SPARSE_CHAR_THRESHOLD:
            result.sparse_content = True
            result.warnings.append(
                f"Sparse content extracted ({best_attempt.content_length} chars < {_SPARSE_CHAR_THRESHOLD} threshold)"
            )

        # Check for access restrictions
        is_restricted, signals = _detect_access_restriction(best_attempt.content)
        if is_restricted:
            result.access_restriction_detected = True
            result.warnings.append(f"Access restriction detected: {', '.join(signals)}")
            result.suggestions.append(
                "Try external relays (WEBSEARCH_ENABLE_EXTERNAL_RELAYS=1)"
            )
            result.suggestions.append("Try archive fallback for paywalled content")
    else:
        # All tiers failed
        failed_tiers = [a.tier for a in result.tier_attempts]
        result.warnings.append(f"All tiers failed: {', '.join(failed_tiers)}")

        # Add suggestions based on what was tried
        if not allow_external_relays:
            result.suggestions.append(
                f"Enable external relays: {_EXTERNAL_RELAY_ENV}=1"
            )
        if not allow_unsafe_tier3:
            result.suggestions.append(f"Enable Tier 3 browser: {_UNSAFE_TIER3_ENV}=1")
        if force_tier is not None:
            result.suggestions.append("Try without force_tier to allow auto-escalation")

    return result


# Legacy scrape function for backward compatibility
async def scrape(
    url: str,
    mode: str,
    force_tier: int | None = None,
    skip_twitter: bool = False,
    allow_external_relays: bool = False,
    allow_unsafe_tier3: bool = False,
) -> tuple[str, str] | None:
    """
    Legacy wrapper around scrape_concurrent for backward compatibility.
    Returns (method, content) tuple or None.
    """
    result = await scrape_concurrent(
        url=url,
        mode=mode,
        force_tier=force_tier,
        skip_twitter=skip_twitter,
        allow_external_relays=allow_external_relays,
        allow_unsafe_tier3=allow_unsafe_tier3,
    )

    if result.success and result.content and result.winning_tier:
        return result.winning_tier, result.content
    return None


def _truncate_for_mcp(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_RETURN_CHARS:
        return text, False
    return text[:_MAX_RETURN_CHARS], True


def _format_scrape_result(result: ScrapeResult) -> str:
    """Format scrape result with enhanced metadata and suggestions."""
    if not result.success or not result.content:
        # Format error output
        lines = [f"ERROR: Failed to fetch {result.url}"]
        lines.append("")

        if result.tier_attempts:
            lines.append("Tier Results:")
            for attempt in result.tier_attempts:
                status = "OK" if attempt.success else "FAILED"
                error_info = f" ({attempt.error})" if attempt.error else ""
                chars = f", {attempt.content_length} chars" if attempt.success else ""
                lines.append(f"  - {attempt.tier}: {status}{error_info}{chars}")
            lines.append("")

        if result.warnings:
            lines.append("Warnings:")
            for warning in result.warnings:
                lines.append(f"  - {warning}")
            lines.append("")

        if result.suggestions:
            lines.append("Suggestions:")
            for suggestion in result.suggestions:
                lines.append(f"  - {suggestion}")

        return "\n".join(lines)

    # Format success output
    output, truncated = _truncate_for_mcp(result.content)

    # Build tier info string
    tier_info_parts = [f"{result.winning_tier} ({result.total_elapsed_seconds:.1f}s)"]
    other_tiers = [
        f"{a.tier} ({'ok' if a.success else 'fail'}: {a.content_length} chars)"
        for a in result.tier_attempts
        if a.tier != result.winning_tier
    ]
    if other_tiers:
        tier_info_parts.append(f"other: {', '.join(other_tiers)}")

    header_lines = [
        f"SOURCE: {result.url}",
        f"METHOD: {' | '.join(tier_info_parts)}",
        f"MODE: {result.mode}",
        f"CHARS: original={result.content_length:,}; returned={len(output):,}",
    ]

    # Add status if there are issues
    status_parts = []
    if result.sparse_content:
        status_parts.append("SPARSE_CONTENT")
    if result.access_restriction_detected:
        status_parts.append("ACCESS_RESTRICTED")
    if status_parts:
        header_lines.append(f"STATUS: {', '.join(status_parts)}")

    header = "\n".join(header_lines)

    # Add warnings and suggestions if present
    footer_parts = []

    if result.warnings:
        footer_parts.append("\nWARNINGS:")
        for warning in result.warnings:
            footer_parts.append(f"  - {warning}")

    if result.suggestions:
        footer_parts.append("\nSUGGESTIONS:")
        for suggestion in result.suggestions:
            footer_parts.append(f"  - {suggestion}")

    footer = "\n".join(footer_parts)

    if truncated:
        output = f"{output}\n\n[TRUNCATED] Output capped at {_MAX_RETURN_CHARS:,} characters."

    if footer:
        return f"{header}\n\n{output}\n{footer}"
    return f"{header}\n\n{output}"


@mcp.tool(description=SEARCH_WEB_PAGES_DESCRIPTION)
def search_web_pages(query: str) -> list[dict[str, Any]]:
    try:
        with redirect_stdout(_DEVNULL), redirect_stderr(_DEVNULL):
            results = DDGS().text(
                query=query,
                region="wt-wt",
                safesearch="off",
                max_results=10,
            )
            results_list = list(results)
        if not results_list:
            return [{"error": "No results found", "query": query}]
        return results_list
    except Exception as exc:
        return [{"error": f"Search failed: {str(exc)}", "query": query}]


@mcp.tool(description=READ_WEBSITE_DESCRIPTION)
async def read_website(
    url: str, mode: str = "full", force_tier: int | str | None = None
) -> str:
    normalized_url = (url or "").strip()
    if not normalized_url:
        return "ERROR: URL is required."
    url_validation_error = _validate_read_website_url(normalized_url)
    if url_validation_error:
        return url_validation_error

    normalized_mode = _normalize_mode(mode)
    if normalized_mode is None:
        return f"ERROR: Invalid mode '{mode}'. Valid values are 'precision' or 'full'."

    resolved_force_tier, force_tier_error = _coerce_force_tier(force_tier)
    if force_tier_error:
        return force_tier_error

    allow_external_relays = _external_relays_enabled()
    allow_unsafe_tier3 = _unsafe_tier3_enabled()

    if resolved_force_tier == 3 and not allow_unsafe_tier3:
        return (
            f"ERROR: force_tier=3 is disabled by default. Set {_UNSAFE_TIER3_ENV}=1 to enable "
            "the Tier 3 Nodriver fallback."
        )

    try:
        with redirect_stdout(_DEVNULL), redirect_stderr(_DEVNULL):
            result = await scrape_concurrent(
                normalized_url,
                normalized_mode,
                force_tier=resolved_force_tier,
                skip_twitter=False,
                allow_external_relays=allow_external_relays,
                allow_unsafe_tier3=allow_unsafe_tier3,
            )
    except Exception as exc:
        return f"ERROR: An unexpected error occurred while scraping {normalized_url}: {str(exc)}"

    return _format_scrape_result(result)


if __name__ == "__main__":
    mcp.run()
