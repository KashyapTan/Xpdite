import asyncio
from contextlib import redirect_stderr, redirect_stdout
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

# ── Connection pooling ──────────────────────────────────────────────
# Reuse HTTP sessions across multiple requests to avoid connection setup overhead
_curl_session_instance: Any = None
_httpx_client_instance: Any = None
_httpx_noredirect_client_instance: Any = None

# Locks to prevent race conditions during initialization
_curl_session_lock = asyncio.Lock()
_httpx_client_lock = asyncio.Lock()
_httpx_noredirect_client_lock = asyncio.Lock()


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
                    _httpx_client_instance = httpx.AsyncClient(timeout=20, follow_redirects=True)
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
                    _httpx_noredirect_client_instance = httpx.AsyncClient(timeout=10, follow_redirects=False)
                except ImportError:
                    return None
    return _httpx_noredirect_client_instance


async def cleanup_http_clients():
    """Clean up HTTP client resources. Call on server shutdown."""
    global _curl_session_instance, _httpx_client_instance, _httpx_noredirect_client_instance

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
        return None, f"ERROR: Invalid force_tier '{force_tier}'. Valid values are 1, 2, or 3."

    parsed_force_tier: int | str = force_tier
    if isinstance(force_tier, str):
        stripped_force_tier = force_tier.strip()
        if stripped_force_tier in {"1", "2", "3"}:
            parsed_force_tier = int(stripped_force_tier)
        else:
            return None, f"ERROR: Invalid force_tier '{force_tier}'. Valid values are 1, 2, or 3."

    if parsed_force_tier not in (1, 2, 3):
        return None, f"ERROR: Invalid force_tier '{force_tier}'. Valid values are 1, 2, or 3."

    return int(parsed_force_tier), None


@lru_cache(maxsize=128)
def _host(url: str) -> str:
    return urlparse(url).hostname or ""


def _is_public_ip_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
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
    if any(signature.lower() in html_lower for signature in SPA_SIGNATURES) and len(text) < 500:
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
                convert_as_inline=["img"],
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
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "svg", "noscript"]):
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
                timeout=15,
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
    try:
        from browserforge.fingerprints import Screen
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        return None

    try:
        safe_url = await _resolve_safe_redirect_chain(url, fail_open=True)
        if not safe_url:
            return None

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
        ) as browser:
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
            await page.goto(safe_url, wait_until="load", timeout=30_000)
            html = await page.content()
            final_url = getattr(page, "url", safe_url)
            await page.close()
        if isinstance(final_url, str) and _validate_read_website_url(final_url):
            return None
        if has_js_wall(html):
            return None
        result = extract(html, mode, final_url if isinstance(final_url, str) else url)
        return result if len(result) > 100 else None
    except Exception:
        return None


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
        page = await asyncio.wait_for(browser.get(safe_url), timeout=45.0)
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
                await browser.stop()
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
        lines.append(getattr(tweet, "full_text", None) or getattr(tweet, "text", "") or "")
        lines.append("")

        stats: list[str] = []
        for attr, label in [("favorite_count", "Likes"), ("retweet_count", "Retweets"), ("reply_count", "Replies")]:
            if hasattr(tweet, attr):
                stats.append(f"{label}: {getattr(tweet, attr)}")
        if stats:
            lines.append("  ".join(stats))

        if getattr(tweet, "media", None):
            lines.append(f"\nMedia ({len(tweet.media)} item(s)):")
            for media in tweet.media:
                source = getattr(media, "media_url_https", None) or getattr(media, "url", None)
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


