"""Company profile report via the Tavily Research API.

Docs: https://docs.tavily.com/documentation/api-reference/endpoint/research
"""
import httpx

from app.config import settings
from app.models import ReportInput
from app.quick_report import quick_report
from app.tavily import Tavily, TavilyError

CREDIT_LIMIT = (432, 433)

SECTIONS = [
    ("Company Overview",
     "Brand name and registered legal name (if different), year founded, headquarters city and country, "
     "industry, company size if published, and 2-3 sentences on what the company does."),
    ("Official Website",
     "The official website URL and primary domain, plus any other official domains or country sites."),
    ("Contact Information",
     "Every published phone number with its country code, labelled by purpose (main, sales, support, "
     "toll-free, etc.), and the URL of the contact page."),
    ("Official Email Addresses",
     "Every email address the company publishes, labelled by purpose (general, sales, support, careers, etc.)."),
    ("Company Address",
     "The full headquarters or registered office address (street, city, state, postal code, country), "
     "followed by other office locations."),
    ("Social Media Profiles",
     "Full profile URLs for LinkedIn, X (Twitter), Facebook, Instagram and YouTube, plus any other official accounts."),
    ("Products & Services",
     "The main products, services or solutions, one line each."),
    ("Notes",
     "Only if needed: conflicting information between sources, details you could not verify, and any "
     "similarly named companies you found and excluded."),
]

RULES = [
    "Take every fact from the company's own website first: homepage, Contact, About, footer, Privacy Policy "
    "and Terms pages. Use other sources (official company registries, the company's LinkedIn page, Crunchbase, "
    "reputable news) only to fill gaps, and mark those facts \"(third-party source)\".",
    "Copy phone numbers, email addresses, street addresses and URLs exactly as published. Never guess or "
    "construct them; for example, do not assume an address like info@<domain> exists.",
    "List a social media profile only if the company's website links to it, or it clearly belongs to this "
    "company (same name and it links back to the official website).",
    "If a detail cannot be found, write \"Not publicly listed\" instead of guessing.",
    "Cite every fact.",
]


def build_prompt(inputs: ReportInput) -> str:
    name = inputs.company_name
    domain = inputs.domain
    confidence = inputs.domain_confidence or ("provided" if domain else "none")

    if domain and confidence in ("provided", "high", "medium"):
        intro = (
            f'Research the company "{name}", whose official website is https://{domain} (domain: {domain}). '
            f"Report only on the organisation that owns {domain}. Companies with the same or a similar name "
            f"are different companies; do not use their details."
        )
    elif domain:
        intro = (
            f'Research the company "{name}". Its official website is probably https://{domain}. First confirm '
            f"that this site really belongs to {name}; if it does not, find the company's real official "
            f"website and use that instead. Do not mix in details from similarly named companies."
        )
    else:
        intro = (
            f'Research the company "{name}". First identify its official website and primary domain, then '
            f"build the profile from that website. Do not mix in details from similarly named companies."
        )

    known = []
    if inputs.address:
        known.append(f"location/address: {inputs.address}")
    if inputs.phone:
        known.append(f"phone: {inputs.phone}")

    parts = [intro]
    if known:
        parts.append(
            "The user already has these details for this company. Use them to identify the right company, "
            "and in Notes say whether your sources confirm or contradict each one: " + "; ".join(known) + "."
        )
    if inputs.other_domain and inputs.other_domain != domain:
        parts.append(
            f"A web search for this name also found the website {inputs.other_domain}. If it belongs to the same "
            f"company (for example an older, regional or product site), list it under Official Website as an "
            f"additional site. If it belongs to a different company, do not use it, and say so in Notes."
        )
    if inputs.email:
        parts.append(
            f"The user has the personal work email of someone who works at this company ({inputs.email}). "
            f"Use only its domain to identify the company. It is not an official company email address: "
            f"do not list it under Official Email Addresses and do not search for this person."
        )
    parts.append("")
    parts.append("Write a company profile in Markdown with exactly these section headings (## level), in this order:")
    parts += [f"## {title}: {what}" for title, what in SECTIONS]
    parts.append("")
    parts.append("Rules:")
    parts += [f"- {r}" for r in RULES]
    return "\n".join(parts)


async def research_company(inputs: ReportInput, client: httpx.AsyncClient) -> dict:
    prompt = build_prompt(inputs)
    confident = inputs.domain and (inputs.domain_confidence or "provided") in ("provided", "high", "medium")
    model, note = settings.research_model, None

    async def run(m: str) -> dict:
        return await Tavily(client).research(
            prompt,
            model=m,
            citation_format="numbered",
            output_length=settings.research_length,
            # Soft preference for the official site; other sources are still allowed.
            include_domains=[inputs.domain] if confident else None,
            timeout=settings.research_timeout,
        )

    # Tavily refuses a research job up front when the plan's remaining credits can't cover
    # its worst-case cost. Then try mini, and finally a quick report from Tavily Search.
    data = None
    for m in dict.fromkeys([model, "mini"]):
        try:
            data = await run(m)
            model = m
            break
        except TavilyError as e:
            if e.status not in CREDIT_LIMIT:
                raise
    if data is None:
        quick = await quick_report(inputs, client)
        usage = await Tavily(client).usage()
        left = f" ({usage['used']} of {usage['limit']} plan credits used)" if usage else ""
        return quick | {
            "model": "search",
            "note": "Tavily Research was refused because the plan is near its credit limit" + left
                    + ". This is a quick report from Tavily Search instead; add credits for the full research report.",
            "prompt": prompt,
        }
    if model != settings.research_model:
        note = f"The {settings.research_model} model was refused (credit limit), so mini was used."

    content = data.get("content")
    sources = [
        {"title": s.get("title") or s.get("url"), "url": s.get("url"), "favicon": s.get("favicon")}
        for s in data.get("sources") or []
        if isinstance(s, dict) and s.get("url")
    ]
    return {
        "content": content if isinstance(content, str) else "",
        "sources": sources,
        "model": model,
        "note": note,
        "credits": (data.get("usage") or {}).get("credits"),
        "prompt": prompt,
    }
