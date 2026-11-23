"""FastAPI entry point. Run: uvicorn app.main:app --reload"""
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.domain import find_official_website
from app.models import CompanyInput, ReportInput
from app.report import research_company
from app.tavily import Tavily, TavilyError

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Company Profile Search Agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/config")
async def config():
    usage = None
    if settings.tavily_api_key:
        async with httpx.AsyncClient() as client:
            usage = await Tavily(client).usage()
    return {"configured": bool(settings.tavily_api_key), "model": settings.research_model, "usage": usage}


@app.post("/api/resolve")
async def resolve(inputs: CompanyInput):
    """Step 1: find the official website / domain (2 Tavily searches, about 3 credits)."""
    async with httpx.AsyncClient() as client:
        try:
            return await find_official_website(inputs, client)
        except TavilyError as e:
            raise HTTPException(502, str(e)) from e


@app.post("/api/report")
async def report(inputs: ReportInput):
    """Step 2: the cited company profile report from Tavily Research."""
    start = time.perf_counter()
    async with httpx.AsyncClient() as client:
        try:
            data = await research_company(inputs, client)
        except TavilyError as e:
            raise HTTPException(502, str(e)) from e
    data["duration_ms"] = int((time.perf_counter() - start) * 1000)
    return data


@app.post("/api/search")
async def search(inputs: CompanyInput):
    """Both steps in one call (handy for scripts)."""
    site = await resolve(inputs)
    fields = inputs.model_dump() | {"domain": site["domain"], "domain_confidence": site["confidence"]}
    rep = await report(ReportInput(**fields))
    return {"website": site, "report": rep}
