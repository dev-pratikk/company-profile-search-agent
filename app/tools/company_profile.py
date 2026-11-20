"""Builds an official company profile:
    company name, contact info, official email, address, social profiles,
    products & services, logo -- each value with the source(s) it came from.

Sources, most trusted first:
    1. the company's own website (schema.org data, links, contact/about pages)
    2. The Companies API (company database, looked up by domain)
    3. Tavily web search (only used as a fallback, clearly labelled)
Values found by more than one source are merged and list every source.
"""
import asyncio
import re

import httpx

from app.config import settings
from app.models import CompanyInput
from app.tools import extractors as ex
from app.tools.base import Tool, ToolError, ToolResult
from app.tools.companies_api import CompaniesAPI
from app.tools.tavily_client import Tavily

# Sites that list companies but are never the company's own website.
NOT_OFFICIAL = (
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "wikipedia.org", "wikidata.org", "crunchbase.com", "zaubacorp.com", "tofler.in", "glassdoor.com",
    "glassdoor.co.in", "indeed.com", "ambitionbox.com", "justdial.com", "indiamart.com",
    "tradeindia.com", "bloomberg.com", "zoominfo.com", "dnb.com", "owler.com", "pitchbook.com",
    "tracxn.com", "yelp.com", "bbb.org", "reuters.com", "moneycontrol.com", "economictimes.indiatimes.com",
    "yellowpages.com", "quora.com", "reddit.com", "medium.com", "google.com", "apollo.io", "rocketreach.co",
    "cbinsights.com", "craft.co", "companieshouse.gov.uk", "opencorporates.com", "mca.gov.in",
    "naukri.com", "clutch.co", "g2.com", "trustpilot.com", "amazon.com", "amazon.in", "flipkart.com",
)
FREE_EMAIL = {"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com",
              "icloud.com", "aol.com", "rediffmail.com", "protonmail.com", "proton.me", "zohomail.in"}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

CONTACT_RE = re.compile(r"contact|reach[-_ ]?us|get[-_ ]in[-_ ]touch|locations?|offices?", re.I)
ABOUT_RE = re.compile(r"about|company|who[-_ ]we[-_ ]are", re.I)
PRODUCT_RE = re.compile(r"products?|services?|solutions?|offerings?|platform|what[-_ ]we[-_ ]do|industries", re.I)

PLATFORMS = ("linkedin", "x_twitter", "facebook", "instagram", "youtube")
PLATFORM_WORDS = {"linkedin": "LinkedIn", "x_twitter": "Twitter", "facebook": "Facebook",
                  "instagram": "Instagram", "youtube": "YouTube"}

# Source labels, with trust rank (lower = more trusted).
STRUCTURED = "website structured data"
OFFICIAL = "official website"
COMPANIES = "The Companies API"
WEB = "web search"
USER = "you provided"
RANK = {STRUCTURED: 0, OFFICIAL: 1, COMPANIES: 2, USER: 3, WEB: 4}


# ---------------------------------------------------------------- merging

def phone_key(v: str) -> str:
    d = re.sub(r"\D", "", v)
    return d[-10:] if len(d) >= 8 else ""


def social_key(url: str) -> str:
    u = re.sub(r"^https?://", "", url.lower()).rstrip("/")
    u = re.sub(r"^(www|m|mobile|[a-z]{2})\.", "", u)
    return u.replace("twitter.com/", "x.com/")


class Bucket:
    """Collects values from many sources; identical values are merged."""

    def __init__(self, key=lambda v: v.strip().lower()):
        self.key = key
        self.items: dict[str, dict] = {}

    def add(self, value, via: str, url: str | None = None, **extra):
        if not isinstance(value, str) or not value.strip():
            return
        value = value.strip()
        k = self.key(value)
        if not k:
            return
        it = self.items.setdefault(k, {"value": value, "sources": [], **extra})
        if all(s["via"] != via for s in it["sources"]):
            it["sources"].append({"via": via, "url": url})

    def __bool__(self):
        return bool(self.items)

    def top(self, limit: int) -> list[dict]:
        def rank(it):
            return (min(RANK.get(s["via"], 9) for s in it["sources"]), -len(it["sources"]))
        return sorted(self.items.values(), key=rank)[:limit]


# ---------------------------------------------------------------- helpers

def is_official_candidate(host: str) -> bool:
    return bool(host) and not any(host == d or host.endswith("." + d) for d in NOT_OFFICIAL)


