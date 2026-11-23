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


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    v = os.getenv(name, default).strip().lower()
    return v if v in allowed else default


class Settings:
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "").strip()
    # Tavily Research model: auto (playground default), pro (most thorough), mini (cheapest)
    research_model: str = _choice("TAVILY_RESEARCH_MODEL", "auto", ("auto", "pro", "mini"))
    # Report length: short, standard, long
    research_length: str = _choice("TAVILY_RESEARCH_LENGTH", "standard", ("short", "standard", "long"))
    research_timeout: int = _int("TAVILY_RESEARCH_TIMEOUT", 300, 60, 900)
    # Boost search results from this country, like Google does for your location
    # (full lowercase name, e.g. "india", "united states"). Empty = worldwide.
    search_country: str = os.getenv("TAVILY_COUNTRY", "").strip().lower()


settings = Settings()
