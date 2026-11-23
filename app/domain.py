"""Find a company's official website / domain with Tavily Search.

Pass 1 - two searches run in parallel:
  1. "What is the official website of <name>?"  (advanced depth + LLM answer)
  2. "<name> company official site"            (basic depth, plain web ranking)
Pass 2 - only when pass 1 finds nothing convincing ("did you mean"):
  the same question for spelling variants of the name, e.g. "QuantaReality" ->
  "Quanta Realty", "Quanta Reality" (Google autocorrects silently; Tavily doesn't).

Directory, registry, social and news sites are excluded. Every remaining domain
gets a score from several independent signals, and the best one wins:
  - the domain label matches the company name / its acronym / a near spelling
  - Tavily's answer names the domain
  - the result is a homepage, ranks high, and its title contains the name
  - the domain shows up in several searches / several times
Pages that are merely *about* the company (domain unrelated to the name, not
named by any answer) are never picked.
"""
import asyncio
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models import CompanyInput
from app.tavily import Tavily, TavilyError

# Sites that list companies but are never the company's own website.
NOT_OFFICIAL = {
    # social / communities
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
    "pinterest.com", "reddit.com", "quora.com", "medium.com", "threads.net", "t.me", "whatsapp.com",
    # encyclopedias / search / app stores / maps
    "wikipedia.org", "wikimedia.org", "wikidata.org", "britannica.com", "google.com", "bing.com",
    "apple.com", "play.google.com", "apps.apple.com", "maps.google.com",
    # company databases / directories / reviews
    "crunchbase.com", "zoominfo.com", "dnb.com", "owler.com", "pitchbook.com", "cbinsights.com", "tracxn.com",
    "craft.co", "opencorporates.com", "bloomberg.com", "rocketreach.co", "apollo.io", "signalhire.com",
    "leadiq.com", "lusha.com", "contactout.com", "datanyze.com", "kona.com", "growjo.com", "comparably.com",
    "glassdoor.com", "glassdoor.co.in", "indeed.com", "ambitionbox.com", "naukri.com", "monster.com",
    "trustpilot.com", "g2.com", "capterra.com", "getapp.com", "softwareadvice.com", "clutch.co",
    "goodfirms.co", "yelp.com", "bbb.org", "yellowpages.com", "manta.com", "bizapedia.com", "buzzfile.com",
    "justdial.com", "indiamart.com", "tradeindia.com", "sulekha.com", "zaubacorp.com", "tofler.in",
    "thecompanycheck.com", "instafinancials.com", "falconebiz.com", "companiesinn.com", "cleartax.in",
    "vakilsearch.com", "economictimes.indiatimes.com", "moneycontrol.com", "screener.in",
    "find-and-update.company-information.service.gov.uk", "endole.co.uk", "companieshouse.gov.uk",
    "allbiz.com", "kompass.com", "europages.com", "made-in-china.com", "alibaba.com", "visualvisitor.com",
    # trademark / patent registries
    "trademarkia.com", "justia.com", "quickcompany.in", "trademarking.in", "corpbiz.io",
    # property portals (they list real-estate developers)
    "squareyards.com", "99acres.com", "magicbricks.com", "housing.com", "nobroker.in", "zoperty360.com",
    "thepropertist.com", "commonfloor.com", "makaan.com", "proptiger.com", "propertywala.com",
    # shops / media / news / publishing
    "amazon.com", "amazon.in", "amazon.co.uk", "flipkart.com", "spotify.com", "goodreads.com",
    "forbes.com", "reuters.com", "businesswire.com", "prnewswire.com", "globenewswire.com",
    "techcrunch.com", "yourstory.com", "inc42.com", "livemint.com", "thehindu.com", "ndtv.com",
    "timesofindia.indiatimes.com", "indiatimes.com", "cnbc.com", "wsj.com", "nytimes.com",
    "github.com", "tavily.com", "blogspot.com", "wordpress.com", "substack.com", "scribd.com", "slideshare.net",
}

FREE_EMAIL = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com", "icloud.com",
    "aol.com", "proton.me", "protonmail.com", "rediffmail.com", "zoho.com", "gmx.com", "mail.com",
}

