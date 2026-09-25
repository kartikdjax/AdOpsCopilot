"""
Who is asking, as the MCP server sees it.

The API decides a user's scope from their session and the orchestrator
attaches it to every tool call as MCP request metadata (META_KEY) - never
as a tool argument, so it isn't in any tool schema and the LLM can't see,
set or override it. Revive tools refuse to run without it (fail closed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

META_KEY = "copilot_scope"
ROLES = ("admin", "manager")


@dataclass(frozen=True, slots=True)
class Scope:
    role: str
    agency_id: int | None = None  # the Revive manager (rv_agency) a manager role is limited to

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise PermissionError(f"Role {self.role!r} has no data access")
        if self.role == "manager" and not isinstance(self.agency_id, int):
            raise PermissionError("A manager scope needs an agency_id")
        if self.role == "admin" and self.agency_id is not None:
            raise PermissionError("An admin scope can't be limited to an agency")

    @property
    def revive_agency_id(self) -> int | None:
        """What to scope Revive queries by: None for admins, the manager's agency otherwise."""
        return self.agency_id

    def to_meta(self) -> dict[str, Any]:
        return {META_KEY: {"role": self.role, "agency_id": self.agency_id}}

    @classmethod
    def from_meta(cls, meta: dict[str, Any] | None) -> Scope:
        raw = (meta or {}).get(META_KEY)
        if not isinstance(raw, dict):
            raise PermissionError("Access denied: this request carries no user scope")
        return cls(role=raw.get("role"), agency_id=raw.get("agency_id"))


ADMIN = Scope("admin")
