"""Domain payload contracts shared across services and presentation layers."""

from dataclasses import dataclass, field
from typing import Any


def _clean_list(values):
    if not isinstance(values, (list, tuple, set)):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


@dataclass(frozen=True)
class StockProfile:
    """Canonical stock identity and market taxonomy payload."""

    code: str
    name: str = ""
    sector: str = ""
    concepts: list[str] = field(default_factory=list)

    @classmethod
    def empty(cls):
        return cls(code="", name="", sector="", concepts=[])

    @classmethod
    def from_dict(cls, code, payload=None):
        payload = payload or {}
        normalized_code = str(code or payload.get("code") or "").strip()
        name = str(payload.get("name") or normalized_code).strip()
        sector = str(payload.get("sector") or "").strip()
        concepts = _clean_list(payload.get("concepts") or payload.get("concept") or [])
        return cls(code=normalized_code, name=name, sector=sector, concepts=concepts)

    def to_dict(self):
        return {
            "code": self.code,
            "name": self.name,
            "sector": self.sector,
            "concepts": list(self.concepts),
        }
