"""Client for The Companies API (https://www.thecompaniesapi.com).

GET https://api.thecompaniesapi.com/v2/companies/{domain}
Header: Authorization: Basic <token>
Unknown domain -> empty object (no credits charged).
"""
import httpx

from app.config import settings
from app.tools.base import ToolError

BASE_URL = "https://api.thecompaniesapi.com/v2"

ERROR_MESSAGES = {
    400: "The Companies API rejected the request.",
    401: "Invalid Companies API token. Check COMPANIES_API_KEY in .env.",
    402: "The Companies API: no credits remaining.",
    403: "The Companies API token has no permission for this request.",
    429: "The Companies API rate limit hit. Try again shortly.",
}

# Their social keys -> our platform keys
SOCIAL_MAP = {"linkedin": "linkedin", "twitter": "x_twitter", "facebook": "facebook",
              "instagram": "instagram", "youtube": "youtube"}


def _dig(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _first(v):
    return (v[0] if v else None) if isinstance(v, list) else v


def _contact_values(items) -> list[tuple[str, str | None]]:
    out = []
    for x in items or []:
        if isinstance(x, dict) and x.get("value"):
            out.append((str(x["value"]).strip(), x.get("category")))
        elif isinstance(x, str) and x.strip():
            out.append((x.strip(), None))
    return out


def parse_company(c: dict) -> dict:
    """Flatten the fields we use from the CompanyV2 object."""
    about = c.get("about") or {}
    hq = _dig(c, "locations", "headquarters") or {}
    address = _dig(hq, "address", "raw")
    if not address:
        parts = [_dig(hq, k, "name") for k in ("city", "state", "country")]
        address = ", ".join(p for p in parts if p) or None

    phones = _contact_values(_dig(c, "contacts", "phones"))
    phones += _contact_values(_dig(c, "contacts", "lines"))
    phones += [(v, "whatsapp") for v, _ in _contact_values(_dig(c, "contacts", "whatsapps"))]

    return {
        "name": about.get("name"),
        "legal_name": about.get("nameLegal"),
        "industry": about.get("industry"),
        "industries": about.get("industries") or [],
        "description": _dig(c, "descriptions", "primary"),
        "tagline": _dig(c, "descriptions", "tagline"),
        "logo": _dig(c, "assets", "logoSquare", "src"),
        "website": _first(_dig(c, "urls", "website")),
        "contact_url": _first(_dig(c, "urls", "contact")),
        "emails": _contact_values(_dig(c, "contacts", "emails")),
        "phones": phones,
        "address": address,
        "socials": {
            ours: url
            for theirs, ours in SOCIAL_MAP.items()
            if isinstance(url := _dig(c, "socials", theirs, "url"), str) and url
        },
    }


class CompaniesAPI:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.headers = {"Authorization": f"Basic {settings.companies_api_key}"}

    async def company(self, domain: str) -> dict | None:
        """Returns the parsed company, or None when they have no record."""
        resp = await self.client.get(f"{BASE_URL}/companies/{domain}", headers=self.headers, timeout=30)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            msg = ERROR_MESSAGES.get(resp.status_code, f"The Companies API returned HTTP {resp.status_code}.")
            try:
                detail = resp.json().get("error", {}).get("message")
                if detail and resp.status_code not in (401, 402):
                    msg += f" ({detail})"
            except ValueError:
                pass
            raise ToolError(msg)
        data = resp.json() or {}
        if isinstance(data.get("company"), dict):  # tolerate a wrapped response
            data = data["company"]
        if not data or not (data.get("about") or data.get("domain")):
            return None
        return parse_company(data)
