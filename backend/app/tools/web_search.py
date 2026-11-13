"""Web search with three interchangeable providers.

SEARCH_PROVIDER=duckduckgo (free, no key) | tavily | serpapi
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from ..core.config import Settings, get_settings
from ..core.errors import ToolError
from ..core.logging import get_logger
from ..core.utils import retry_async
from .base import Tool, ToolContext

log = get_logger("tools.web_search")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = httpx.Timeout(20.0, connect=10.0)

_TAG = re.compile(r"<[^>]+>")
_ANCHOR = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.S | re.I,
)
_SNIPPET = re.compile(
    r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)>',
    re.S | re.I,
)


def _clean(fragment: str) -> str:
    text = _TAG.sub(" ", fragment or "")
    return " ".join(html.unescape(text).split())


def _unwrap(href: str) -> str:
    href = html.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


async def _duckduckgo(query: str, limit: int) -> dict[str, Any]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=headers) as client:
            return await client.get(url)

    response = await retry_async(call, attempts=3, label="duckduckgo", retry_on=(httpx.HTTPError,))
    if response.status_code >= 400:
        raise ToolError(
            f"DuckDuckGo returned HTTP {response.status_code}. "
            "Set SEARCH_PROVIDER=tavily or serpapi with an API key for reliable search."
        )

    anchors = _ANCHOR.findall(response.text)
    snippets = _SNIPPET.findall(response.text)
    results = []
    for index, (href, title_html) in enumerate(anchors[:limit]):
        results.append(
            {
                "title": _clean(title_html) or "(untitled)",
                "url": _unwrap(href),
                "snippet": _clean(snippets[index]) if index < len(snippets) else "",
            }
        )
    if not results:
        return {
            "provider": "duckduckgo",
            "query": query,
            "results": [],
            "note": (
                "No results parsed. DuckDuckGo may be rate-limiting; "
                "configure TAVILY_API_KEY or SERPAPI_API_KEY for reliable search."
            ),
        }
    return {"provider": "duckduckgo", "query": query, "results": results}


async def _tavily(query: str, limit: int, api_key: str) -> dict[str, Any]:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": limit,
        "search_depth": "basic",
        "include_answer": True,
    }

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await client.post("https://api.tavily.com/search", json=payload)

    response = await retry_async(call, attempts=3, label="tavily", retry_on=(httpx.HTTPError,))
    if response.status_code >= 400:
        raise ToolError(f"Tavily returned HTTP {response.status_code}: {response.text[:200]}")
    data = response.json()
    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": " ".join((item.get("content") or "").split())[:500],
        }
        for item in data.get("results", [])[:limit]
    ]
    return {"provider": "tavily", "query": query, "answer": data.get("answer"), "results": results}


async def _serpapi(query: str, limit: int, api_key: str) -> dict[str, Any]:
    params = {"engine": "google", "q": query, "num": limit, "api_key": api_key}

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await client.get("https://serpapi.com/search", params=params)

    response = await retry_async(call, attempts=3, label="serpapi", retry_on=(httpx.HTTPError,))
    if response.status_code >= 400:
        raise ToolError(f"SerpAPI returned HTTP {response.status_code}: {response.text[:200]}")
    data = response.json()
    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": " ".join((item.get("snippet") or "").split())[:500],
        }
        for item in data.get("organic_results", [])[:limit]
    ]
    return {
        "provider": "serpapi",
        "query": query,
        "answer": (data.get("answer_box") or {}).get("answer"),
        "results": results,
    }


async def web_search(ctx: ToolContext, query: str, max_results: int | None = None) -> dict[str, Any]:
    settings: Settings = ctx.settings or get_settings()
    query = (query or "").strip()
    if not query:
        raise ToolError("a search needs a query")

    limit = int(max_results or settings.search_max_results or 5)
    limit = max(1, min(limit, 10))
    provider = (settings.search_provider or "duckduckgo").strip().lower()

    if provider == "tavily" and settings.tavily_api_key:
        return await _tavily(query, limit, settings.tavily_api_key)
    if provider == "serpapi" and settings.serpapi_api_key:
        return await _serpapi(query, limit, settings.serpapi_api_key)
    if provider in ("tavily", "serpapi"):
        log.warning("%s selected but no API key set; falling back to duckduckgo", provider)
    return await _duckduckgo(query, limit)


TOOLS = [
    Tool(
        name="web_search",
        description="Search the web and return titles, URLs and snippets",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
        },
        handler=web_search,
    ),
]
