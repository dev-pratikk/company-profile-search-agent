"""Pure parsing helpers: pull emails, phones, social links, logos and
schema.org data out of HTML / markdown. No network calls here."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------- URLs

URL_RE = re.compile(r"https?://[^\s)\]\"'<>]+", re.I)


def host_of(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, domain: str) -> bool:
    h = host_of(url)
    return h == domain or h.endswith("." + domain)


def find_urls(text: str) -> list[str]:
    return [u.rstrip(".,;") for u in URL_RE.findall(text or "")]


# ---------------------------------------------------------------- emails

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
_BAD_EMAIL_TLDS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
_BAD_EMAIL_DOMAINS = {
    "example.com", "domain.com", "email.com", "yourdomain.com", "company.com", "sentry.io",
    "wixpress.com", "sentry-next.wixpress.com", "test.com",
}


def find_emails(text: str) -> list[str]:
    out = []
    for m in EMAIL_RE.findall(text or ""):
        e = m.lower().strip(".")
        dom = e.split("@", 1)[1]
        if e.endswith(_BAD_EMAIL_TLDS) or dom in _BAD_EMAIL_DOMAINS or dom.endswith(".sentry.io"):
            continue
        if e not in out:
            out.append(e)
    return out


# ---------------------------------------------------------------- phones

TEL_RE = re.compile(r"tel:([+\d][\d\s().-]{6,})", re.I)
PHONE_RE = re.compile(r"(?<![\w/])(\+?\(?\d{1,4}\)?[\s.-]?(?:\(?\d{1,5}\)?[\s.-]?){1,4}\d{2,5})(?![\w/])")
PHONE_HINT = re.compile(r"(phone|tel|call|mobile|mob\.?|contact|fax|whatsapp|toll|helpline|☎|📞)", re.I)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _clean_phone(s: str) -> str | None:
    s = re.sub(r"\s+", " ", s).strip(" .-")
    if s.count(")") > s.count("("):
        s = s.rstrip(")").strip()
    if s.count("(") > s.count(")"):
        s = s.lstrip("(").strip()
    n = len(_digits(s))
    if not 8 <= n <= 15:
        return None
    if re.fullmatch(r"(19|20)\d{2}[-./ ]\d{1,2}[-./ ]\d{1,2}", s):  # looks like a date
        return None
    return s


def find_phones(text: str) -> list[str]:
    """tel: links first (high confidence), then numbers on lines that look like contact lines."""
    found: dict[str, str] = {}

    def add(raw: str):
        p = _clean_phone(raw)
        if p and _digits(p)[-10:] not in found:
            found[_digits(p)[-10:]] = p

    for raw in TEL_RE.findall(text or ""):
        add(raw)
    for line in (text or "").splitlines():
        if PHONE_HINT.search(line) or line.strip().startswith("+"):
            for raw in PHONE_RE.findall(line):
                if raw.startswith("+") or len(_digits(raw)) >= 10:
                    add(raw)
    return list(found.values())


# ---------------------------------------------------------------- social

SOCIAL_PATTERNS = {
    "linkedin": re.compile(r"^https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com/(company|school|showcase|in)/[^/?#\s]+", re.I),
    "x_twitter": re.compile(r"^https?://(www\.|mobile\.)?(twitter|x)\.com/(?!intent|share|home|hashtag|search|i/)[A-Za-z0-9_]{1,30}/?$", re.I),
    "facebook": re.compile(r"^https?://([a-z-]+\.)?facebook\.com/(?!sharer|share|dialog|plugins|tr[/?]|login)[^?#\s]+", re.I),
    "instagram": re.compile(r"^https?://(www\.)?instagram\.com/(?!p/|reel/|explore/|accounts/)[A-Za-z0-9_.]+/?$", re.I),
    "youtube": re.compile(r"^https?://(www\.|m\.)?youtube\.com/(@|c/|channel/|user/)[^/?#\s]+", re.I),
}


def normalize_social(url: str) -> str:
    url = url.split("#")[0].split("?")[0].rstrip("/")
    return re.sub(r"^http://", "https://", url)


def classify_social(url: str) -> str | None:
    u = normalize_social(url)
    for platform, rx in SOCIAL_PATTERNS.items():
        if rx.match(u + ("/" if platform in ("x_twitter", "instagram") else "")) or rx.match(u):
            return platform
    return None


def find_social(urls: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for u in urls:
        p = classify_social(u)
        if p:
            n = normalize_social(u)
            if n not in out.setdefault(p, []):
                out[p].append(n)
    return out


# ---------------------------------------------------------------- HTML page

class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._in_ldjson = False
        self._ld_buf: list[str] = []
        self.meta: dict[str, str] = {}
        self.icons: list[tuple[str, str]] = []  # (rel, href)
        self.links: list[tuple[str, str]] = []  # (href, anchor text)
        self._a_href: str | None = None
        self._a_text: list[str] = []
        self.logo_imgs: list[str] = []
        self.ld_json: list = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "link" and "icon" in a.get("rel", "").lower() and a.get("href"):
            self.icons.append((a["rel"].lower(), a["href"]))
        elif tag == "a" and a.get("href"):
            self._a_href, self._a_text = a["href"], []
        elif tag == "img":
            src = a.get("src") or a.get("data-src") or ""
            blob = " ".join([src, a.get("alt", ""), a.get("class", ""), a.get("id", "")]).lower()
            if src and "logo" in blob:
                self.logo_imgs.append(src)
        elif tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_ldjson, self._ld_buf = True, []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._a_href is not None:
            self.links.append((self._a_href, " ".join("".join(self._a_text).split())))
            self._a_href = None
        elif tag == "script" and self._in_ldjson:
            self._in_ldjson = False
            try:
                self.ld_json.append(json.loads("".join(self._ld_buf)))
            except ValueError:
                pass

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._a_href is not None:
            self._a_text.append(data)
        if self._in_ldjson:
            self._ld_buf.append(data)


ORG_TYPES = {"organization", "corporation", "localbusiness", "company", "onlinebusiness", "ngo",
             "educationalorganization", "professionalservice", "store"}


def _iter_ld(node):
    if isinstance(node, list):
        for n in node:
            yield from _iter_ld(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "publisher", "provider", "brand", "author"):
            if key in node:
                yield from _iter_ld(node[key])


def _ld_types(node: dict) -> set[str]:
    t = node.get("@type", [])
    return {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


def _ld_str(v) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = v.get("url") or v.get("contentUrl") or v.get("@id")
    return v.strip() if isinstance(v, str) and v.strip() else None


def _format_address(a) -> str | None:
    if isinstance(a, str):
        return a.strip() or None
    if isinstance(a, list):
        a = a[0] if a else None
    if not isinstance(a, dict):
        return None
    country = a.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    parts = [a.get("streetAddress"), a.get("addressLocality"), a.get("addressRegion"), a.get("postalCode"), country]
    return ", ".join(str(p).strip() for p in parts if p and str(p).strip()) or None


def organization_from_ld(blocks: list) -> dict:
    """Merge every schema.org Organization-like node into one dict."""
    org: dict = {"emails": [], "phones": [], "addresses": [], "same_as": []}
    for node in _iter_ld(blocks):
        if not (_ld_types(node) & ORG_TYPES):
            continue
        org.setdefault("name", _ld_str(node.get("name")))
        org.setdefault("legal_name", _ld_str(node.get("legalName")))
        if not org.get("logo"):
            org["logo"] = _ld_str(node.get("logo")) or None
        contacts = node.get("contactPoint") or []
        contacts = contacts if isinstance(contacts, list) else [contacts]
        for src in [node, *[c for c in contacts if isinstance(c, dict)]]:
            for e in (src.get("email") if isinstance(src.get("email"), list) else [src.get("email")]):
                if isinstance(e, str) and e.strip():
                    org["emails"].append(e.replace("mailto:", "").strip().lower())
            for t in (src.get("telephone") if isinstance(src.get("telephone"), list) else [src.get("telephone")]):
                if isinstance(t, str) and t.strip():
                    org["phones"].append(t.strip())
        addrs = node.get("address")
        for a in (addrs if isinstance(addrs, list) else [addrs]):
            f = _format_address(a)
            if f:
                org["addresses"].append(f)
        same = node.get("sameAs") or []
        org["same_as"] += [s for s in (same if isinstance(same, list) else [same]) if isinstance(s, str)]
    return org


def parse_html(html: str, base_url: str) -> dict:
    p = _PageParser()
    try:
        p.feed(html)
    except Exception:
        pass
    abs_ = lambda u: urljoin(base_url, u.strip())
    links = [(abs_(h), t) for h, t in p.links if not h.lower().startswith(("javascript:", "#"))]
    icons = sorted(p.icons, key=lambda x: (0 if "apple-touch" in x[0] else 1))
    return {
        "title": " ".join(p.title.split()),
        "site_name": p.meta.get("og:site_name") or p.meta.get("application-name"),
        "og_image": abs_(p.meta["og:image"]) if p.meta.get("og:image") else None,
        "description": p.meta.get("og:description") or p.meta.get("description"),
        "icons": [abs_(h) for _, h in icons],
        "logo_imgs": [abs_(s) for s in p.logo_imgs if not s.startswith("data:")],
        "links": links,
        "org": organization_from_ld(p.ld_json),
    }
