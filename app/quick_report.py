"""Fallback report built from Tavily Search, used when Tavily Research is refused
(e.g. the plan does not have enough credits left for a research job).

Three focused "advanced" searches (2 credits each), each asking one question,
preferring pages on the official domain. Tavily's answers become the sections.
"""
import asyncio
import re

import httpx

from app.config import settings
from app.domain import Name, host_of
from app.models import ReportInput
from app.tavily import Tavily

SOCIAL_HOSTS = {
    "linkedin.com": "LinkedIn", "twitter.com": "X (Twitter)", "x.com": "X (Twitter)",
    "facebook.com": "Facebook", "instagram.com": "Instagram", "youtube.com": "YouTube",
}
URL_RE = re.compile(r"https?://[^\s)\]\"'<>,]+", re.I)


# Profile URL shapes per platform (rejects posts, articles, videos, search pages).
PROFILE_RE = {
    "LinkedIn": re.compile(r"^/(company|school|showcase)/[^/?#]+/?$"),
    "X (Twitter)": re.compile(r"^/(?!(?:i|search|intent|share|home|hashtag)/?$)[A-Za-z0-9_]{1,15}/?$"),
    "Facebook": re.compile(r"^/(?!(?:sharer|share|watch|groups|events|fb-answers|pages/?$))[A-Za-z0-9.\-]{3,}/?$"),
    "Instagram": re.compile(r"^/(?!(?:p|reel|explore|stories)/)[A-Za-z0-9_.]{1,30}/?$"),
    "YouTube": re.compile(r"^/(@[A-Za-z0-9_.\-]+|c/[^/]+|channel/[^/]+|user/[^/]+)/?$"),
}


def _social_links(results: list[dict], name: Name) -> dict[str, str]:
    """Social profile URLs seen in the search results whose handle mentions the company name."""
    found: dict[str, str] = {}
    for r in results:
        for url in [r.get("url") or ""] + URL_RE.findall(r.get("content") or ""):
            url = url.rstrip(".;").split("?")[0].split("#")[0]
            host = host_of(url)
            base = next((h for h in SOCIAL_HOSTS if host == h or host.endswith("." + h)), None)
            if not base:
                continue
            platform = SOCIAL_HOSTS[base]
            path = "/" + url.split(host, 1)[-1].lstrip("/")
            handle = path.lower().replace("-", "").replace("_", "").replace(".", "")
            if PROFILE_RE[platform].match(path) and any(t in handle for t in name.strong or name.tokens):
                found.setdefault(platform, url)
    return found


async def quick_report(inputs: ReportInput, client: httpx.AsyncClient) -> dict:
    name, domain = inputs.company_name, inputs.domain
    who = f"{name} ({domain})" if domain else name
    if inputs.address:
        who += f", {inputs.address}"
    prefer = {"include_domains": [domain], "include_domains_mode": "prefer"} if domain else {}
    only = {"include_domains": [domain]} if domain else {}  # restrict to the official site
    common = {"search_depth": "advanced", "include_answer": "advanced", "max_results": 8,
              "include_favicon": True, "include_usage": True}
    if settings.search_country:
        common["country"] = settings.search_country

    tv = Tavily(client)
    questions = [
        ("Company Overview and Products & Services",
         f"What does {who} do? Give its official name, year founded, headquarters, industry, "
         f"and its main products and services.", prefer),
        ("Contact Information, Email and Address",
         f"What are the official phone numbers, email addresses and head office address of {who}? "
         f"List each with its purpose.", only),
        ("Social Media Profiles",
         f"What are the official LinkedIn, X (Twitter), Facebook, Instagram and YouTube pages of {who}? "
         f"Give the full profile URLs.", {}),
    ]
    results = list(await asyncio.gather(*(tv.search(q, **common, **extra) for _, q, extra in questions)))
    if only and not results[1].get("results"):  # official site had nothing: widen the contact search
        results[1] = await tv.search(questions[1][1], **common, **prefer)

    sources: list[dict] = []
    index: dict[str, int] = {}

    def cite(r: dict) -> int:
        url = r["url"]
        if url not in index:
            sources.append({"title": r.get("title") or url, "url": url, "favicon": r.get("favicon")})
            index[url] = len(sources)
        return index[url]

    parts = []
    for (title, _, _), res in zip(questions, results):
        hits = [r for r in res.get("results") or [] if r.get("url")]
        nums = sorted({cite(r) for r in hits[:5]})
        answer = (res.get("answer") or "").strip() or "Not found in search results."
        refs = " " + "".join(f"[{n}]" for n in nums) if nums else ""
        parts.append(f"## {title}\n\n{answer}{refs}")

    social = _social_links(results[2].get("results") or [], Name(name))
    if social:  # real profile URLs found in the results: list them instead of the prose answer
        refs = parts[-1][parts[-1].rfind(" ["):] if parts[-1].endswith("]") else ""
        parts[-1] = "## Social Media Profiles\n\n" + "\n".join(f"- {k}: {v}" for k, v in social.items()) + "\n\n" + refs.strip()
    if domain:
        parts.insert(0, f"## Official Website\n\nhttps://{domain}")

    content = "\n\n".join(parts)
    content += "\n\n### Sources\n\n" + "\n".join(f"[{i}] {s['url']}" for i, s in enumerate(sources, 1))
    credits = sum((r.get("usage") or {}).get("credits") or 0 for r in results) or None
    return {"content": content, "sources": sources, "credits": credits}
