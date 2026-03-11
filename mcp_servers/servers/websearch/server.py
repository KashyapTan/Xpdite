from mcp.server.fastmcp import FastMCP
from ddgs import DDGS
from typing import Any, Dict, List
import asyncio
import os
import re
import random
from contextlib import redirect_stdout, redirect_stderr
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, CacheMode
from mcp_servers.servers.websearch.websearch_descriptions import READ_WEBSITE_DESCRIPTION, SEARCH_WEB_PAGES_DESCRIPTION

mcp = FastMCP("Web Search Tools")

# Module-level devnull for stdout/stderr suppression during tool execution.
# Opened once to avoid per-call file handle churn.
_DEVNULL = open(os.devnull, "w")

# A list of modern, common User-Agents to rotate
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
]

def clean_markdown(md_text: str) -> str:
    """
    Strips Markdown links and images to return pure text.
    """
    if not md_text:
        return ""
    # Remove images
    md_text = re.sub(r'!\[.*?\]\(.*?\)', '', md_text)
    # Remove links, keep text
    md_text = re.sub(r'\[([^\]]*)\]\(.*?\)', r'\1', md_text)
    # Clean up excessive newlines
    md_text = re.sub(r'\n{3,}', '\n\n', md_text)
    return md_text.strip()

# ------------------------------------------------------------------
# 1. Fetch website urls tool
# ------------------------------------------------------------------
@mcp.tool(description=SEARCH_WEB_PAGES_DESCRIPTION)
def search_web_pages(query: str) -> List[Dict[str, Any]]:
    try:
        with redirect_stdout(_DEVNULL), redirect_stderr(_DEVNULL):
            # DDGS().text() returns search results
            results = DDGS().text(
                query=query,
                region='wt-wt',
                safesearch='off',
                max_results=10
            )

            # Convert iterator/generator to list for JSON serialization
            results_list = list(results)

        # Validate results
        if not results_list:
            return [{"error": "No results found", "query": query}]

        return results_list

    except Exception as e:
        return [{"error": f"Search failed: {str(e)}", "query": query}]

# ------------------------------------------------------------------
# 2. Read website content tool
# ------------------------------------------------------------------
@mcp.tool(description=READ_WEBSITE_DESCRIPTION)
async def read_website(url: str) -> str:
    # 
    # Validate URL
    if not url.startswith(('http://', 'https://')):
        return f"ERROR: Invalid URL: {url}. URL must start with http:// or https://"
    
    # --- 1. ENHANCED BROWSER CONFIG ---
    # enable_stealth=True masks 'navigator.webdriver' and other bot signatures
    browser_config = BrowserConfig(
        headless=True,
        enable_stealth=True,
        verbose=False,
        headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/"  # Makes it look like you came from a search
        },
        # Disables the "AutomationControlled" flag in Blink browsers
        extra_args=["--disable-blink-features=AutomationControlled"]
    )
    
    # --- 2. NOISE REDUCTION ---
    # Exclude common navigation and non-content elements
    noise_selector = [
        '.nav', '.navbar', '.menu', '.sidebar', '.footer', '.header',
        '#nav', '#header', '#footer', '.topbar', '.navigation',
        '.ad-container', '.social-share', '.cookie-banner', '.modal'
    ]
    
    # --- 3. RANDOMIZED HUMAN TIMING ---
    # Random wait between 1-3 seconds to break rhythmic detection patterns
    random_wait = random.uniform(1.0, 3.0)
    
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        verbose=False,
        page_timeout=30000,
        excluded_selector=", ".join(noise_selector),
        excluded_tags=['nav', 'header', 'footer', 'aside', 'form', 'svg', 'noscript', 'script', 'style'],
        # Wait for the page to be idle (all network requests finished)
        js_code=f"await new Promise(r => setTimeout(r, {random_wait * 1000}));"
    )
    
    try:
        # Safety net: redirect stdout/stderr to devnull during crawl to catch
        # any stray print() calls from dependencies. Primary defense is
        # verbose=False on BrowserConfig + CrawlerRunConfig.
        with redirect_stdout(_DEVNULL), redirect_stderr(_DEVNULL):
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await asyncio.wait_for(
                    crawler.arun(url=url, config=run_config),
                    timeout=45.0,
                )

        if result.success:
            cleaned_content = clean_markdown(result.markdown)
            
            # Check if we got any content
            if not cleaned_content or len(cleaned_content.strip()) < 50:
                return f"WARNING: Page loaded but extracted minimal content from: {url}"
                
            return cleaned_content
        else:
            # Log specific status codes and errors
            error_msg = f"ERROR: Failed to crawl: {url}\n"
            if hasattr(result, 'status_code'):
                error_msg += f"Status Code: {result.status_code}\n"
            if hasattr(result, 'error_message') and result.error_message:
                error_msg += f"Error: {result.error_message}"
            return error_msg

    except asyncio.TimeoutError:
        return f"ERROR: Crawl timed out after 45 seconds for {url}. The page may be too slow or unresponsive."
    except Exception as e:
        return f"ERROR: An unexpected error occurred while crawling {url}: {str(e)}"

# Add this if running the server directly
if __name__ == "__main__":
    mcp.run()