LEGAL_WORDS = {
    "pvt", "private", "ltd", "limited", "inc", "incorporated", "llc", "llp", "plc", "corp", "corporation",
    "co", "company", "gmbh", "ag", "sa", "bv", "nv", "pte", "pty", "the", "and", "of", "srl", "spa", "oy",
}
GENERIC_WORDS = {
    "technologies", "technology", "tech", "solutions", "solution", "services", "service", "systems",
    "software", "group", "global", "international", "india", "consulting", "consultancy", "enterprises",
    "enterprise", "industries", "labs", "digital", "infotech", "infosystems", "ventures", "holdings",
    "networks", "media", "logistics", "foods", "pharma", "healthcare", "capital", "partners",
}
# Frequent misspellings in company names -> usual spelling (for the "did you mean" pass).
COMMON_FIXES = {
    "reality": "realty", "realities": "realty", "realtys": "realty",
    "tecnologies": "technologies", "technolgies": "technologies", "technologis": "technologies",
    "infratec": "infratech", "bulders": "builders", "devlopers": "developers", "constructions": "construction",
}
SECOND_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu", "ltd", "plc", "gen", "firm", "ind", "biz", "info", "or", "ne"}
DOMAIN_RE = re.compile(r"\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})\b", re.I)
CONFIDENCE_ORDER = ["none", "low", "medium", "high"]


# ------------------------------------------------------------------ helpers

def host_of(url: str) -> str:
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def registrable(host: str) -> str:
    """careers.example.co.in -> example.co.in"""
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def label_of(domain: str) -> str:
    return domain.split(".")[0].replace("-", "")


def split_camel(name: str) -> str:
    """'QuantaReality' -> 'Quanta Reality' (acronyms like 'TCS' stay intact)."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def spelling_variants(name: str) -> list[str]:
    """Other spellings to try when the name as typed finds nothing."""
    split = split_camel(name)
    def fix(w: str) -> str:
        f = COMMON_FIXES.get(w.lower())
        return (f.capitalize() if w[:1].isupper() else f) if f else w

    fixed = " ".join(fix(w) for w in split.split())
    out: list[str] = []
    for v in (fixed, split):
        if v.lower() != name.lower() and v not in out:
            out.append(v)
    return out


class Name:
    """Pre-computed forms of the company name used for matching domains."""

    def __init__(self, name: str):
        self.text = name
        words = re.findall(r"[a-z0-9]+", split_camel(name).lower().replace("&", " and "))
        self.tokens = [w for w in words if w not in LEGAL_WORDS] or words
        self.strong = [w for w in self.tokens if w not in GENERIC_WORDS and len(w) >= 3]
        self.compact = "".join(self.tokens)                # tataconsultancyservices
        self.compact_strong = "".join(self.strong)         # tataconsultancy
        self.acronym = "".join(w[0] for w in self.tokens) if len(self.tokens) >= 2 else ""  # tcs
        self.phrase = " ".join(self.tokens)

    def label_score(self, label: str) -> int:
        if not label:
            return 0
        if label in (self.compact, self.compact_strong):
            return 60
        if self.acronym and label == self.acronym:
            return 50
        forms = [f for f in (self.compact, self.compact_strong) if f]
        ratio = max((SequenceMatcher(None, label, f).ratio() for f in forms), default=0) if len(label) >= 5 else 0
        if ratio >= 0.9:  # one or two letters off: typo, realty/reality
            return 50
        if len(label) >= 4 and (label.startswith(self.compact_strong or self.compact)
                                or (self.compact.startswith(label) and len(label) >= len(self.compact) // 2)):
            return 40
        if ratio >= 0.8:
            return 30
        if any(len(t) >= 4 and t in label for t in self.strong):
            return 25
        return 0

    def is_named(self, domain: str) -> bool:
        """True when the domain itself is the company's name (e.g. searching 'LinkedIn')."""
        return self.label_score(label_of(domain)) >= 50


def is_directory(domain: str, host: str) -> bool:
    if any(host == d or host.endswith("." + d) for d in NOT_OFFICIAL) or domain in NOT_OFFICIAL:
        return True
    parts = host.split(".")
    return "gov" in parts or "nic" in parts or "mil" in parts


def is_homepage(url: str) -> bool:
    path = urlparse(url).path.strip("/").lower()
    return path in ("", "en", "en-us", "en-in", "en-gb", "home", "index.html", "index.php")


def answer_domains(answer: str | None) -> set[str]:
    return {registrable(host_of(m)) for m in DOMAIN_RE.findall(answer or "") if "." in m}


def exclude_for(names: list["Name"]) -> list[str]:
    """Blocklist for Tavily, minus any site that *is* the company (searching 'LinkedIn')."""
    return sorted(d for d in NOT_OFFICIAL if not any(n.is_named(d) for n in names))[:150]


# ------------------------------------------------------------------ scoring

