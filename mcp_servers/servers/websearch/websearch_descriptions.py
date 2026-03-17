from mcp_servers.servers.description_format import build_tool_description


SEARCH_WEB_PAGES_DESCRIPTION = build_tool_description(
    purpose="Search the public web with DuckDuckGo and return candidate pages.",
    use_when=(
        "You need current information, recent sources, or relevant URLs before "
        "reading full web content."
    ),
    inputs="query.",
    returns="A list of search results with title, href, and body-snippet fields.",
    notes=(
        "Discovery only. Do not answer from snippets alone. Follow up with "
        "read_website on the best results and prefer authoritative sources."
    ),
)

READ_WEBSITE_DESCRIPTION = build_tool_description(
    purpose="Fetch a webpage and extract its main content as cleaned text or markdown.",
    use_when=(
        "You already have a relevant URL and need the full article, "
        "documentation page, or post content."
    ),
    inputs=(
        "url (required). "
        "mode: 'precision' (default) extracts main content only — best for articles, blogs, and docs; "
        "'full' converts the entire DOM to Markdown — best for product pages, tables, and e-commerce. "
        "force_tier: optional int 1, 2, or 3 to bypass auto-escalation and use a specific fetch method "
        "(1=curl_cffi fast HTTP, 2=Camoufox patched Firefox, 3=Nodriver Chrome CDP)."
    ),
    returns=(
        "The extracted page content prefixed with SOURCE/METHOD/MODE/CHARS metadata "
        "(MODE may include requested/used values when fallback extraction is applied), "
        "or an ERROR/WARNING string if the page is invalid, blocked, or yields very little text."
    ),
    notes=(
        "Prefer URLs returned by search_web_pages. "
        "Twitter/X, Medium, and paywalled news sites (WSJ, NYT, FT) are handled automatically. "
        "Private/internal targets are blocked by safety policy. "
        "If precision mode loses content, retry with mode='full'. "
        "If a page fails, try another result or refine the search query."
    ),
)
