# Company Profile Search Agent

Search a company by name (optionally domain, email, phone, address) and get its official profile, with a source for every value.

## Run

1. Put your keys in `.env` (see `.env.example`): `TAVILY_API_KEY` and `COMPANIES_API_KEY`. Either one alone also works.
2. `.\run.ps1` (creates `.venv` and installs deps the first time)
3. Open http://127.0.0.1:8000

## Structure

```
app/
  main.py            FastAPI routes: /, /api/tools, /api/search
  config.py          reads .env
  models.py          CompanyInput (company_name required, rest optional)
  tools/
    base.py          Tool base class + ToolResult
    __init__.py      TOOLS registry, runs all tools in parallel
    company_profile.py  Builds the official profile (name, contact, email, address, social, products, logo)
    tavily_client.py    Tavily search + extract wrapper
    companies_api.py    The Companies API client + response parser
    research_report.py  Playground-style report via Tavily Research (cited markdown)
    extractors.py       Parsers for emails, phones, social links, logos, schema.org data
  static/            UI (index.html, app.js, style.css)
```

## Tools

| Tool | Status | Needs |
|---|---|---|
| Company Profile (official website + The Companies API + Tavily) | done | company_name |
| Domain active | todo | domain |
| Domain age | todo | domain |
| Email verifier | todo | email |
| Phone verifier | todo | phone |
| Social media active | todo | social links found by the profile |
| Contact & address | todo | address |

## Adding a verifier

1. Create `app/tools/<name>.py` with a `Tool` subclass: set `name`, `label`, `required_inputs`, implement `is_configured()` and `async run()`.
2. Add it to `TOOLS` in `app/tools/__init__.py`.
3. (Optional) Add a renderer for it in `app/static/app.js` (`renderers.<name>`); otherwise the result shows as JSON.

## Research report

The **Report** tab uses the Tavily Research API (same as the Tavily playground "Research"): a markdown report
with numbered citations, rendered with source favicons and a numbered source list.
Set `TAVILY_RESEARCH_MODEL` in `.env`: `mini` (4-110 credits, ~45s), `pro` (15-250 credits, more thorough), `auto`, or `off`.
The **Verified details** tab shows the structured data from the official website and The Companies API.

## How the Company Profile is built

1. Find the official website: the domain you entered, your email's domain, or a Tavily search (skips LinkedIn, Wikipedia and other directory sites).
2. Read the website: the homepage HTML (schema.org data, footer links, logo), plus Tavily Extract on the homepage and contact/about pages.
3. Look the domain up in The Companies API (name, legal name, logo, emails, phones, HQ address, socials, description, industry).
4. Ask Tavily two questions: products & services, and HQ address/contact.
5. Merge: the same value from several sources is shown once, with every source attached.

Source labels: `Official website` (most trusted), `Companies API`, `Web search` (check it), `You provided`.
Cost per search: about 3-5 Tavily credits with research on (7-9 with it off), plus the research report, + 1 Companies API credit (0 if the company isn't in their database).
