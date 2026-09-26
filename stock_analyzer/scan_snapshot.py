"""Daily scan snapshots for reusing one analysis across scan pools."""

import json
import os
import uuid
from datetime import datetime, time
from pathlib import Path

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.c_signal_v2 import build_c_signal_v2_priority, build_c_signal_v2_state_from_result
from stock_analyzer.data_fetcher import beijing_now, market_calendar_context
from stock_analyzer.legacy_c_signal_adapter import c_signal_v2_fields
from stock_analyzer.market_data_identity import frame_market_data_identity
from stock_analyzer.scanner import SCAN_CONFIG, format_scan_date, normalize_scan_type, scan_stock_frame
from stock_analyzer.scan_snapshot_paths import is_scan_snapshot_file
from stock_analyzer.v2_analysis_context import build_v2_analysis_context
from stock_analyzer.versioning import (
    DATA_ADJUST,
    SCAN_STRATEGY_VERSION,
    SCAN_SNAPSHOT_SCHEMA_VERSION,
    build_strategy_meta,
)


SNAPSHOT_VERSION = SCAN_SNAPSHOT_SCHEMA_VERSION
MAX_LATEST_SNAPSHOT_AGE_DAYS = int(os.environ.get("STOCK_ANALYZER_MAX_SCAN_SNAPSHOT_AGE_DAYS", "7"))
MAX_SNAPSHOT_DATA_LAG_DAYS = int(os.environ.get("STOCK_ANALYZER_MAX_SCAN_SNAPSHOT_DATA_LAG_DAYS", "14"))
SNAPSHOT_DIR = Path(os.environ.get(
    "STOCK_ANALYZER_SCAN_SNAPSHOT_DIR",
    Path(__file__).resolve().parents[1] / ".cache" / "scan_snapshots",
))
SNAPSHOT_SCAN_TYPES = (
    "opportunity",
    "risk",
    "bottom_div",
)


def snapshot_day_text(snapshot_day=None):
    value = snapshot_day or beijing_now()
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")[:8]


def normalize_snapshot_day(value):
    text = str(value or "").strip()
    if not text:
        return ""
    digits = text.replace("-", "")[:8]
    return digits if len(digits) == 8 and digits.isdigit() else ""


def display_snapshot_day(value):
    text = normalize_snapshot_day(value)
    if text:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return str(value or "").strip() or "-"


def _parse_snapshot_day(value):
    try:
        return datetime.strptime(str(value), "%Y%m%d")
    except ValueError:
        return None


def _parse_data_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except ValueError:
        return None


def _coerce_now_datetime(value=None):
    value = beijing_now() if value is None else value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M%S", "%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return beijing_now()


def is_recent_snapshot(snapshot, max_age_days=MAX_LATEST_SNAPSHOT_AGE_DAYS, now_day=None):
    snapshot_day = _parse_snapshot_day(snapshot.get("snapshot_day", ""))
    if snapshot_day is None:
        return False

    current_now = _coerce_now_datetime(now_day)
    if max_age_days is not None:
        current_day = _parse_snapshot_day(snapshot_day_text(current_now))
        if current_day is None:
            return False
        if not 0 <= (current_day - snapshot_day).days <= max_age_days:
            return False
    else:
        current_day = _parse_snapshot_day(snapshot_day_text(current_now))

    data_date = _parse_data_date(snapshot.get("data_date", ""))
    if data_date is not None and (snapshot_day - data_date).days > MAX_SNAPSHOT_DATA_LAG_DAYS:
        return False
    # After a confirmed trading-session close, reuse requires that session's data.
    # Calendar gaps retain the former weekday fallback instead of guessing a closure.
    session_status = None
    if current_day is not None:
        session_status = market_calendar_context(
            current_day.strftime("%Y%m%d")
        ).get("is_session")
    requires_current_session_data = bool(
        session_status is True
        or (
            session_status is None
            and current_day is not None
            and current_day.weekday() < 5
        )
    )
    if (
        data_date is not None
        and current_day is not None
        and requires_current_session_data
        and current_now.time() >= time(15, 10)
        and data_date.date() < current_day.date()
    ):
        return False
    return True


def _start_key(start_date=None):
    return str(start_date or "default").replace("-", "")