async def scrape(
    url: str,
    mode: str,
    force_tier: int | None = None,
    skip_twitter: bool = False,
    allow_external_relays: bool = False,
    allow_unsafe_tier3: bool = False,
) -> tuple[str, str] | None:
    if force_tier is None:
        if is_twitter(url):
            if not skip_twitter:
                twitter_result = await handle_twitter(url)
                if twitter_result:
                    return "twitter_twikit", twitter_result
        elif is_medium(url) and allow_external_relays:
            medium_result = await handle_medium(url, mode)
            if medium_result:
                return "medium_freedium", medium_result
            archive_result = await handle_archive(url, mode)
            if archive_result:
                return "medium_archive", archive_result

    run_tier1 = force_tier == 1 or (force_tier is None and not needs_js(url))
    if run_tier1:
        tier1_result = await tier1_curl(url, mode)
        if tier1_result is not None:
            text, raw_html = tier1_result
            if not is_js_skeleton(raw_html, text) and text:
                return "tier1_curl_cffi", text
        if force_tier == 1:
            return None

    if allow_external_relays and force_tier not in (2, 3):
        tier1_5_result = await tier1_5_jina(url)
        if tier1_5_result:
            return "tier1_5_jina", tier1_5_result

    if force_tier in (None, 2):
        tier2_result = await tier2_camoufox(url, mode)
        if tier2_result:
            return "tier2_camoufox", tier2_result
        if force_tier == 2:
            return None

    if force_tier in (None, 3) and allow_unsafe_tier3:
        tier3_result = await tier3_nodriver(url, mode)
        if tier3_result:
            return "tier3_nodriver", tier3_result

    return None


def _truncate_for_mcp(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_RETURN_CHARS:
        return text, False
    return text[:_MAX_RETURN_CHARS], True


def _format_scrape_result(source_url: str, method: str, mode: str, content: str) -> str:
    output, truncated = _truncate_for_mcp(content)
    header = (
        f"SOURCE: {source_url}\n"
        f"METHOD: {method}\n"
        f"MODE: {mode}\n"
        f"CHARS: original={len(content):,}; returned={len(output):,}"
    )
    if truncated:
        output = f"{output}\n\n[TRUNCATED] Output capped at {_MAX_RETURN_CHARS:,} characters."
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
async def read_website(url: str, mode: str = "full", force_tier: int | str | None = None) -> str:
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

    is_twitter_url = is_twitter(normalized_url)
    allow_external_relays = _external_relays_enabled()
    allow_unsafe_tier3 = _unsafe_tier3_enabled()

    if resolved_force_tier == 3 and not allow_unsafe_tier3:
        return (
            f"ERROR: force_tier=3 is disabled by default. Set {_UNSAFE_TIER3_ENV}=1 to enable "
            "the Tier 3 Nodriver fallback."
        )

    if resolved_force_tier is None and is_twitter_url:
        try:
            with redirect_stdout(_DEVNULL), redirect_stderr(_DEVNULL):
                twitter_result = await handle_twitter(normalized_url)
        except Exception:
            twitter_result = None
        if twitter_result:
            return _format_scrape_result(normalized_url, "twitter_twikit", normalized_mode, twitter_result)

    try:
        with redirect_stdout(_DEVNULL), redirect_stderr(_DEVNULL):
            result = await scrape(
                normalized_url,
                normalized_mode,
                force_tier=resolved_force_tier,
                skip_twitter=resolved_force_tier is None and is_twitter_url,
                allow_external_relays=allow_external_relays,
                allow_unsafe_tier3=allow_unsafe_tier3,
            )
    except Exception as exc:
        return f"ERROR: An unexpected error occurred while scraping {normalized_url}: {str(exc)}"

    if result is None:
        relay_note = ""
        if not allow_external_relays:
            relay_note = (
                f" External relay fallbacks are disabled; set {_EXTERNAL_RELAY_ENV}=1 to enable "
                "Jina/Freedium/archive fallbacks."
            )
        tier3_note = ""
        if not allow_unsafe_tier3:
            tier3_note = (
                f" Tier 3 Nodriver fallback is disabled; set {_UNSAFE_TIER3_ENV}=1 to enable it."
            )
        return (
            f"ERROR: Failed to read website content for {normalized_url}. "
            f"All tiers exhausted (Twitter handler, curl_cffi, Camoufox).{relay_note}{tier3_note}"
        )

    method, content = result
    if not content or len(content.strip()) < 50:
        return f"WARNING: Page loaded but extracted minimal content from: {normalized_url}"

    return _format_scrape_result(normalized_url, method, normalized_mode, content)


if __name__ == "__main__":
    mcp.run()
