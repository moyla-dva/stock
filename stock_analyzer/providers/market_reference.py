"""Adapters for locally bundled calendars and exchange stock-list snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd


DEFAULT_OFFICIAL_MARKET_SCHEDULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "reference_data"
    / "official_market_schedules.json"
)
BSE_OPEN_DATE = "2021-11-15"


@dataclass(frozen=True)
class CalendarSourcePayload:
    sessions: tuple[str, ...]
    source: str
    evidence_level: str
    package_version: str
    evidence_segments: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class UniverseSourcePayload:
    as_of: str
    members: tuple[dict[str, str], ...]
    source: str
    evidence_level: str
    coverage_status: str
    coverage: dict[str, Any]
    warnings: tuple[str, ...]


def load_akshare_bundled_calendar(ak_module=ak) -> CalendarSourcePayload:
    """Read AkShare's packaged Sina calendar without making a network request."""

    package_root = Path(ak_module.__file__).resolve().parent
    path = package_root / "file_fold" / "calendar.json"
    sessions = json.loads(path.read_text(encoding="utf-8"))
    normalized = tuple(sorted({str(item) for item in sessions if str(item)}))
    if not normalized:
        raise ValueError(f"bundled calendar is empty: {path}")
    version = str(getattr(ak_module, "__version__", "unknown"))
    return CalendarSourcePayload(
        sessions=normalized,
        source=f"akshare-{version}:bundled-sina-calendar",
        evidence_level="provider",
        package_version=version,
        evidence_segments=({
            "coverage_start": normalized[0],
            "coverage_end": normalized[-1],
            "source": f"akshare-{version}:bundled-sina-calendar",
            "evidence_level": "provider",
            "source_url": "",
            "priority": 10,
        },),
    )


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def load_exchange_validated_calendar(
    ak_module=ak,
    *,
    schedule_path: str | Path = DEFAULT_OFFICIAL_MARKET_SCHEDULE_PATH,
) -> CalendarSourcePayload:
    """Overlay official annual exchange closure notices on the provider baseline."""

    base = load_akshare_bundled_calendar(ak_module)
    path = Path(schedule_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if int(manifest.get("schema_version") or 0) != 1:
        raise ValueError("unsupported official market schedule schema")

    sessions = set(base.sessions)
    evidence_segments = list(base.evidence_segments)
    seen_years = set()
    for year_payload in manifest.get("years") or []:
        year = int(year_payload.get("year") or 0)
        if year < 1990 or year in seen_years:
            raise ValueError(f"invalid or duplicate official schedule year: {year}")
        seen_years.add(year)
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        if year_start.strftime("%Y%m%d") < min(sessions) or year_end.strftime("%Y%m%d") > max(sessions):
            raise ValueError(f"official schedule year outside provider coverage: {year}")

        closed_dates = set()
        for closed_range in year_payload.get("closed_ranges") or []:
            start = date.fromisoformat(str(closed_range.get("start") or ""))
            end = date.fromisoformat(str(closed_range.get("end") or ""))
            if start.year != year or end.year != year or start > end:
                raise ValueError(f"invalid official closure range for {year}")
            closed_dates.update(_date_range(start, end))

        sessions = {
            item for item in sessions
            if not item.startswith(str(year))
        }
        sessions.update(
            item.strftime("%Y%m%d")
            for item in _date_range(year_start, year_end)
            if item.weekday() < 5 and item not in closed_dates
        )
        notices = year_payload.get("notices") or []
        if not notices:
            raise ValueError(f"official schedule year has no evidence notices: {year}")
        for notice in notices:
            source = str(notice.get("source") or "").strip()
            source_url = str(notice.get("url") or "").strip()
            if not source or not source_url:
                raise ValueError(f"official schedule notice is incomplete: {year}")
            evidence_segments.append({
                "coverage_start": year_start.isoformat(),
                "coverage_end": year_end.isoformat(),
                "source": source,
                "evidence_level": "exchange-official",
                "source_url": source_url,
                "priority": 100,
            })

    if not seen_years:
        raise ValueError("official market schedule manifest contains no years")
    return CalendarSourcePayload(
        sessions=tuple(sorted(sessions)),
        source=f"{base.source}+exchange-official-calendar-overlay-v1",
        evidence_level="mixed",
        package_version=base.package_version,
        evidence_segments=tuple(evidence_segments),
    )


def _date_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.date().isoformat()


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _first_value(row, names) -> Any:
    for name in names:
        if name in row.index:
            value = row.get(name)
            if value is not None and not pd.isna(value):
                return value
    return ""


def _records_from_frame(
    frame,
    *,
    exchange: str,
    member_source: str,
    code_columns: tuple[str, ...],
    name_columns: tuple[str, ...],
    listing_columns: tuple[str, ...],
    delisting_columns: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    if frame is None or frame.empty:
        return []
    output = []
    for _, row in frame.iterrows():
        raw_code = _text(_first_value(row, code_columns))
        digits = "".join(character for character in raw_code if character.isdigit())
        if len(digits) < 6:
            continue
        output.append({
            "code": digits[-6:],
            "name": _text(_first_value(row, name_columns)),
            "exchange": exchange,
            "listing_status": "listed",
            "listing_date": _date_text(_first_value(row, listing_columns)),
            "delisting_date": _date_text(_first_value(row, delisting_columns)),
            "member_source": member_source,
        })
    return output


def _fetch_frame(label, fetcher, warnings, *, required=False):
    try:
        frame = fetcher()
    except Exception as exc:
        warnings.append(f"{label} unavailable: {type(exc).__name__}: {exc}")
        if required:
            raise RuntimeError(f"required universe source unavailable: {label}") from exc
        return pd.DataFrame()
    if frame is None or frame.empty:
        warnings.append(f"{label} returned no rows")
        if required:
            raise RuntimeError(f"required universe source returned no rows: {label}")
        return pd.DataFrame()
    return frame


def build_exchange_universe(
    as_of: str,
    ak_module=ak,
    *,
    observed_on: str | None = None,
) -> UniverseSourcePayload:
    """Derive an A-share universe from exchange current and delisted lists.

    Historical output is intentionally marked partial because the configured
    provider has no complete BSE membership-exit history, effective-dated code
    aliases, or point-in-time name history.
    """

    target = pd.to_datetime(as_of, errors="raise").date()
    observed_date = (
        pd.to_datetime(observed_on, errors="raise").date()
        if observed_on
        else datetime.now(ZoneInfo("Asia/Shanghai")).date()
    )
    warnings: list[str] = []
    current_frames = [
        (
            _fetch_frame(
                "SSE main-board current list",
                lambda: ak_module.stock_info_sh_name_code(symbol="主板A股"),
                warnings,
                required=True,
            ),
            "SSE",
            "sse_current_main",
            ("证券代码",),
            ("证券简称",),
            ("上市日期",),
        ),
        (
            _fetch_frame(
                "SSE STAR current list",
                lambda: ak_module.stock_info_sh_name_code(symbol="科创板"),
                warnings,
                required=True,
            ),
            "SSE",
            "sse_current_star",
            ("证券代码",),
            ("证券简称",),
            ("上市日期",),
        ),
        (
            _fetch_frame(
                "SZSE A-share current list",
                lambda: ak_module.stock_info_sz_name_code(symbol="A股列表"),
                warnings,
                required=True,
            ),
            "SZSE",
            "szse_current",
            ("A股代码", "证券代码"),
            ("A股简称", "证券简称"),
            ("A股上市日期", "上市日期"),
        ),
        (
            _fetch_frame(
                "BSE current list",
                ak_module.stock_info_bj_name_code,
                warnings,
                required=True,
            ),
            "BSE",
            "bse_current",
            ("证券代码",),
            ("证券简称",),
            ("上市日期",),
        ),
    ]
    records = []
    for frame, exchange, source, code_cols, name_cols, listing_cols in current_frames:
        exchange_records = _records_from_frame(
            frame,
            exchange=exchange,
            member_source=source,
            code_columns=code_cols,
            name_columns=name_cols,
            listing_columns=listing_cols,
        )
        if not exchange_records:
            raise RuntimeError(
                f"required universe source produced no valid membership rows: {exchange} current list"
            )
        records.extend(exchange_records)

    historical = target < observed_date
    if target > observed_date:
        warnings.append(
            f"requested as_of {target.isoformat()} is after provider observation date "
            f"{observed_date.isoformat()}"
        )
    sh_delisted = pd.DataFrame()
    sz_delisted = pd.DataFrame()
    if historical:
        sh_delisted = _fetch_frame(
            "SSE delisted list",
            lambda: ak_module.stock_info_sh_delist(symbol="全部"),
            warnings,
        )
        sz_delisted = _fetch_frame(
            "SZSE delisted list",
            lambda: ak_module.stock_info_sz_delist(symbol="终止上市公司"),
            warnings,
        )
        records.extend(_records_from_frame(
            sh_delisted,
            exchange="SSE",
            member_source="sse_delisted",
            code_columns=("公司代码", "证券代码"),
            name_columns=("公司简称", "证券简称"),
            listing_columns=("上市日期",),
            delisting_columns=("暂停上市日期", "终止上市日期"),
        ))
        records.extend(_records_from_frame(
            sz_delisted,
            exchange="SZSE",
            member_source="szse_delisted",
            code_columns=("证券代码", "公司代码"),
            name_columns=("证券简称", "公司简称"),
            listing_columns=("上市日期",),
            delisting_columns=("终止上市日期", "暂停上市日期"),
        ))
        warnings.append(
            "BSE delisted history and transfer exits, effective-dated code aliases, and "
            "historical security-name revisions are incomplete"
        )

    members: dict[str, dict[str, str]] = {}
    for record in records:
        listed_on = record.get("listing_date") or ""
        delisted_on = record.get("delisting_date") or ""
        if record.get("exchange") == "BSE":
            if historical and not listed_on:
                warnings.append(
                    f"BSE member {record['code']} has no listing date; omitted from historical universe"
                )
                continue
            if listed_on and listed_on < BSE_OPEN_DATE:
                listed_on = BSE_OPEN_DATE
                record = {**record, "listing_date": listed_on}
        if listed_on and listed_on > target.isoformat():
            continue
        if delisted_on and target.isoformat() >= delisted_on:
            continue
        existing = members.get(record["code"])
        if existing is None or record["member_source"].startswith(("sse_current", "szse_current", "bse_current")):
            members[record["code"]] = record

    if not members:
        raise RuntimeError("exchange universe provider produced no members")
    version = str(getattr(ak_module, "__version__", "unknown"))
    coverage = {
        "membership": {
            "SSE": {
                "status": "available",
                "evidence_level": "provider",
                "impact": "membership",
                "sources": ["sse_current_main", "sse_current_star"],
            },
            "SZSE": {
                "status": "available",
                "evidence_level": "provider",
                "impact": "membership",
                "sources": ["szse_current"],
            },
            "BSE": {
                "status": "available" if not current_frames[3][0].empty else "unavailable",
                "evidence_level": "provider",
                "impact": "membership",
                "sources": ["bse_current"],
            },
        },
        "delisting_history": {
            "SSE": {
                "status": (
                    "available" if historical and not sh_delisted.empty
                    else "not_required" if not historical else "unavailable"
                ),
                "evidence_level": "provider",
                "impact": "membership",
                "sources": ["sse_delisted"],
            },
            "SZSE": {
                "status": (
                    "available" if historical and not sz_delisted.empty
                    else "not_required" if not historical else "unavailable"
                ),
                "evidence_level": "provider",
                "impact": "membership",
                "sources": ["szse_delisted"],
            },
            "BSE": {
                "status": "missing" if historical else "not_required",
                "evidence_level": "none" if historical else "not_required",
                "impact": "membership",
                "sources": [],
            },
        },
        "security_name_history": {
            "ALL": {
                "status": "missing" if historical else "not_required",
                "evidence_level": "none" if historical else "not_required",
                "impact": "display",
                "sources": [],
            },
        },
        "governance": {
            "upstream_usage_terms": {
                "status": "unreviewed",
                "evidence_level": "maintainer-statement",
                "impact": "governance",
                "sources": [
                    f"akshare-{version}:MIT-code-license",
                    "akshare-data-statement:academic-research-only",
                    "underlying-provider-terms:unreviewed",
                ],
                "review_note": (
                    "Library license and maintainer data-use statement reviewed; "
                    "underlying source-site terms remain unreviewed"
                ),
            },
        },
        "observation": {
            "target_as_of": target.isoformat(),
            "provider_observed_on": observed_date.isoformat(),
        },
    }
    return UniverseSourcePayload(
        as_of=target.isoformat(),
        members=tuple(members[code] for code in sorted(members)),
        source=f"akshare-{version}:exchange-list-aggregate",
        evidence_level="provider-derived",
        coverage_status="partial" if historical or warnings else "current-provider-snapshot",
        coverage=coverage,
        warnings=tuple(sorted(set(warnings))),
    )
