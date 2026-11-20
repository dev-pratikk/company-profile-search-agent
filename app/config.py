"""Loads settings from the .env file in the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env", override=True)


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.getenv(name, default))))
    except ValueError:
        return default


class Settings:
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "").strip()
    tavily_max_results: int = _int("TAVILY_MAX_RESULTS", 8, 1, 20)
    companies_api_key: str = os.getenv("COMPANIES_API_KEY", "").strip()
    # Tavily Research report: mini (4-110 credits), pro (15-250), auto, or off
    research_model: str = os.getenv("TAVILY_RESEARCH_MODEL", "mini").strip().lower()
    if research_model not in ("mini", "pro", "auto", "off"):
        research_model = "mini"
    research_enabled: bool = research_model != "off"
    research_timeout: int = _int("TAVILY_RESEARCH_TIMEOUT", 300, 60, 900)
    http_timeout: float = 30.0


settings = Settings()
