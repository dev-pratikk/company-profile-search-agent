"""Common building blocks every verification tool shares.

To add a new verifier:
  1. Create app/tools/<name>.py with a subclass of Tool.
  2. Register an instance in TOOLS inside app/tools/__init__.py.
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import httpx

from app.models import CompanyInput

# ok      = check passed / data found
# warning = ran fine but result is doubtful (e.g. nothing found, domain mismatch)
# failed  = check ran and the thing is NOT valid (e.g. domain inactive)
# error   = the tool itself broke (bad key, API down, timeout)
# skipped = not run (missing input or API key not configured)
Status = Literal["ok", "warning", "failed", "error", "skipped"]


@dataclass
class ToolResult:
    tool: str
    label: str
    status: Status
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolError(Exception):
    """Raise inside a tool for a clean, user-readable error message."""


class Tool:
    name: str = "tool"
    label: str = "Tool"
    description: str = ""
    # Input fields (from CompanyInput) that must be filled for this tool to run.
    required_inputs: tuple[str, ...] = ("company_name",)

    def is_configured(self) -> bool:
        """Return False when the tool's API key is missing."""
        return True

    def providers(self) -> list[dict]:
        """External APIs this tool uses: [{"name": ..., "configured": bool}]."""
        return []

    def missing_inputs(self, inputs: CompanyInput) -> list[str]:
        return [f for f in self.required_inputs if not getattr(inputs, f, None)]

    async def run(self, inputs: CompanyInput, client: httpx.AsyncClient) -> ToolResult:
        raise NotImplementedError

    def result(self, status: Status, summary: str, **data: Any) -> ToolResult:
        return ToolResult(tool=self.name, label=self.label, status=status, summary=summary, data=data)
