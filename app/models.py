"""Request models. Only company_name is mandatory."""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CompanyInput(BaseModel):
    company_name: str = Field(..., max_length=200)
    domain: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v, info):
        if isinstance(v, str):
            v = v.strip()
            if info.field_name == "company_name":
                return v  # keep "" so the required-name check below fires
            return v or None
        return v

    @field_validator("company_name")
    @classmethod
    def _require_name(cls, v):
        if not v:
            raise ValueError("Company name is required")
        return v

    @field_validator("domain")
    @classmethod
    def _normalize_domain(cls, v):
        """Accept 'https://www.Example.com/about' and store 'example.com'."""
        if not v:
            return None
        v = re.sub(r"^[a-z]+://", "", v.lower())
        v = v.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
        if v.startswith("www."):
            v = v[4:]
        return v or None

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v):
        return v.lower() if v else None


class ReportInput(CompanyInput):
    # How sure we are that `domain` is the official website (from /api/resolve).
    # Leave empty when the user typed the domain themselves.
    domain_confidence: Literal["provided", "high", "medium", "low", "none"] | None = None
    # A different website that web search found for the same name (when `domain` came from the email).
    other_domain: str | None = None

    @field_validator("other_domain")
    @classmethod
    def _normalize_other(cls, v):
        return cls._normalize_domain(v)
