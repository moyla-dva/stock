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


@dataclass(frozen=True)
class ScanResult:
    """Single scan candidate result with extension fields preserved."""

    code: str
    scan_type: str = "opportunity"
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload):
        payload = dict(payload or {})
        return cls(
            code=str(payload.get("code") or ""),
            scan_type=str(payload.get("scan_type") or "opportunity"),
            payload=payload,
        )

    def to_dict(self):
        output = dict(self.payload)
        output.setdefault("code", self.code)
        output.setdefault("scan_type", self.scan_type)
        return output


@dataclass(frozen=True)
class ScanSnapshot:
    """Persisted scan snapshot contract."""

    code: str
    snapshot_day: str
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload):
        payload = dict(payload or {})
        return cls(
            code=str(payload.get("code") or ""),
            snapshot_day=str(payload.get("snapshot_day") or ""),
            payload=payload,
        )

    def to_dict(self):
        output = dict(self.payload)
        output.setdefault("code", self.code)
        output.setdefault("snapshot_day", self.snapshot_day)
        return output


@dataclass(frozen=True)
class ScanWorkspace:
    """Market scan workspace response contract."""

    pools: dict[str, Any] = field(default_factory=dict)
    snapshot_meta: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload):
        payload = dict(payload or {})
        return cls(
            pools=dict(payload.get("pools") or {}),
            snapshot_meta=dict(payload.get("snapshot_meta") or {}),
            payload=payload,
        )

    def to_dict(self):
        output = dict(self.payload)
        output.setdefault("pools", dict(self.pools))
        output.setdefault("snapshot_meta", dict(self.snapshot_meta))
        return output
