# Company Profile Search Agent

Type a company name and get a cited company profile: official website, overview, contact numbers,
emails, address, social media profiles, and products & services. It uses only the Tavily API.

## Run

1. Put your key in `.env` (see `.env.example`): `TAVILY_API_KEY`.
2. `.\run.ps1` (creates `.venv` and installs dependencies the first time).
3. Open http://127.0.0.1:8000

## How it works

**Step 1: find the official website** (`app/domain.py`, 2 Tavily searches, about 3 credits)

- If you enter the website, it is used as-is.
- If you enter a contact person's work email (not Gmail, Outlook and so on), the email decides:
  - the email's domain has a website → **that is the primary website** (`felipe@silicondreams.io` → silicondreams.io);
    a different site found by name search is shown next to it (silicondreams.net) with "Use this instead".
  - the email's domain has **no** website (email-only domain) → the app asks Tavily, as the playground does,
    which website belongs to that email, and picks the site with the same brand
    (`bob@dbbaits.com` → dbbaits.com has no pages → **dbbaits.co.za**). Both are shown.
- Otherwise two searches run in parallel: "What is the official website of X?" (advanced, with an answer)
  and "X company official site". LinkedIn, Wikipedia, Crunchbase, directories and news sites are excluded.
- Each remaining domain is scored on: does the domain match the name or its acronym (`tcs.com` for Tata Consultancy
  Services), does Tavily's answer name it, is it a homepage, how high does it rank, and does it appear in both searches.
- Near spellings count as a match ("QuantaReality" matches `quantarealty.in`). Trademark registries, property
  portals and other pages *about* a company are never picked.
- **Did you mean:** if nothing convincing is found, it searches spelling variants (split words, common
  misspellings like reality → realty), like Google's autocorrect, and shows "Showing results for …".
- `TAVILY_COUNTRY` (e.g. `india`) favours local companies, as Google does for your location:
  "Quantum Realty" gives the Indian `quantumrealty.co.in`, not the US firms with that name.
- The result has a confidence level. When several companies share the name, the UI says so and offers the other
  matches. Click one, or add a location, to search again.

**Step 2: research report** (`app/report.py`, Tavily Research)

The prompt anchors the research to the official domain ("report only on the organisation that owns X"),
sets fixed sections, and gives rules: official website first, copy contact details exactly, never guess emails,
write "Not publicly listed" when something can't be found, and cite everything. The domain is also passed as
`include_domains`, a soft preference so other sources are still allowed.
The full prompt is shown under each report ("Prompt sent to Tavily Research"), so you can paste it into the Tavily playground to compare.

**When Research is refused** (`app/quick_report.py`)

Tavily refuses a Research job up front when the plan's remaining credits can't cover its worst-case cost
(roughly 100+ credits). The app then tries `mini`, and if that is refused too, it builds a quick report from
3 Tavily searches (6 credits). Contact details in that report come only from the official domain.
The header shows how many plan credits are left.

## Settings (`.env`)

| Key | Default | Meaning |
|---|---|---|
| `TAVILY_API_KEY` | | required |
| `TAVILY_RESEARCH_MODEL` | `auto` | `auto` (playground default), `pro` (most thorough), `mini` (cheapest). If your plan refuses `auto`/`pro` for credit limits, the app retries with `mini` automatically. |
| `TAVILY_RESEARCH_LENGTH` | `standard` | `short`, `standard`, `long` |
| `TAVILY_COUNTRY` | (empty) | Favour results from this country, e.g. `india`, `united states`. Empty = worldwide. |
| `TAVILY_RESEARCH_TIMEOUT` | `300` | seconds to wait for a report |

## Structure

```
app/
  main.py      FastAPI routes: / , /api/config, /api/resolve (step 1), /api/report (step 2), /api/search (both)
  config.py    reads .env
  models.py    CompanyInput (company_name required), ReportInput
  tavily.py    Tavily Search + Research client
  domain.py    official website detection
  report.py    research prompt + report
  static/      UI (index.html, app.js, style.css)
```
