"""Playground-style research report via the Tavily Research API.

Returns a markdown report with numbered citations [1] and a source list.
Docs: https://docs.tavily.com/documentation/api-reference/endpoint/research
"""
import httpx

from app.config import settings
from app.models import CompanyInput
from app.tools.base import Tool, ToolResult
from app.tools.tavily_client import Tavily

SECTIONS = [
    "Official Company Name",
    "Contact Information",
    "Official Email Address",
    "Company Address",
    "Social Media Profiles",
    "Products & Services",
]


def build_prompt(inputs: CompanyInput) -> str:
    who = inputs.company_name
    if inputs.domain:
        who += f" (official website: {inputs.domain})"
    lines = [
        f"Research the company {who}. Provide: " + ", ".join(SECTIONS) + ".",
        "Use exactly these section headings, in this order. Prefer the company's own website and official pages; "
        "label any detail that only comes from a third-party listing. Give full URLs for social media profiles. "
        "Cite every fact.",
    ]
    known = []
    if inputs.email:
        known.append(f"email {inputs.email}")
    if inputs.phone:
        known.append(f"phone {inputs.phone}")
    if inputs.address:
        known.append(f"address {inputs.address}")
    if known:
        lines.append("The user has this on file; confirm or contradict it: " + ", ".join(known) + ".")
    return " ".join(lines)


class ResearchReport(Tool):
    name = "research_report"
    label = "Research Report"
    description = "Playground-style report from Tavily Research, with numbered citations and sources."
    required_inputs = ("company_name",)

    def is_configured(self) -> bool:
        return bool(settings.tavily_api_key) and settings.research_enabled

    async def run(self, inputs: CompanyInput, client: httpx.AsyncClient) -> ToolResult:
        prompt = build_prompt(inputs)
        data = await Tavily(client).research(
            prompt, model=settings.research_model, timeout=settings.research_timeout
        )
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            return self.result("warning", "Research finished but returned no report.", prompt=prompt)
        sources = [
            {"title": s.get("title") or s.get("url"), "url": s.get("url"), "favicon": s.get("favicon")}
            for s in data.get("sources") or []
            if isinstance(s, dict) and s.get("url")
        ]
        return self.result(
            "ok",
            f"Research report ready ({len(sources)} sources).",
            content=content,
            sources=sources,
            model=settings.research_model,
            credits=(data.get("usage") or {}).get("credits"),
            prompt=prompt,
        )
