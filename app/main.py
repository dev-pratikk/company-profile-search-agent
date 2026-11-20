"""FastAPI entry point. Run: uvicorn app.main:app --reload"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models import CompanyInput
from app.tools import TOOLS_BY_NAME, describe_tools, run_all, run_tool

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Company Profile Search Agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/tools")
def tools():
    return {"tools": describe_tools(), "research_model": settings.research_model}


@app.post("/api/run/{tool_name}")
async def run_one(tool_name: str, inputs: CompanyInput):
    """Run a single tool, so the UI can show each result as soon as it's ready."""
    tool = TOOLS_BY_NAME.get(tool_name)
    if not tool:
        raise HTTPException(404, f"Unknown tool: {tool_name}")
    return {"input": inputs.model_dump(), "result": (await run_tool(tool, inputs)).to_dict()}


@app.post("/api/search")
async def search(inputs: CompanyInput):
    """Run every tool at once (handy for scripts)."""
    results = await run_all(inputs)
    return {"input": inputs.model_dump(), "results": [r.to_dict() for r in results]}
