"""Resolve and persist the current scan universe through market metadata SQLite."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from stock_analyzer.catalog_stock_list import StockUniverseUnavailable
from stock_analyzer.market_metadata_store import (
    DEFAULT_MARKET_METADATA_PATH,
    MarketMetadataStore,
)
from stock_analyzer.providers.market_reference import (
    build_exchange_universe,
    load_exchange_validated_calendar,
)


BEIJING = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class CurrentStockUniverse:
    as_of: str
    revision: str
    source: str
    coverage_status: str
    calendar_revision: str
    codes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "revision": self.revision,
            "source": self.source,
            "coverage_status": self.coverage_status,
            "calendar_revision": self.calendar_revision,
            "member_count": len(self.codes),
            "codes": list(self.codes),
        }


@dataclass
class _UniverseFlight:
    event: threading.Event
    result: CurrentStockUniverse | None = None
    error: Exception | None = None


class CurrentUniverseService:
    """Refresh at most once per session date and return the pinned SQLite revision."""

    def __init__(
        self,
        store: MarketMetadataStore | None = None,
        *,
        universe_loader: Callable[..., object] = build_exchange_universe,
        calendar_loader: Callable[[], object] = load_exchange_validated_calendar,
        now: Callable[[], datetime] | None = None,
    ):
        self.store = store or MarketMetadataStore(DEFAULT_MARKET_METADATA_PATH)
        self.universe_loader = universe_loader
        self.calendar_loader = calendar_loader
        self.now = now or (lambda: datetime.now(BEIJING))
        self._lock = threading.Lock()
        self._flights: dict[str, _UniverseFlight] = {}

    def _ensure_calendar(self, today: str) -> dict[str, object]:
        status = self.store.calendar_status("XSHG")
        if (
            not status.get("available")
            or today < str(status.get("coverage_start") or "")
            or today > str(status.get("coverage_end") or "")
        ):
            payload = self.calendar_loader()
            self.store.import_trading_calendar(
                payload.sessions,
                source=payload.source,
                evidence_level=payload.evidence_level,
                evidence_segments=payload.evidence_segments,
            )
            status = self.store.calendar_status("XSHG")
        if (
            not status.get("available")
            or today < str(status.get("coverage_start") or "")
            or today > str(status.get("coverage_end") or "")
        ):
            raise StockUniverseUnavailable("交易日历未覆盖当前日期，无法确定股票池时点")
        return status

    def _resolve_session(self, today: str) -> tuple[str, str]:
        calendar = self._ensure_calendar(today)
        context = self.store.session_context(today)
        if context.get("is_session") is True:
            return today, str(context.get("calendar_revision") or calendar.get("revision") or "")
        if context.get("is_session") is False:
            previous = self.store.adjacent_trading_session(
                today,
                direction="previous",
                inclusive=True,
            )
            if previous:
                previous_context = self.store.session_context(previous)
                return previous, str(previous_context.get("calendar_revision") or calendar.get("revision") or "")
        raise StockUniverseUnavailable("交易日历无法确认当前交易日，已停止扫描")

    def _read_eligible_snapshot(self, as_of: str, calendar_revision: str):
        report = self.store.universe_coverage_report(as_of)
        if not report.get("current_scan_eligible"):
            return None
        snapshot = self.store.universe_as_of(as_of)
        codes = tuple(str(item["code"]) for item in snapshot.get("members") or [])
        if not codes:
            return None
        return CurrentStockUniverse(
            as_of=as_of,
            revision=str(snapshot.get("revision") or ""),
            source=str(snapshot.get("source") or ""),
            coverage_status=str(snapshot.get("coverage_status") or "unknown"),
            calendar_revision=calendar_revision,
            codes=codes,
        )

    def _load_for_today(self, today: str) -> CurrentStockUniverse:
        as_of, calendar_revision = self._resolve_session(today)
        snapshot = self._read_eligible_snapshot(as_of, calendar_revision)
        if snapshot:
            return snapshot

        if as_of != today:
            raise StockUniverseUnavailable(
                f"最近交易日 {as_of} 没有有效股票池快照；非交易日不重建历史名单"
            )

        try:
            payload = self.universe_loader(as_of, observed_on=today)
            if str(payload.as_of) != as_of or not payload.members:
                raise ValueError("名单源返回的日期或股票列表无效")
            imported = self.store.import_universe_snapshot(
                payload.as_of,
                payload.members,
                source=payload.source,
                evidence_level=payload.evidence_level,
                coverage_status=payload.coverage_status,
                coverage=payload.coverage,
                warnings=payload.warnings,
            )
            snapshot = self._read_eligible_snapshot(as_of, calendar_revision)
            if not snapshot:
                raise ValueError("刷新后的股票池未通过当前扫描完整性校验")
            if snapshot.revision != imported.get("revision"):
                raise RuntimeError("读取到的股票池 revision 与刚写入的 revision 不一致")
            return snapshot
        except StockUniverseUnavailable:
            raise
        except Exception as exc:
            raise StockUniverseUnavailable(
                f"无法刷新 {as_of} 的完整股票池：{exc}"
            ) from exc

    def get(self) -> CurrentStockUniverse:
        now = self.now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=BEIJING)
        today = now.astimezone(BEIJING).date().isoformat()

        with self._lock:
            flight = self._flights.get(today)
            if flight is None:
                flight = _UniverseFlight(event=threading.Event())
                self._flights[today] = flight
                leader = True
            else:
                leader = False

        if not leader:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            if flight.result is None:
                raise StockUniverseUnavailable("股票池刷新未返回结果")
            return flight.result

        try:
            flight.result = self._load_for_today(today)
            return flight.result
        except Exception as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(today, None)
                flight.event.set()


_default_service = CurrentUniverseService()


def get_current_stock_universe() -> CurrentStockUniverse:
    return _default_service.get()