def _rank(names: list[Name], result_sets: list[list[dict]], answers: list[str | None], email_domain: str | None):
    """Score every domain seen in the results. Returns (scored [(score, cand)], domains named by answers)."""
    from_answer: set[str] = set().union(*(answer_domains(a) for a in answers))

    def name_score(domain: str) -> int:
        return max(n.label_score(label_of(domain)) for n in names)

    cands: dict[str, dict] = {}

    def candidate(domain: str) -> dict:
        return cands.setdefault(domain, {
            "domain": domain, "url": None, "title": None, "favicon": None,
            "best": 0, "hits": 0, "queries": set(), "home": False, "title_match": False,
        })

    for qi, results in enumerate(result_sets):
        for i, r in enumerate(results):
            url = r.get("url") or ""
            host = host_of(url)
            if not host:
                continue
            dom = registrable(host)
            if is_directory(dom, host) and not any(n.is_named(dom) for n in names):
                continue
            c = candidate(dom)
            title = re.sub(r"[^a-z0-9]+", " ", (r.get("title") or "").lower())
            home = host == dom and is_homepage(url)  # host_of() already dropped "www."
            s = max(0, 10 - i) + float(r.get("score") or 0) * 10
            s += 10 if home else 0
            if any(n.phrase and n.phrase in title for n in names):
                s += 10
                c["title_match"] = True
            elif any(t in title for n in names for t in n.strong):
                s += 4
            c["best"] = max(c["best"], s)
            c["hits"] += 1
            c["queries"].add(qi)
            if home and not c["home"]:
                c["home"], c["url"], c["title"] = True, url, r.get("title")
            c["url"] = c["url"] or url
            c["title"] = c["title"] or r.get("title")
            c["favicon"] = c["favicon"] or r.get("favicon")

    for d in from_answer:  # an answer may name a domain the result lists missed
        if d in cands or (name_score(d) >= 25 and not is_directory(d, d)):
            candidate(d)
    if email_domain:
        candidate(email_domain)

    scored = []
    for d, c in cands.items():
        named = name_score(d)
        # Domain unrelated to the name, named by no answer, and not a homepage titled with the
        # company name: that's a page *about* the company (a trademark filing, a blog), skip it.
        if not named and d not in from_answer and d != email_domain and not (c["home"] and c["title_match"]):
            continue
        score = c["best"] + named
        score += min(15, 5 * (c["hits"] - 1)) + (10 if len(c["queries"]) >= 2 else 0)
        if d in from_answer:
            score += 40
        if d == email_domain:
            score += 50
        c["named"] = named
        scored.append((round(score, 1), c))
    scored.sort(key=lambda x: -x[0])
    return scored, from_answer


def _confidence(scored, from_answer, email_domain) -> tuple[str, bool]:
    if not scored:
        return "none", False
    top_score, top = scored[0]
    gap = top_score - (scored[1][0] if len(scored) > 1 else 0)
    named, in_answer = top["named"] > 0, top["domain"] in from_answer
    if top["domain"] == email_domain or (top_score >= 100 and (gap >= 20 or in_answer) and named):
        confidence = "high"
    elif top_score >= 60 and (named or in_answer) and (gap >= 10 or in_answer):
        confidence = "medium"
    else:
        confidence = "low"
    # Several look-alike domains close to the winner = several companies share this name.
    ambiguous = top["domain"] != email_domain and sum(1 for s, _ in scored[1:] if top_score - s <= 40) >= 3
    if ambiguous and confidence == "high":
        confidence = "medium"
    return confidence, ambiguous


# ------------------------------------------------------------------ main

async def find_official_website(inputs: CompanyInput, client: httpx.AsyncClient) -> dict:
    """Return {domain, url, title, favicon, confidence, via, matched_name, answer, candidates, search_site, ...}.

    - Website entered        -> that website (no search).
    - Contact email entered  -> the email's domain is the primary website (people's work emails are on the
                                company's real domain), and the website found by search is returned as
                                `search_site` when it differs.
    - Neither                -> the website found by search.
    """
    if inputs.domain:
        d = inputs.domain
        return _site(d, f"https://{d}", None, None, "provided", "you provided", None, [])

    email_domain = None
    if inputs.email and "@" in inputs.email:
        e = inputs.email.split("@")[-1]
        if e not in FREE_EMAIL:
            email_domain = registrable(host_of(e))

    if not email_domain:
        return await _search_website(inputs, client)

    try:
        found = await _search_website(inputs, client)
    except TavilyError as e:  # search failed (e.g. no credits): the email domain still answers it
        found = _site(None, None, None, None, "none", "search", None, [])
        found["search_error"] = str(e)

    # Reuse what the search knows about the email domain (homepage URL, title, icon) if it saw it.
    same = found if found["domain"] == email_domain else next(
        (c for c in found["candidates"] if c["domain"] == email_domain), None)
    known_url = (same or {}).get("url")
    site = _site(
        email_domain,
        known_url if known_url and is_homepage(known_url) else f"https://{email_domain}",
        (same or {}).get("title"), (same or {}).get("favicon"),
        "high", "contact email", found["answer"],
        [c for c in found["candidates"] if c["domain"] != email_domain],
        matched_name=found["matched_name"],
    )
    if found["domain"] and found["domain"] != email_domain:
        site["search_site"] = {k: found[k] for k in ("domain", "url", "title", "favicon", "confidence")}
    site["search_agrees"] = found["domain"] == email_domain
    if found.get("search_error"):
        site["search_error"] = found["search_error"]
    return site