def scan_snapshot_path(code, start_date=None, snapshot_day=None):
    code = normalize_code(code)
    if not code:
        return None
    return SNAPSHOT_DIR / f"{code}_{_start_key(start_date)}_{snapshot_day_text(snapshot_day)}.json"


def scan_snapshot_glob(code, start_date=None):
    code = normalize_code(code)
    if not code:
        return []
    pattern = f"{code}_{_start_key(start_date)}_*.json"
    return sorted(SNAPSHOT_DIR.glob(pattern), reverse=True)


def scan_snapshot_paths_for_codes(codes, start_date=None, snapshot_days=None):
    """Resolve expected snapshot paths without globbing once per code."""
    days = tuple(dict.fromkeys(
        normalize_snapshot_day(day) for day in (snapshot_days or [None])
    ))
    paths = []
    seen = set()
    for day in days:
        if not day:
            continue
        for code in codes or ():
            path = scan_snapshot_path(code, start_date=start_date, snapshot_day=day)
            if path is None or path in seen or not path.is_file():
                continue
            seen.add(path)
            paths.append(path)
    return paths


def scan_snapshot_files(start_date=None):
    pattern = f"*_{_start_key(start_date)}_*.json"
    return sorted(
        (path for path in SNAPSHOT_DIR.glob(pattern) if is_scan_snapshot_file(path)),
        reverse=True,
    )


def scan_snapshot_day_files(start_date=None, snapshot_day=None):
    target_day = normalize_snapshot_day(snapshot_day)
    if not target_day:
        return []
    pattern = f"*_{_start_key(start_date)}_{target_day}.json"
    return sorted(
        (path for path in SNAPSHOT_DIR.glob(pattern) if is_scan_snapshot_file(path)),
        reverse=True,
    )


