"""Thin async wrapper around the Tavily REST API (search, extract, research).

Docs: https://docs.tavily.com/documentation/api-reference
"""
import asyncio
import time

import httpx

from app.config import settings
from app.tools.base import ToolError

BASE_URL = "https://api.tavily.com"

ERROR_MESSAGES = {
    400: "Tavily rejected the request (bad parameters).",
    401: "Invalid Tavily API key. Check TAVILY_API_KEY in .env.",
    404: "Tavily task not found.",
    429: "Tavily rate limit hit. Wait a moment and try again.",
    432: "Tavily plan credit limit exceeded.",
    433: "Tavily pay-as-you-go limit exceeded.",
}


def _detail(resp: httpx.Response) -> str | None:
    try:
        d = resp.json().get("detail")
    except (ValueError, AttributeError):
        return None
    if isinstance(d, dict):
        return d.get("error")
    return d if isinstance(d, str) else None


class Tavily:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.headers = {"Authorization": f"Bearer {settings.tavily_api_key}"}

    async def _request(self, method: str, path: str, payload: dict | None = None, ok=(200,)) -> dict:
        resp = await self.client.request(method, f"{BASE_URL}{path}", json=payload, headers=self.headers, timeout=60)
        if resp.status_code not in ok:
            msg = ERROR_MESSAGES.get(resp.status_code, f"Tavily returned HTTP {resp.status_code}.")
            detail = _detail(resp)
            if detail and resp.status_code != 401:
                msg += f" ({detail})"
            raise ToolError(msg)
        return resp.json()

    async def search(
        self,
        query: str,
        *,
        depth: str = "basic",
        max_results: int = 5,
        answer: bool | str = False,
        include_domains: list[str] | None = None,
    ) -> dict:
        payload = {
            "query": query[:400],
            "search_depth": depth,
            "max_results": max_results,
            "include_answer": answer,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        return await self._request("POST", "/search", payload)

    async def extract(self, urls: list[str], *, depth: str = "basic") -> dict:
        return await self._request(
            "POST", "/extract",
            {"urls": urls[:20], "extract_depth": depth, "format": "markdown", "include_images": True},
        )

    async def research(self, prompt: str, *, model: str = "mini", timeout: int = 300, poll: float = 3.0) -> dict:
        """Start a research task and poll until it completes.
        Returns {content (markdown), sources [{title,url,favicon}], usage {credits}, ...}."""
        task = await self._request(
            "POST", "/research",
            {"input": prompt, "model": model, "citation_format": "numbered"},
            ok=(200, 201),
        )
        if task.get("status") == "completed":
            return task
        rid = task.get("request_id")
        if not rid:
            raise ToolError("Tavily research did not return a task id.")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(poll)
            data = await self._request("GET", f"/research/{rid}?include_usage=true", ok=(200, 202))
            status = data.get("status")
            if status == "completed":
                return data
            if status == "failed":
                raise ToolError("Tavily research task failed. Try again.")
        raise ToolError(f"Tavily research did not finish within {timeout}s.")
