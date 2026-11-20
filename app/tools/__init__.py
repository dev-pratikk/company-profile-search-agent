"""Tool registry and runner. Add new verifiers to TOOLS."""
import asyncio
import time

import httpx

from app.config import settings
from app.models import CompanyInput
from app.tools.base import Tool, ToolError, ToolResult
from app.tools.company_profile import CompanyProfile
from app.tools.research_report import ResearchReport

TOOLS: list[Tool] = [
    CompanyProfile(),
    ResearchReport(),
    # DomainActiveCheck(), DomainAgeCheck(), EmailVerifier(), PhoneVerifier(), ...
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


async def _safe_run(tool: Tool, inputs: CompanyInput, client: httpx.AsyncClient) -> ToolResult:
    if not tool.is_configured():
        return tool.result("skipped", "API key not configured in .env.")
    missing = tool.missing_inputs(inputs)
    if missing:
        return tool.result("skipped", f"Needs: {', '.join(missing)}.")

    start = time.perf_counter()
    try:
        res = await tool.run(inputs, client)
    except ToolError as e:
        res = tool.result("error", str(e))
    except httpx.TimeoutException:
        res = tool.result("error", "Request timed out.")
    except httpx.HTTPError as e:
        res = tool.result("error", f"Network error: {e.__class__.__name__}")
    except Exception as e:  # never let one tool break the whole search
        res = tool.result("error", f"Unexpected error: {e}")
    res.duration_ms = int((time.perf_counter() - start) * 1000)
    return res


async def run_tool(tool: Tool, inputs: CompanyInput) -> ToolResult:
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        return await _safe_run(tool, inputs, client)


async def run_all(inputs: CompanyInput) -> list[ToolResult]:
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        return await asyncio.gather(*(_safe_run(t, inputs, client) for t in TOOLS))


def describe_tools() -> list[dict]:
    return [
        {
            "name": t.name,
            "label": t.label,
            "description": t.description,
            "required_inputs": list(t.required_inputs),
            "configured": t.is_configured(),
            "providers": t.providers(),
        }
        for t in TOOLS
    ]