async def _search_website(inputs: CompanyInput, client: httpx.AsyncClient) -> dict:
    """Find the official website from the company name (and location) with Tavily Search."""
    # The user's location always goes in the query text. The default country (TAVILY_COUNTRY) is a
    # ranking boost on both searches, and is written into the plain web search only: like Google
    # localizing, it surfaces local companies ("Quantum Realty" -> the Indian one), while the
    # question-style search stays unbiased so small companies aren't drowned out.
    hint = f" ({inputs.address})" if inputs.address else ""
    local = hint or (f" {settings.search_country.title()}" if settings.search_country else "")
    geo = {"country": settings.search_country} if settings.search_country else {}
    tv = Tavily(client)

    def ask(company: str, names: list[Name], boost: bool = True):
        return tv.search(f"What is the official website of the company {company}{hint}?",
                         search_depth="advanced", include_answer="advanced", max_results=10,
                         include_favicon=True, exclude_domains=exclude_for(names), **(geo if boost else {}))

    # Pass 1: the name as typed.
    names = [Name(inputs.company_name)]
    res = await asyncio.gather(
        ask(inputs.company_name, names),
        tv.search(f"{inputs.company_name}{local} company official site", search_depth="basic", max_results=10,
                  include_favicon=True, exclude_domains=exclude_for(names), **geo),
    )
    result_sets = [r.get("results") or [] for r in res]
    answers = [res[0].get("answer")]
    scored, from_answer = _rank(names, result_sets, answers, None)
    confidence, ambiguous = _confidence(scored, from_answer, None)
    matched_name = None

    # Pass 2 ("did you mean"): nothing convincing -> try spelling variants, like Google's autocorrect.
    variants = spelling_variants(inputs.company_name)[:2]
    if confidence in ("none", "low") and variants:
        v_names = [Name(v) for v in variants]
        all_names = names + v_names
        # No country boost here: pass 1 already had it, and it can bury small companies.
        extra = await asyncio.gather(*(ask(v, all_names, boost=False) for v in variants))
        scored2, from_answer2 = _rank(all_names, result_sets + [r.get("results") or [] for r in extra],
                                      answers + [r.get("answer") for r in extra], None)
        conf2, amb2 = _confidence(scored2, from_answer2, None)
        if scored2 and CONFIDENCE_ORDER.index(conf2) > CONFIDENCE_ORDER.index(confidence):
            scored, from_answer, ambiguous = scored2, from_answer2, amb2
            answers += [r.get("answer") for r in extra]
            top_label = label_of(scored[0][1]["domain"])
            best = max(v_names, key=lambda n: n.label_score(top_label))
            if best.label_score(top_label) > names[0].label_score(top_label):
                matched_name = best.text
            # A corrected spelling is a guess about what the user meant: never claim "high".
            confidence = "medium" if conf2 == "high" and matched_name else conf2

    answer = next((a for a in reversed(answers) if a), None)
    if not scored:
        return _site(None, None, None, None, "none", "search", answer, [])

    top_score, top = scored[0]
    alternatives = [
        {"domain": c["domain"], "url": c["url"] or f"https://{c['domain']}", "title": c["title"],
         "favicon": c["favicon"], "score": s}
        for s, c in scored[1:6]
    ]
    url = top["url"] if top["home"] else f"https://{top['domain']}"
    return _site(top["domain"], url, top["title"], top["favicon"], confidence, "search", answer, alternatives,
                 top_score, ambiguous, matched_name)


def _site(domain, url, title, favicon, confidence, via, answer, candidates, score=None, ambiguous=False,
          matched_name=None) -> dict:
    return {
        "domain": domain, "url": url, "title": title, "favicon": favicon, "confidence": confidence,
        "via": via, "score": score, "ambiguous": ambiguous, "matched_name": matched_name,
        "answer": answer, "candidates": candidates,
    }
