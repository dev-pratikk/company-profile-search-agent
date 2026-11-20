"""Input model for a company search. Only company_name is mandatory."""
import re

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
