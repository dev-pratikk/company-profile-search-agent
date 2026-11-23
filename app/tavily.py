"""Async wrapper around the Tavily REST API (Search + Research).

Docs: https://docs.tavily.com/documentation/api-reference
"""
import asyncio
import time

import httpx

from app.config import settings

BASE_URL = "https://api.tavily.com"

ERROR_MESSAGES = {
    400: "Tavily rejected the request (bad parameters).",
    401: "Invalid Tavily API key. Check TAVILY_API_KEY in .env.",
    404: "Tavily research task not found.",
    429: "Tavily rate limit hit. Wait a moment and try again.",
    432: "Tavily plan credit limit exceeded.",
    433: "Tavily pay-as-you-go limit exceeded.",
}


class TavilyError(Exception):
    """A clean, user-readable Tavily error."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


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
        if not settings.tavily_api_key:
            raise TavilyError("TAVILY_API_KEY is not set in .env.")
        self.client = client
        self.headers = {"Authorization": f"Bearer {settings.tavily_api_key}"}

    async def _request(self, method: str, path: str, payload: dict | None = None, ok=(200,)) -> dict:
        try:
            resp = await self.client.request(
                method, f"{BASE_URL}{path}", json=payload, headers=self.headers, timeout=90
            )
        except httpx.TimeoutException as e:
            raise TavilyError("Tavily did not respond in time. Try again.") from e
        except httpx.HTTPError as e:
            raise TavilyError(f"Could not reach Tavily ({e.__class__.__name__}).") from e
        if resp.status_code not in ok:
            msg = ERROR_MESSAGES.get(resp.status_code, f"Tavily returned HTTP {resp.status_code}.")
            detail = _detail(resp)
            if detail and resp.status_code != 401:
                msg += f" ({detail})"
            raise TavilyError(msg, resp.status_code)
        return resp.json()

    async def search(self, query: str, **params) -> dict:
        """POST /search. Any documented parameter can be passed as a keyword."""
        payload = {"query": query[:1500], **{k: v for k, v in params.items() if v is not None}}
        return await self._request("POST", "/search", payload)

    async def usage(self) -> dict | None:
        """GET /usage -> {used, limit} for the plan, or None if unavailable. Costs no credits."""
        try:
            acc = (await self._request("GET", "/usage")).get("account") or {}
        except TavilyError:
            return None
        used, limit = acc.get("plan_usage"), acc.get("plan_limit")
        return {"used": used, "limit": limit, "plan": acc.get("current_plan")} if limit else None

    async def research(self, prompt: str, *, timeout: int = 300, poll: float = 3.0, **params) -> dict:
        """POST /research, then poll GET /research/{id} until it completes.

        Returns {content (markdown), sources [{title, url, favicon}], usage {credits}, ...}.
        """
        payload = {"input": prompt, **{k: v for k, v in params.items() if v is not None}}
        task = await self._request("POST", "/research", payload, ok=(200, 201))
        if task.get("status") == "completed":
            return task
        rid = task.get("request_id")
        if not rid:
            raise TavilyError("Tavily research did not return a task id.")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(poll)
            data = await self._request("GET", f"/research/{rid}?include_usage=true", ok=(200, 202))
            status = data.get("status")
            if status == "completed":
                return data
            if status == "failed":
                raise TavilyError("Tavily research task failed. Try again.")
        raise TavilyError(f"Tavily research did not finish within {timeout}s.")
