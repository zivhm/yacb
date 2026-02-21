"""Web tools: search and fetch."""

import html as html_mod
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from core.tools.base import Tool

USER_AGENT = "Mozilla/5.0 (compatible; yacb/0.1)"


def _strip_tags(text: str) -> str:
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html_mod.unescape(text).strip()


def _normalize(text: str) -> str:
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


_PROMPT_INJECTION_PATTERNS = [
    r"ignore (all|any|previous|prior) instructions",
    r"reveal (the )?(system prompt|hidden prompt|developer message)",
    r"do not follow safety",
    r"bypass (security|guardrails|polic(y|ies))",
    r"act as (system|developer|administrator|root)",
]


def _detect_prompt_injection_signals(text: str) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    hits: list[str] = []
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            hits.append(pattern)
    return hits


class WebSearchTool(Tool):
    """Search the web using Tavily."""

    name = "web_search"
    description = "Search the internet using Tavily. Use this whenever you need current information, news, weather, prices, events, or anything you don't already know. Returns titles, URLs, and snippets. Can also include images."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Number of results (1-10)", "minimum": 1, "maximum": 10},
            "include_images": {"type": "boolean", "description": "Include image URLs in results"},
            "topic": {"type": "string", "description": "Search topic", "enum": ["general", "news"]},
        },
        "required": ["query"],
    }

    def __init__(self, max_results: int = 5, api_key: str = "", **kwargs: Any):
        self.max_results = max_results
        self._api_key = api_key

    async def execute(
        self, query: str, count: int | None = None,
        include_images: bool = False, topic: str = "general", **kwargs: Any,
    ) -> str:
        try:
            from tavily import AsyncTavilyClient
        except ModuleNotFoundError:
            return (
                "Error: web search dependency not installed. "
                "Install with: uv sync --extra web"
            )
        except Exception as e:
            return f"Error: {e}"

        try:

            api_key = self._api_key or os.environ.get("TAVILY_API_KEY", "")
            if not api_key:
                return "Error: Tavily API key not configured. Set tools.tavily_api_key in config or TAVILY_API_KEY env var."

            client = AsyncTavilyClient(api_key=api_key)
            n = min(max(count or self.max_results, 1), 10)
            response = await client.search(
                query=query,
                max_results=n,
                include_images=include_images,
                topic=topic,
            )

            results = response.get("results", [])
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if content := item.get("content"):
                    lines.append(f"   {content}")

            images = response.get("images", [])
            if images:
                lines.append("\nImages:")
                for img in images[:5]:
                    if isinstance(img, str):
                        lines.append(f"  {img}")
                    elif isinstance(img, dict):
                        lines.append(f"  {img.get('url', '')}")

            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL."""

    name = "web_fetch"
    description = "Fetch URL and extract readable content."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "max_chars": {"type": "integer", "minimum": 100},
        },
        "required": ["url"],
    }

    def __init__(self, max_chars: int = 50000):
        self._max_chars = max_chars

    async def execute(self, url: str, max_chars: int | None = None, **kwargs: Any) -> str:
        max_chars = max_chars or self._max_chars

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return json.dumps({"error": "Only http/https URLs allowed", "url": url})

        try:
            async with httpx.AsyncClient(follow_redirects=True, max_redirects=5, timeout=30.0) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            if "application/json" in ctype:
                text = json.dumps(r.json(), indent=2)
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                # Prefer readability-lxml when available, but gracefully
                # fall back to plain tag stripping when it's not installed.
                try:
                    from readability import Document
                except ModuleNotFoundError:
                    text = _normalize(_strip_tags(r.text))
                else:
                    doc = Document(r.text)
                    text = _normalize(_strip_tags(doc.summary()))
                    if doc.title():
                        text = f"# {doc.title()}\n\n{text}"
            else:
                text = r.text

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]
            warnings = _detect_prompt_injection_signals(text)

            return json.dumps({
                "url": url, "status": r.status_code,
                "truncated": truncated, "length": len(text), "text": text,
                "security_warnings": warnings,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})