def read_scan_snapshot_file(path, logger=None):
    try:
        with path.open("r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except Exception as e:
        if logger:
            logger.warning(f"读取扫描快照失败: {path.name}, error={e}")
        return None

    if snapshot.get("version") != SNAPSHOT_VERSION:
        return None
    return snapshot


def read_scan_snapshot(code, start_date=None, snapshot_day=None, logger=None):
    path = scan_snapshot_path(code, start_date=start_date, snapshot_day=snapshot_day)
    if path is None or not path.exists():
        return None
    return read_scan_snapshot_file(path, logger=logger)


def is_current_strategy_snapshot(snapshot):
    return bool(
        snapshot
        and snapshot.get("strategy_version") == SCAN_STRATEGY_VERSION
        and snapshot.get("data_adjust") == DATA_ADJUST
    )


def read_latest_scan_snapshot(
    code,
    start_date=None,
    logger=None,
    max_age_days=MAX_LATEST_SNAPSHOT_AGE_DAYS,
    require_current_strategy=False,
):
    for path in scan_snapshot_glob(code, start_date=start_date):
        snapshot = read_scan_snapshot_file(path, logger=logger)
        if snapshot is None or not is_recent_snapshot(snapshot, max_age_days=max_age_days):
            continue
        if require_current_strategy and not is_current_strategy_snapshot(snapshot):
            continue
        return snapshot
    return None


def write_scan_snapshot(snapshot, start_date=None, snapshot_day=None, logger=None):
    code = snapshot.get("code")
    path = scan_snapshot_path(code, start_date=start_date, snapshot_day=snapshot_day)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique tmp name so the web service and offline rebuild jobs writing the
        # same code/day never clobber each other's staging file.
        tmp_path = path.with_suffix(f".{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(path)
    except Exception as e:
        if logger:
            logger.warning(f"写入扫描快照失败: {path.name}, error={e}")


def build_scan_snapshot(
    code,
    name,
    df_display,
    scan_types=SNAPSHOT_SCAN_TYPES,
    snapshot_day=None,
    sector=None,
    concepts=None,
):
    code = normalize_code(code) or code
    sector = str(sector or "").strip()
    concepts = list(concepts or [])
    computed_scan_types = [normalize_scan_type(scan_type) for scan_type in scan_types]
    results = {}
    analysis_context = build_v2_analysis_context(
        df_display,
        context={
            "alignment": "scan_candidate",
            "detail": "来自扫描候选，仍需核对市场结构和板块阶段。",
        },
        include_events=False,
        include_trade_plan=True,
    )
    trade_plan = analysis_context.get("trade_plan")

    for scan_type in computed_scan_types:
        result = scan_stock_frame(
            code,
            name or code,
            df_display,
            scan_type,
            analysis_context=analysis_context,
        )
        if result:
            result["sector"] = sector
            result["concepts"] = concepts
            result["trade_plan"] = trade_plan
            results[scan_type] = result

    data_date = "-"
    rows = 0
    if df_display is not None and not df_display.empty:
        rows = int(len(df_display))
        if "date" in df_display.columns:
            data_date = format_scan_date(df_display.iloc[-1]["date"])
    data_identity = frame_market_data_identity(df_display)

    return {
        "version": SNAPSHOT_VERSION,
        "strategy_version": SCAN_STRATEGY_VERSION,
        "strategy_meta": build_strategy_meta(),
        "data_adjust": DATA_ADJUST,
        "code": code,
        "name": name or code,
        "sector": sector,
        "concepts": concepts,
        "snapshot_day": snapshot_day_text(snapshot_day),
        "data_date": data_date,
        "bar_state": data_identity.get("bar_state") or "unknown",
        "data_source": data_identity.get("data_source") or "unknown",
        "cache_status": data_identity.get("cache_status") or "unknown",
        "data_revision": data_identity.get("data_revision") or "unknown",
        "generated_at": data_identity.get("generated_at") or "unknown",
        "calendar_id": data_identity.get("calendar_id") or "unknown",
        "calendar_revision": data_identity.get("calendar_revision") or "unknown",
        "calendar_evidence_level": (
            data_identity.get("calendar_evidence_level") or "unknown"
        ),
        "rows": rows,
        "trade_plan": trade_plan,
        "computed_scan_types": sorted(set(computed_scan_types), key=computed_scan_types.index),
        "results": results,
    }


def snapshot_has_scan_type(snapshot, scan_type):
    scan_type = normalize_scan_type(scan_type)
    return scan_type in set(snapshot.get("computed_scan_types", []))


def scan_result_from_snapshot(snapshot, scan_type):
    scan_type = normalize_scan_type(scan_type)
    result = snapshot.get("results", {}).get(scan_type)
    if result is None:
        return None
    output = dict(result)
    is_current_strategy = is_current_strategy_snapshot(snapshot)
    strategy_meta = snapshot.get("strategy_meta") if isinstance(snapshot.get("strategy_meta"), dict) else {}
    output["strategy_status"] = "current" if is_current_strategy else "legacy"
    output["strategy_source_label"] = "当前策略" if is_current_strategy else "旧策略"
    output["snapshot_strategy_version"] = snapshot.get("strategy_version") or "legacy"
    output["snapshot_strategy_label"] = strategy_meta.get("strategy_label") or ("当前策略" if is_current_strategy else "旧策略快照")
    if "trade_plan" not in output and isinstance(snapshot.get("trade_plan"), dict):
        output["trade_plan"] = snapshot["trade_plan"]
    if output.get("signal_key") and not output.get("v2_signal"):
        output.update(c_signal_v2_fields(output.get("signal_key")))
    if output.get("signal_key") and not output.get("v2_state_model"):
        output["v2_state_model"] = build_c_signal_v2_state_from_result(output)
    state_model = output.get("v2_state_model") if isinstance(output.get("v2_state_model"), dict) else {}
    if output.get("signal_key") and (
        not state_model.get("candidate_substate")
        or not state_model.get("candidate_trigger_plan")
    ):
        backfilled_state = build_c_signal_v2_state_from_result(output)
        for key in (
            "candidate_substate",
            "candidate_substate_label",
            "candidate_display_label",
            "candidate_confirmation_price",
            "candidate_invalidation_price",
            "candidate_missing_confirmations",
            "candidate_trigger_plan",
        ):
            state_model[key] = backfilled_state.get(key)
        if state_model:
            output["v2_state_model"] = state_model
    for key in (
        "candidate_substate",
        "candidate_substate_label",
        "candidate_display_label",
        "candidate_confirmation_price",
        "candidate_invalidation_price",
        "candidate_missing_confirmations",
        "candidate_trigger_plan",
    ):
        if key not in output and state_model.get(key) is not None:
            output[key] = state_model.get(key)
    if output.get("signal_key") and not output.get("v2_priority_score"):
        output.update(build_c_signal_v2_priority(output))
    return output


def scan_config_keys():
    return tuple(SCAN_CONFIG.keys())