def name_tokens(name: str) -> list[str]:
    stop = {"pvt", "ltd", "private", "limited", "inc", "llc", "llp", "the", "and", "company", "corp", "co"}
    return [t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 3 and t not in stop]


async def fetch_html(client: httpx.AsyncClient, url: str) -> tuple[str | None, str | None]:
    try:
        r = await client.get(url, headers=BROWSER_HEADERS, follow_redirects=True, timeout=15)
        if r.status_code < 400 and "html" in r.headers.get("content-type", ""):
            return str(r.url), r.text
    except httpx.HTTPError:
        pass
    return None, None


def pick_links(links: list[tuple[str, str]], rx: re.Pattern, limit: int) -> list[dict]:
    out: dict[str, str] = {}
    for url, text in links:
        url = url.split("#")[0].split("?")[0].rstrip("/")
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        if (rx.search(path) or rx.search(text)) and url not in out and len(out) < limit:
            out[url] = text or path
    return [{"title": t, "url": u} for u, t in out.items()]


def result_sources(res: dict | None) -> list[dict]:
    return [{"title": r.get("title") or r["url"], "url": r["url"]} for r in (res or {}).get("results", [])]


# ---------------------------------------------------------------- tool

class CompanyProfile(Tool):
    name = "company_profile"
    label = "Company Profile"
    description = "Official name, contact, email, address, social profiles, products & services and logo."
    required_inputs = ("company_name",)

    def is_configured(self) -> bool:
        return bool(settings.tavily_api_key or settings.companies_api_key)

    def providers(self) -> list[dict]:
        return [
            {"name": "Tavily", "configured": bool(settings.tavily_api_key)},
            {"name": "The Companies API", "configured": bool(settings.companies_api_key)},
        ]

    async def find_website(self, tv: Tavily | None, inputs: CompanyInput) -> tuple[str | None, str | None]:
        if inputs.domain:
            return inputs.domain, USER
        if inputs.email:
            dom = inputs.email.split("@")[-1]
            if dom not in FREE_EMAIL:
                return (dom[4:] if dom.startswith("www.") else dom), "from your email"
        if not tv:
            return None, None
        res = await tv.search(f"{inputs.company_name} official website", max_results=8)
        tokens = name_tokens(inputs.company_name)
        candidates = [h for h in (ex.host_of(r["url"]) for r in res.get("results", [])) if is_official_candidate(h)]
        for h in candidates:  # prefer a host containing part of the company name
            if any(t in h for t in tokens):
                return h, WEB
        return (candidates[0], WEB) if candidates else (None, None)

    async def run(self, inputs: CompanyInput, client: httpx.AsyncClient) -> ToolResult:
        tv = Tavily(client) if settings.tavily_api_key else None
        ca = CompaniesAPI(client) if settings.companies_api_key else None
        name = inputs.company_name
        notes: list[str] = []
        errors: list[Exception] = []

        async def safe(label, coro):
            try:
                return await coro
            except (ToolError, httpx.HTTPError) as e:
                errors.append(e)
                notes.append(f"{label} failed: {e or e.__class__.__name__}")
                return None

        website, website_via = await self.find_website(tv, inputs)
        if not website:
            hint = "" if tv else " (Tavily is not configured, so the website can't be searched.)"
            return self.result("warning", "Could not find the official website. Enter the domain and search again." + hint)

        # ---- Step 1: everything that only needs the domain, in parallel.
        api_calls = 0
        tasks = {"home": fetch_html(client, f"https://{website}")}
        if ca:
            tasks["co"] = safe("The Companies API", ca.company(website)); api_calls += 1
        if tv:
            tasks["site"] = safe("Tavily site search", tv.search(
                f"{name} contact us address phone email", include_domains=[website], max_results=5))
            api_calls += 1
        if tv and not settings.research_enabled:  # the research report already answers these
            tasks["prod"] = safe("Tavily products search", tv.search(
                f"What products and services does {name} ({website}) offer?",
                depth="advanced", answer="advanced", max_results=6))
            tasks["contact"] = safe("Tavily contact search", tv.search(
                f"{name} ({website}) official headquarters address, phone number and contact email",
                depth="advanced", answer="advanced", max_results=6))
            api_calls += 2
        done = dict(zip(tasks, await asyncio.gather(*tasks.values())))
        if api_calls and len(errors) == api_calls:
            raise errors[0]  # every API failed -> show the real reason (bad key, no credits...)

        co, site_res, prod_res, contact_res = (done.get(k) for k in ("co", "site", "prod", "contact"))
        if ca and co is None and not any("Companies API" in n for n in notes):
            notes.append(f"The Companies API has no record for {website}.")

        home_url, home_html = done["home"]
        if not home_html:
            home_url, home_html = await fetch_html(client, f"https://www.{website}")
        page = ex.parse_html(home_html, home_url) if home_html else None
        if not page:
            notes.append("The website could not be opened directly (it may block automated visits).")
        home_url = home_url or f"https://{website}"

        # ---- Step 2: read the contact/about pages through Tavily Extract.
        site_links = [(u, t) for u, t in (page["links"] if page else []) if ex.host_of(u) == website]
        contact_pages = pick_links(site_links, CONTACT_RE, 3)
        about_pages = pick_links(site_links, ABOUT_RE, 1)
        pages_md: list[tuple[str, str, list]] = []
        if tv:
            urls = [home_url] + [p["url"] for p in contact_pages + about_pages]
            urls += [r["url"] for r in (site_res or {}).get("results", [])[:3]]
            urls = list(dict.fromkeys(u.split("#")[0] for u in urls))[:6]
            ext = await safe("Tavily extract", tv.extract(urls))
            pages_md = [(r["url"], r.get("raw_content") or "", r.get("images") or [])
                        for r in (ext or {}).get("results", [])]
        if not contact_pages:
            contact_pages = [{"title": r.get("title") or r["url"], "url": r["url"]}
                             for r in (site_res or {}).get("results", []) if CONTACT_RE.search(r["url"])][:3]
        if co and co.get("contact_url") and all(co["contact_url"].rstrip("/") != p["url"] for p in contact_pages):
            contact_pages.append({"title": "Contact", "url": co["contact_url"]})

        org = page["org"] if page else {"emails": [], "phones": [], "addresses": [], "same_as": []}
        co = co or {}
        co_url = None  # API data has no public page to link to

        # ---- Step 3: merge every source, field by field.
        names = Bucket()
        names.add(org.get("legal_name"), STRUCTURED, home_url)
        names.add(org.get("name"), STRUCTURED, home_url)
        names.add(co.get("legal_name"), COMPANIES, co_url)
        names.add(co.get("name"), COMPANIES, co_url)
        names.add(page.get("site_name") if page else None, OFFICIAL, home_url)

        phones = Bucket(phone_key)
        for p in org["phones"]:
            phones.add(p, STRUCTURED, home_url)
        for p, cat in co.get("phones", []):
            phones.add(p, COMPANIES, co_url, label=cat)
        if home_html:
            for p in ex.TEL_RE.findall(home_html):
                phones.add(p, OFFICIAL, home_url)
        for url, md, _ in pages_md:
            for p in ex.find_phones(md):
                phones.add(p, OFFICIAL, url)

        emails = Bucket()
        for e in org["emails"]:
            emails.add(e, STRUCTURED, home_url)
        for e, cat in co.get("emails", []):
            emails.add(e.lower(), COMPANIES, co_url, label=cat)
        if home_html:
            for e in ex.find_emails(home_html):
                emails.add(e, OFFICIAL, home_url)
        for url, md, _ in pages_md:
            for e in ex.find_emails(md):
                emails.add(e, OFFICIAL, url)

        # Web-search fallback, only when nothing official was found.
        web_text = [(r["url"], r.get("content") or "") for r in (contact_res or {}).get("results", [])]
        if not emails:
            for u, t in web_text:
                for e in ex.find_emails(t):
                    emails.add(e, WEB, u)
        if not phones:
            for u, t in web_text:
                for p in ex.find_phones(t):
                    phones.add(p, WEB, u)

        addresses = Bucket(lambda v: re.sub(r"[^a-z0-9]", "", v.lower()))
        for a in org["addresses"]:
            addresses.add(a, STRUCTURED, home_url)
        addresses.add(co.get("address"), COMPANIES, co_url)

        social = {p: Bucket(social_key) for p in PLATFORMS}

        def add_social(urls, via, src):
            for platform, found in ex.find_social(urls).items():
                for u in found:
                    social[platform].add(u, via, src)

        add_social(org["same_as"], STRUCTURED, home_url)
        if page:
            add_social([u for u, _ in page["links"]], OFFICIAL, home_url)
        for url, md, _ in pages_md:
            add_social(ex.find_urls(md), OFFICIAL, url)
        for platform, url in co.get("socials", {}).items():
            social[platform].add(ex.normalize_social(url), COMPANIES, co_url)
        missing = [p for p in PLATFORMS if not social[p]]
        if missing and tv:
            await self._social_web_fallback(tv, name, missing, social, notes)

        logo = self._logo(co, org, page, pages_md, website)

        def mark_email(it):
            it["official"] = ex.same_site("https://" + it["value"].split("@")[-1], website)
            it["matches_input"] = bool(inputs.email) and it["value"].lower() == inputs.email
            return it

        def mark_phone(it):
            it["matches_input"] = bool(inputs.phone) and phone_key(it["value"]) == phone_key(inputs.phone)
            return it

        email_list = sorted((mark_email(e) for e in emails.top(10)), key=lambda e: not e["official"])
        profile = {
            "website": {"url": home_url, "domain": website, "via": website_via, "reachable": bool(home_html)},
            "name": (names.top(1) or [{"value": name, "sources": [{"via": USER, "url": None}]}])[0],
            "legal_name": org.get("legal_name") or co.get("legal_name"),
            "logo": logo,
            "contact": {"phones": [mark_phone(p) for p in phones.top(8)], "pages": contact_pages},
            "emails": email_list,
            "address": {
                "items": addresses.top(4),
                "answer": (contact_res or {}).get("answer"),
                "answer_sources": result_sources(contact_res),
            },
            "social": {p: social[p].top(3) for p in PLATFORMS if social[p]},
            "products": {
                "description": co.get("description") or (page.get("description") if page else None),
                "tagline": co.get("tagline"),
                "industry": co.get("industry"),
                "industries": co.get("industries", [])[:8],
                "answer": (prod_res or {}).get("answer"),
                "answer_sources": result_sources(prod_res),
                "pages": pick_links(site_links, PRODUCT_RE, 12),
            },
            "providers": {"tavily": bool(tv), "companies_api": bool(co)},
            "notes": notes,
        }
        return self._finish(profile)

    # ------------------------------------------------------------ pieces
    @staticmethod
    def _logo(co, org, page, pages_md, website) -> dict:
        cands: list[tuple[str, str]] = []
        if co.get("logo"):
            cands.append((co["logo"], COMPANIES))
        if org.get("logo"):
            cands.append((org["logo"], STRUCTURED))
        if page:
            cands += [(u, OFFICIAL) for u in page["logo_imgs"]]
        for _, _, imgs in pages_md:
            cands += [(u, OFFICIAL) for u in imgs if isinstance(u, str) and "logo" in u.lower()]
        if page:
            cands += [(u, OFFICIAL) for u in page["icons"]]
        cands.append((f"https://www.google.com/s2/favicons?domain={website}&sz=128", "favicon"))
        seen, uniq = set(), []
        for u, via in cands:
            if isinstance(u, str) and u.startswith("http") and u not in seen:
                seen.add(u)
                uniq.append({"url": u, "via": via})
        return {"url": uniq[0]["url"], "candidates": uniq[:6]}

    @staticmethod
    async def _social_web_fallback(tv, name, missing, social, notes):
        words = " ".join(PLATFORM_WORDS[m] for m in missing)
        try:
            res = await tv.search(f"{name} official {words} page", max_results=10)
        except (ToolError, httpx.HTTPError) as e:
            notes.append(f"Social search failed: {e}")
            return
        tokens = name_tokens(name)
        for r in res.get("results", []):
            p = ex.classify_social(r["url"])
            u = ex.normalize_social(r["url"])
            # Only accept profiles whose URL mentions the company name.
            if p in missing and not social[p] and any(t in u.lower() for t in tokens):
                social[p].add(u, WEB, r["url"])

    def _finish(self, profile: dict) -> ToolResult:
        p = profile
        coverage = {
            "Company name": p["name"]["sources"][0]["via"] != USER,
            "Contact": bool(p["contact"]["phones"] or p["contact"]["pages"]),
            "Email": bool(p["emails"]),
            "Address": bool(p["address"]["items"] or p["address"]["answer"]),
            "Social media": bool(p["social"]),
            "Products & services": bool(p["products"]["answer"] or p["products"]["description"] or p["products"]["pages"]),
        }
        p["coverage"] = coverage
        found = sum(coverage.values())
        missing = [k for k, v in coverage.items() if not v]
        summary = f"Found {found} of 6 fields for {p['website']['domain']}"
        summary += f" (missing: {', '.join(missing).lower()})." if missing else "."
        return self.result("ok" if found >= 5 else "warning", summary, **p)
