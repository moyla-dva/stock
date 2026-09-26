"""Versioned local reference data for calendars, universes, and security history."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


MARKET_METADATA_SCHEMA_VERSION = 5
DEFAULT_MARKET_METADATA_PATH = Path(os.environ.get(
    "STOCK_ANALYZER_MARKET_METADATA_DB",
    Path(__file__).resolve().parents[1] / ".cache" / "market_metadata.sqlite3",
))


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar_imports (
    revision TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    coverage_start TEXT NOT NULL,
    coverage_end TEXT NOT NULL,
    session_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trading_sessions (
    calendar_id TEXT NOT NULL,
    session_date TEXT NOT NULL,
    source_revision TEXT NOT NULL
        REFERENCES calendar_imports(revision) ON DELETE CASCADE,
    PRIMARY KEY(calendar_id, session_date, source_revision)
);
CREATE INDEX IF NOT EXISTS idx_trading_sessions_lookup
    ON trading_sessions(calendar_id, session_date);

CREATE TABLE IF NOT EXISTS calendar_heads (
    calendar_id TEXT PRIMARY KEY,
    source_revision TEXT NOT NULL
        REFERENCES calendar_imports(revision)
);

CREATE TABLE IF NOT EXISTS calendar_evidence_segments (
    source_revision TEXT NOT NULL
        REFERENCES calendar_imports(revision) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    coverage_start TEXT NOT NULL,
    coverage_end TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(source_revision, segment_index)
);
CREATE INDEX IF NOT EXISTS idx_calendar_evidence_lookup
    ON calendar_evidence_segments(source_revision, coverage_start, coverage_end, priority);

CREATE TABLE IF NOT EXISTS universe_imports (
    revision TEXT PRIMARY KEY,
    as_of TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    coverage_status TEXT NOT NULL DEFAULT 'unknown',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    coverage_json TEXT NOT NULL DEFAULT '{}',
    member_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS universe_members (
    as_of TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    exchange TEXT NOT NULL,
    listing_status TEXT NOT NULL,
    listing_date TEXT NOT NULL DEFAULT '',
    delisting_date TEXT NOT NULL DEFAULT '',
    member_source TEXT NOT NULL DEFAULT '',
    source_revision TEXT NOT NULL
        REFERENCES universe_imports(revision) ON DELETE CASCADE,
    PRIMARY KEY(as_of, code, source_revision)
);
CREATE INDEX IF NOT EXISTS idx_universe_members_lookup
    ON universe_members(as_of, code);

CREATE TABLE IF NOT EXISTS universe_heads (
    as_of TEXT PRIMARY KEY,
    source_revision TEXT NOT NULL
        REFERENCES universe_imports(revision)
);
"""


SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS security_reference_imports (
    revision TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    coverage_status TEXT NOT NULL DEFAULT 'unknown',
    coverage_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_security_reference_imports_dataset
    ON security_reference_imports(dataset_id, imported_at);

CREATE TABLE IF NOT EXISTS security_reference_heads (
    dataset_id TEXT PRIMARY KEY,
    source_revision TEXT NOT NULL
        REFERENCES security_reference_imports(revision)
);

CREATE TABLE IF NOT EXISTS security_entities (
    revision TEXT NOT NULL
        REFERENCES security_reference_imports(revision) ON DELETE CASCADE,
    security_id TEXT NOT NULL,
    instrument_type TEXT NOT NULL DEFAULT 'common_share',
    PRIMARY KEY(revision, security_id)
);

CREATE TABLE IF NOT EXISTS security_reference_evidence (
    revision TEXT NOT NULL
        REFERENCES security_reference_imports(revision) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    publisher TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    document_date TEXT NOT NULL DEFAULT '',
    accessed_at TEXT NOT NULL,
    evidence_level TEXT NOT NULL,
    content_sha256 TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(revision, evidence_id)
);

CREATE TABLE IF NOT EXISTS security_aliases (
    revision TEXT NOT NULL,
    security_id TEXT NOT NULL,
    exchange TEXT NOT NULL,
    code TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    valid_from_evidence_id TEXT NOT NULL,
    valid_to_evidence_id TEXT,
    PRIMARY KEY(revision, exchange, code, valid_from),
    FOREIGN KEY(revision, security_id)
        REFERENCES security_entities(revision, security_id) ON DELETE CASCADE,
    FOREIGN KEY(revision, valid_from_evidence_id)
        REFERENCES security_reference_evidence(revision, evidence_id),
    FOREIGN KEY(revision, valid_to_evidence_id)
        REFERENCES security_reference_evidence(revision, evidence_id),
    CHECK(length(code) = 6 AND code NOT GLOB '*[^0-9]*'),
    CHECK(valid_to IS NULL OR valid_to > valid_from),
    CHECK((valid_to IS NULL AND valid_to_evidence_id IS NULL) OR
          (valid_to IS NOT NULL AND valid_to_evidence_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_security_aliases_as_of
    ON security_aliases(revision, exchange, code, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS security_names (
    revision TEXT NOT NULL,
    security_id TEXT NOT NULL,
    name TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    valid_from_evidence_id TEXT NOT NULL,
    valid_to_evidence_id TEXT,
    PRIMARY KEY(revision, security_id, valid_from),
    FOREIGN KEY(revision, security_id)
        REFERENCES security_entities(revision, security_id) ON DELETE CASCADE,
    FOREIGN KEY(revision, valid_from_evidence_id)
        REFERENCES security_reference_evidence(revision, evidence_id),
    FOREIGN KEY(revision, valid_to_evidence_id)
        REFERENCES security_reference_evidence(revision, evidence_id),
    CHECK(length(trim(name)) > 0),
    CHECK(valid_to IS NULL OR valid_to > valid_from),
    CHECK((valid_to IS NULL AND valid_to_evidence_id IS NULL) OR
          (valid_to IS NOT NULL AND valid_to_evidence_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_security_names_as_of
    ON security_names(revision, security_id, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS exchange_memberships (
    revision TEXT NOT NULL,
    security_id TEXT NOT NULL,
    exchange TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    entry_reason TEXT NOT NULL,
    exit_reason TEXT NOT NULL DEFAULT '',
    valid_from_evidence_id TEXT NOT NULL,
    valid_to_evidence_id TEXT,
    PRIMARY KEY(revision, security_id, exchange, valid_from),
    FOREIGN KEY(revision, security_id)
        REFERENCES security_entities(revision, security_id) ON DELETE CASCADE,
    FOREIGN KEY(revision, valid_from_evidence_id)
        REFERENCES security_reference_evidence(revision, evidence_id),
    FOREIGN KEY(revision, valid_to_evidence_id)
        REFERENCES security_reference_evidence(revision, evidence_id),
    CHECK(length(trim(entry_reason)) > 0),
    CHECK((valid_to IS NULL AND exit_reason = '') OR
          (valid_to IS NOT NULL AND length(trim(exit_reason)) > 0)),
    CHECK(valid_to IS NULL OR valid_to > valid_from),
    CHECK((valid_to IS NULL AND valid_to_evidence_id IS NULL) OR
          (valid_to IS NOT NULL AND valid_to_evidence_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_exchange_memberships_as_of
    ON exchange_memberships(revision, exchange, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_exchange_memberships_security
    ON exchange_memberships(revision, security_id, exchange, valid_from);
"""


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc


def _normalize_code(value: Any) -> str:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", str(value or "").strip())
    if not match:
        raise ValueError(f"invalid A-share stock code: {value}")
    return match.group(1)


def _revision(kind: str, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        {"kind": kind, **dict(payload)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _required_text(record: Mapping[str, Any], key: str) -> str:
    value = str(record.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _validate_non_overlapping_intervals(
    rows: Iterable[Mapping[str, Any]],
    group_fields: tuple[str, ...],
    *,
    label: str,
) -> None:
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = tuple(str(row[field]) for field in group_fields)
        groups.setdefault(key, []).append(row)
    open_end = date.max.toordinal() + 1
    for key, intervals in groups.items():
        intervals.sort(key=lambda row: row["valid_from"])
        previous_end = -1
        for row in intervals:
            start = date.fromisoformat(str(row["valid_from"])).toordinal()
            end = (
                date.fromisoformat(str(row["valid_to"])).toordinal()
                if row.get("valid_to")
                else open_end
            )
            if start < previous_end:
                raise ValueError(f"overlapping {label} intervals for {key}")
            previous_end = max(previous_end, end)


def _coverage_gaps(coverage: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
    blocking: list[str] = []
    informational: list[str] = []
    governance: list[str] = []
    incomplete = {"missing", "unavailable", "unreviewed", "partial", "unknown"}
    for group, components in coverage.items():
        if not isinstance(components, Mapping):
            continue
        for component, detail in components.items():
            if not isinstance(detail, Mapping):
                continue
            status = str(detail.get("status") or "").strip().lower()
            if status not in incomplete:
                continue
            path = f"{group}.{component}"
            impact = str(detail.get("impact") or "membership")
            if impact == "governance" or status == "unreviewed":
                governance.append(path)
            elif impact in {"display", "descriptive"}:
                informational.append(path)
            else:
                blocking.append(path)
    return sorted(blocking), sorted(informational), sorted(governance)


def _current_membership_coverage_gaps(coverage: Mapping[str, Any]) -> list[str]:
    membership = coverage.get("membership")
    membership = membership if isinstance(membership, Mapping) else {}
    acceptable = {"available", "complete", "declared-complete"}
    return [
        f"membership.{exchange}"
        for exchange in ("SSE", "SZSE", "BSE")
        if not isinstance(membership.get(exchange), Mapping)
        or str(membership[exchange].get("status") or "").strip().lower() not in acceptable
    ]


class MarketMetadataStore:
    """Rebuildable reference-data store with explicit point-in-time semantics."""

    def __init__(self, path: str | Path = DEFAULT_MARKET_METADATA_PATH):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > MARKET_METADATA_SCHEMA_VERSION:
                raise RuntimeError(
                    f"market metadata schema {version} is newer than supported "
                    f"{MARKET_METADATA_SCHEMA_VERSION}"
                )
            if version < 1:
                connection.executescript(SCHEMA_V1)
                # SCHEMA_V1 contains the current v4 base tables; v5 remains an
                # explicit additive migration so fresh and upgraded DBs agree.
                connection.execute("PRAGMA user_version = 4")
                version = 4
            if version < 2:
                self._migrate_v1_to_v2(connection)
                connection.execute("PRAGMA user_version = 2")
                version = 2
            if version < 3:
                self._migrate_v2_to_v3(connection)
                connection.execute("PRAGMA user_version = 3")
                version = 3
            if version < 4:
                self._migrate_v3_to_v4(connection)
                connection.execute("PRAGMA user_version = 4")
                version = 4
            if version < 5:
                self._migrate_v4_to_v5(connection)
                connection.execute("PRAGMA user_version = 5")

    @staticmethod
    def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
        import_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(universe_imports)").fetchall()
        }
        member_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(universe_members)").fetchall()
        }
        for column, definition in (
            ("coverage_status", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("warnings_json", "TEXT NOT NULL DEFAULT '[]'"),
        ):
            if column not in import_columns:
                connection.execute(
                    f"ALTER TABLE universe_imports ADD COLUMN {column} {definition}"
                )
        for column in ("listing_date", "delisting_date", "member_source"):
            if column not in member_columns:
                connection.execute(
                    f"ALTER TABLE universe_members ADD COLUMN {column} "
                    "TEXT NOT NULL DEFAULT ''"
                )

    @staticmethod
    def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
        # Some early fixture databases contained only universe tables. Reapply
        # the idempotent base schema before creating evidence rows.
        connection.executescript(SCHEMA_V1)
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS calendar_evidence_segments (
                source_revision TEXT NOT NULL
                    REFERENCES calendar_imports(revision) ON DELETE CASCADE,
                segment_index INTEGER NOT NULL,
                coverage_start TEXT NOT NULL,
                coverage_end TEXT NOT NULL,
                source TEXT NOT NULL,
                evidence_level TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(source_revision, segment_index)
            );
            CREATE INDEX IF NOT EXISTS idx_calendar_evidence_lookup
                ON calendar_evidence_segments(
                    source_revision, coverage_start, coverage_end, priority
                );
        """)
        connection.execute("""
            INSERT OR IGNORE INTO calendar_evidence_segments(
                source_revision, segment_index, coverage_start, coverage_end,
                source, evidence_level, source_url, priority
            )
            SELECT revision, 0, coverage_start, coverage_end,
                   source, evidence_level, '', 0
            FROM calendar_imports
        """)

    @staticmethod
    def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(universe_imports)").fetchall()
        }
        if "coverage_json" not in columns:
            connection.execute(
                "ALTER TABLE universe_imports ADD COLUMN coverage_json "
                "TEXT NOT NULL DEFAULT '{}'"
            )

    @staticmethod
    def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
        connection.executescript(SCHEMA_V5)

    def import_trading_calendar(
        self,
        sessions: Iterable[str | date | datetime],
        *,
        calendar_id: str = "XSHG",
        source: str,
        evidence_level: str,
        evidence_segments: Iterable[Mapping[str, Any]] | None = None,
        imported_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_id = str(calendar_id or "").strip().upper()
        if not normalized_id:
            raise ValueError("calendar_id is required")
        normalized_sessions = sorted({_normalize_date(item) for item in sessions})
        if not normalized_sessions:
            raise ValueError("trading calendar must contain at least one session")
        source = str(source or "").strip()
        evidence_level = str(evidence_level or "").strip()
        if not source or not evidence_level:
            raise ValueError("source and evidence_level are required")
        normalized_segments = []
        for index, segment in enumerate(evidence_segments or ()):
            record = dict(segment)
            coverage_start = _normalize_date(record.get("coverage_start"))
            coverage_end = _normalize_date(record.get("coverage_end"))
            if coverage_start > coverage_end:
                raise ValueError("calendar evidence coverage_start must not exceed coverage_end")
            if coverage_start < normalized_sessions[0] or coverage_end > normalized_sessions[-1]:
                raise ValueError("calendar evidence segment exceeds calendar coverage")
            segment_source = str(record.get("source") or "").strip()
            segment_level = str(record.get("evidence_level") or "").strip()
            if not segment_source or not segment_level:
                raise ValueError("calendar evidence segment requires source and evidence_level")
            normalized_segments.append({
                "segment_index": index,
                "coverage_start": coverage_start,
                "coverage_end": coverage_end,
                "source": segment_source,
                "evidence_level": segment_level,
                "source_url": str(record.get("source_url") or "").strip(),
                "priority": int(record.get("priority") or 0),
            })
        if not normalized_segments:
            normalized_segments.append({
                "segment_index": 0,
                "coverage_start": normalized_sessions[0],
                "coverage_end": normalized_sessions[-1],
                "source": source,
                "evidence_level": evidence_level,
                "source_url": "",
                "priority": 0,
            })
        imported_at = str(imported_at or _utc_now_text())
        revision = _revision("trading_calendar", {
            "calendar_id": normalized_id,
            "source": source,
            "evidence_level": evidence_level,
            "sessions": normalized_sessions,
            "evidence_segments": normalized_segments,
        })
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO calendar_imports(
                    revision, calendar_id, source, evidence_level,
                    coverage_start, coverage_end, session_count, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision,
                    normalized_id,
                    source,
                    evidence_level,
                    normalized_sessions[0],
                    normalized_sessions[-1],
                    len(normalized_sessions),
                    imported_at,
                ),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO trading_sessions(
                    calendar_id, session_date, source_revision
                ) VALUES (?, ?, ?)
                """,
                ((normalized_id, item, revision) for item in normalized_sessions),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO calendar_evidence_segments(
                    source_revision, segment_index, coverage_start, coverage_end,
                    source, evidence_level, source_url, priority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        revision,
                        item["segment_index"],
                        item["coverage_start"],
                        item["coverage_end"],
                        item["source"],
                        item["evidence_level"],
                        item["source_url"],
                        item["priority"],
                    )
                    for item in normalized_segments
                ),
            )
            connection.execute(
                """
                INSERT INTO calendar_heads(calendar_id, source_revision)
                VALUES (?, ?)
                ON CONFLICT(calendar_id) DO UPDATE
                SET source_revision = excluded.source_revision
                """,
                (normalized_id, revision),
            )
        return self.calendar_status(normalized_id)

    def calendar_status(self, calendar_id: str = "XSHG") -> dict[str, Any]:
        self.initialize()
        normalized_id = str(calendar_id or "").strip().upper()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ci.*
                FROM calendar_heads ch
                JOIN calendar_imports ci ON ci.revision = ch.source_revision
                WHERE ch.calendar_id = ?
                """,
                (normalized_id,),
            ).fetchone()
        if row is None:
            return {
                "available": False,
                "calendar_id": normalized_id,
                "revision": "",
                "source": "",
                "evidence_level": "",
                "coverage_start": "",
                "coverage_end": "",
                "session_count": 0,
                "imported_at": "",
            }
        return {
            "available": True,
            "calendar_id": normalized_id,
            "revision": str(row["revision"]),
            "source": str(row["source"]),
            "evidence_level": str(row["evidence_level"]),
            "coverage_start": str(row["coverage_start"]),
            "coverage_end": str(row["coverage_end"]),
            "session_count": int(row["session_count"]),
            "imported_at": str(row["imported_at"]),
        }

    def is_trading_session(
        self,
        value: str | date | datetime,
        *,
        calendar_id: str = "XSHG",
    ) -> bool | None:
        return self.session_context(value, calendar_id=calendar_id)["is_session"]

    def session_context(
        self,
        value: str | date | datetime,
        *,
        calendar_id: str = "XSHG",
    ) -> dict[str, Any]:
        """Return session state and the highest-priority evidence for one date."""

        target = _normalize_date(value)
        status = self.calendar_status(calendar_id)
        base = {
            "date": target,
            "is_session": None,
            "calendar_id": str(calendar_id or "").upper(),
            "calendar_revision": "",
            "calendar_source": "",
            "calendar_evidence_level": "",
            "calendar_source_urls": [],
        }
        if (
            not status["available"]
            or target < status["coverage_start"]
            or target > status["coverage_end"]
        ):
            return base
        revision = status["revision"]
        with self._connect() as connection:
            session = connection.execute(
                """
                SELECT 1
                FROM trading_sessions
                WHERE calendar_id = ? AND session_date = ? AND source_revision = ?
                """,
                (str(calendar_id).upper(), target, revision),
            ).fetchone()
            rows = connection.execute(
                """
                SELECT coverage_start, coverage_end, source, evidence_level,
                       source_url, priority
                FROM calendar_evidence_segments
                WHERE source_revision = ?
                  AND coverage_start <= ? AND coverage_end >= ?
                  AND priority = (
                      SELECT MAX(priority)
                      FROM calendar_evidence_segments
                      WHERE source_revision = ?
                        AND coverage_start <= ? AND coverage_end >= ?
                  )
                ORDER BY segment_index
                """,
                (revision, target, target, revision, target, target),
            ).fetchall()
        sources = list(dict.fromkeys(str(row["source"]) for row in rows))
        levels = list(dict.fromkeys(str(row["evidence_level"]) for row in rows))
        urls = list(dict.fromkeys(
            str(row["source_url"])
            for row in rows
            if str(row["source_url"] or "")
        ))
        return {
            **base,
            "is_session": session is not None,
            "calendar_revision": revision,
            "calendar_source": "; ".join(sources) or status["source"],
            "calendar_evidence_level": (
                levels[0] if len(levels) == 1 else "mixed"
            ) if levels else status["evidence_level"],
            "calendar_source_urls": urls,
        }

    def adjacent_trading_session(
        self,
        value: str | date | datetime,
        *,
        direction: str,
        inclusive: bool = False,
        calendar_id: str = "XSHG",
    ) -> str | None:
        target = _normalize_date(value)
        status = self.calendar_status(calendar_id)
        if (
            not status["available"]
            or target < status["coverage_start"]
            or target > status["coverage_end"]
        ):
            return None
        if direction not in {"previous", "next"}:
            raise ValueError("direction must be previous or next")
        operator = "<=" if direction == "previous" and inclusive else "<"
        aggregate = "MAX"
        if direction == "next":
            operator = ">=" if inclusive else ">"
            aggregate = "MIN"
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT {aggregate}(ts.session_date) AS session_date
                FROM trading_sessions ts
                JOIN calendar_heads ch
                  ON ch.calendar_id = ts.calendar_id
                 AND ch.source_revision = ts.source_revision
                WHERE ts.calendar_id = ? AND ts.session_date {operator} ?
                """,
                (str(calendar_id).upper(), target),
            ).fetchone()
        return str(row["session_date"] or "") or None

    def import_universe_snapshot(
        self,
        as_of: str | date | datetime,
        members: Iterable[str | Mapping[str, Any]],
        *,
        source: str,
        evidence_level: str,
        coverage_status: str = "unknown",
        coverage: Mapping[str, Any] | None = None,
        warnings: Iterable[str] | None = None,
        imported_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_as_of = _normalize_date(as_of)
        normalized_members: dict[str, dict[str, str]] = {}
        for item in members:
            record = dict(item) if isinstance(item, Mapping) else {"code": item}
            code = _normalize_code(record.get("code"))
            normalized_members[code] = {
                "code": code,
                "name": str(record.get("name") or "").strip(),
                "exchange": str(record.get("exchange") or "").strip().upper(),
                "listing_status": str(
                    record.get("listing_status") or record.get("status") or "listed"
                ).strip().lower(),
                "listing_date": (
                    _normalize_date(record.get("listing_date"))
                    if record.get("listing_date")
                    else ""
                ),
                "delisting_date": (
                    _normalize_date(record.get("delisting_date"))
                    if record.get("delisting_date")
                    else ""
                ),
                "member_source": str(record.get("member_source") or "").strip(),
            }
        ordered_members = [normalized_members[code] for code in sorted(normalized_members)]
        if not ordered_members:
            raise ValueError("universe snapshot must contain at least one member")
        source = str(source or "").strip()
        evidence_level = str(evidence_level or "").strip()
        if not source or not evidence_level:
            raise ValueError("source and evidence_level are required")
        coverage_status = str(coverage_status or "unknown").strip().lower()
        normalized_coverage = json.loads(json.dumps(
            dict(coverage or {}),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ))
        normalized_warnings = sorted({str(item).strip() for item in warnings or [] if str(item).strip()})
        imported_at = str(imported_at or _utc_now_text())
        revision = _revision("stock_universe", {
            "as_of": normalized_as_of,
            "source": source,
            "evidence_level": evidence_level,
            "coverage_status": coverage_status,
            "coverage": normalized_coverage,
            "warnings": normalized_warnings,
            "members": ordered_members,
        })
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO universe_imports(
                    revision, as_of, source, evidence_level, coverage_status,
                    warnings_json, coverage_json, member_count, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision,
                    normalized_as_of,
                    source,
                    evidence_level,
                    coverage_status,
                    json.dumps(normalized_warnings, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(normalized_coverage, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    len(ordered_members),
                    imported_at,
                ),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO universe_members(
                    as_of, code, name, exchange, listing_status, listing_date,
                    delisting_date, member_source, source_revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        normalized_as_of,
                        item["code"],
                        item["name"],
                        item["exchange"],
                        item["listing_status"],
                        item["listing_date"],
                        item["delisting_date"],
                        item["member_source"],
                        revision,
                    )
                    for item in ordered_members
                ),
            )
            connection.execute(
                """
                INSERT INTO universe_heads(as_of, source_revision)
                VALUES (?, ?)
                ON CONFLICT(as_of) DO UPDATE
                SET source_revision = excluded.source_revision
                """,
                (normalized_as_of, revision),
            )
        return self.universe_as_of(normalized_as_of)

    def import_security_reference(
        self,
        document: Mapping[str, Any],
        *,
        imported_at: str | None = None,
    ) -> dict[str, Any]:
        """Import one immutable, evidence-backed effective-dated reference set."""

        if not isinstance(document, Mapping):
            raise ValueError("security reference document must be an object")
        dataset_id = _required_text(document, "dataset_id").upper()
        source = _required_text(document, "source")
        evidence_level = _required_text(document, "evidence_level")
        coverage_status = str(document.get("coverage_status") or "unknown").strip().lower()
        if coverage_status not in {"unknown", "partial", "complete", "declared-complete"}:
            raise ValueError(f"invalid coverage_status: {coverage_status}")

        coverage = json.loads(json.dumps(
            dict(document.get("coverage") or {}),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ))
        if not isinstance(coverage, dict):
            raise ValueError("coverage must be an object")
        coverage_start = _normalize_date(coverage.get("coverage_start"))
        coverage_end = _normalize_date(coverage.get("coverage_end"))
        if coverage_start > coverage_end:
            raise ValueError("coverage_start must not exceed coverage_end")
        coverage["coverage_start"] = coverage_start
        coverage["coverage_end"] = coverage_end
        coverage_status = coverage_status or "unknown"
        warnings = sorted({
            str(item).strip()
            for item in document.get("warnings") or []
            if str(item).strip()
        })

        securities = []
        security_ids = set()
        for raw in document.get("securities") or []:
            record = dict(raw)
            security_id = _required_text(record, "security_id")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]*", security_id):
                raise ValueError(f"invalid security_id: {security_id}")
            if security_id in security_ids:
                raise ValueError(f"duplicate security_id: {security_id}")
            security_ids.add(security_id)
            instrument_type = str(record.get("instrument_type") or "common_share").strip()
            if not instrument_type:
                raise ValueError(f"instrument_type is required for {security_id}")
            securities.append({
                "security_id": security_id,
                "instrument_type": instrument_type,
            })
        if not securities:
            raise ValueError("security reference must contain at least one security")
        securities.sort(key=lambda item: item["security_id"])

        evidence = []
        evidence_ids = set()
        for raw in document.get("evidence") or []:
            record = dict(raw)
            evidence_id = _required_text(record, "evidence_id")
            if evidence_id in evidence_ids:
                raise ValueError(f"duplicate evidence_id: {evidence_id}")
            evidence_ids.add(evidence_id)
            document_date = (
                _normalize_date(record["document_date"])
                if record.get("document_date") else ""
            )
            digest = str(record.get("content_sha256") or "").strip().lower()
            if digest.startswith("sha256:"):
                digest = digest[7:]
            if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"invalid SHA-256 for evidence {evidence_id}")
            evidence.append({
                "evidence_id": evidence_id,
                "publisher": _required_text(record, "publisher"),
                "title": _required_text(record, "title"),
                "source_url": _required_text(record, "source_url"),
                "document_date": document_date,
                "accessed_at": (
                    str(record.get("accessed_at") or "").strip() or _utc_now_text()
                ),
                "evidence_level": _required_text(record, "evidence_level"),
                "content_sha256": digest,
                "notes": str(record.get("notes") or "").strip(),
            })
        if not evidence:
            raise ValueError("security reference must contain source evidence")
        evidence.sort(key=lambda item: item["evidence_id"])

        def interval_evidence(record, valid_to, label):
            start_evidence_id = _required_text(record, "valid_from_evidence_id")
            end_evidence_id = str(record.get("valid_to_evidence_id") or "").strip()
            if start_evidence_id not in evidence_ids:
                raise ValueError(
                    f"{label} references unknown valid_from_evidence_id: "
                    f"{start_evidence_id}"
                )
            if valid_to and not end_evidence_id:
                raise ValueError(f"{label} requires valid_to_evidence_id")
            if not valid_to and end_evidence_id:
                raise ValueError(f"{label} cannot have valid_to_evidence_id without valid_to")
            if end_evidence_id and end_evidence_id not in evidence_ids:
                raise ValueError(
                    f"{label} references unknown valid_to_evidence_id: {end_evidence_id}"
                )
            return start_evidence_id, end_evidence_id or None

        aliases = []
        for raw in document.get("aliases") or []:
            record = dict(raw)
            security_id = _required_text(record, "security_id")
            if security_id not in security_ids:
                raise ValueError(f"alias references unknown security_id: {security_id}")
            valid_from = _normalize_date(record.get("valid_from"))
            valid_to = (
                _normalize_date(record["valid_to"])
                if record.get("valid_to") else None
            )
            if valid_to is not None and valid_to <= valid_from:
                raise ValueError("alias valid_to must be later than valid_from")
            valid_from_evidence_id, valid_to_evidence_id = interval_evidence(
                record, valid_to, "alias"
            )
            aliases.append({
                "security_id": security_id,
                "exchange": _required_text(record, "exchange").upper(),
                "code": _normalize_code(record.get("code")),
                "valid_from": valid_from,
                "valid_to": valid_to,
                "valid_from_evidence_id": valid_from_evidence_id,
                "valid_to_evidence_id": valid_to_evidence_id,
            })
        if not aliases:
            raise ValueError("security reference must contain at least one code alias")
        aliases.sort(key=lambda item: (
            item["exchange"], item["code"], item["valid_from"], item["security_id"]
        ))
        _validate_non_overlapping_intervals(
            aliases, ("exchange", "code"), label="exchange code alias"
        )
        _validate_non_overlapping_intervals(
            aliases, ("security_id", "exchange"), label="security exchange alias"
        )

        names = []
        for raw in document.get("names") or []:
            record = dict(raw)
            security_id = _required_text(record, "security_id")
            if security_id not in security_ids:
                raise ValueError(f"name references unknown security_id: {security_id}")
            valid_from = _normalize_date(record.get("valid_from"))
            valid_to = (
                _normalize_date(record["valid_to"])
                if record.get("valid_to") else None
            )
            if valid_to is not None and valid_to <= valid_from:
                raise ValueError("name valid_to must be later than valid_from")
            valid_from_evidence_id, valid_to_evidence_id = interval_evidence(
                record, valid_to, "security name"
            )
            names.append({
                "security_id": security_id,
                "name": _required_text(record, "name"),
                "valid_from": valid_from,
                "valid_to": valid_to,
                "valid_from_evidence_id": valid_from_evidence_id,
                "valid_to_evidence_id": valid_to_evidence_id,
            })
        names.sort(key=lambda item: (item["security_id"], item["valid_from"]))
        _validate_non_overlapping_intervals(
            names, ("security_id",), label="security name"
        )

        memberships = []
        for raw in document.get("memberships") or []:
            record = dict(raw)
            security_id = _required_text(record, "security_id")
            if security_id not in security_ids:
                raise ValueError(f"membership references unknown security_id: {security_id}")
            valid_from = _normalize_date(record.get("valid_from"))
            valid_to = (
                _normalize_date(record["valid_to"])
                if record.get("valid_to") else None
            )
            exit_reason = str(record.get("exit_reason") or "").strip()
            if valid_to is not None and valid_to <= valid_from:
                raise ValueError("membership valid_to must be later than valid_from")
            if (valid_to is None and exit_reason) or (valid_to is not None and not exit_reason):
                raise ValueError(
                    "open membership must have no exit_reason; closed membership requires one"
                )
            valid_from_evidence_id, valid_to_evidence_id = interval_evidence(
                record, valid_to, "exchange membership"
            )
            memberships.append({
                "security_id": security_id,
                "exchange": _required_text(record, "exchange").upper(),
                "valid_from": valid_from,
                "valid_to": valid_to,
                "entry_reason": _required_text(record, "entry_reason"),
                "exit_reason": exit_reason,
                "valid_from_evidence_id": valid_from_evidence_id,
                "valid_to_evidence_id": valid_to_evidence_id,
            })
        if not memberships:
            raise ValueError("security reference must contain at least one membership interval")
        memberships.sort(key=lambda item: (
            item["exchange"], item["security_id"], item["valid_from"]
        ))
        _validate_non_overlapping_intervals(
            memberships,
            ("security_id", "exchange"),
            label="exchange membership",
        )

        memberships_by_security_exchange: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for membership in memberships:
            key = (membership["security_id"], membership["exchange"])
            memberships_by_security_exchange.setdefault(key, []).append(membership)
        for alias in aliases:
            spans = memberships_by_security_exchange.get(
                (alias["security_id"], alias["exchange"]), []
            )
            alias_start = date.fromisoformat(alias["valid_from"]).toordinal()
            alias_end = (
                date.fromisoformat(alias["valid_to"]).toordinal()
                if alias["valid_to"] else date.max.toordinal() + 1
            )
            contained = any(
                alias_start >= date.fromisoformat(span["valid_from"]).toordinal()
                and alias_end <= (
                    date.fromisoformat(span["valid_to"]).toordinal()
                    if span["valid_to"] else date.max.toordinal() + 1
                )
                for span in spans
            )
            if not contained:
                raise ValueError(
                    "code alias interval must be contained in a matching exchange membership"
                )

        imported_at = str(imported_at or _utc_now_text())
        revision_evidence = [
            {key: value for key, value in item.items() if key != "accessed_at"}
            for item in evidence
        ]
        revision = _revision("security_reference", {
            "dataset_id": dataset_id,
            "source": source,
            "evidence_level": evidence_level,
            "coverage_status": coverage_status,
            "coverage": coverage,
            "warnings": warnings,
            "securities": securities,
            "evidence": revision_evidence,
            "aliases": aliases,
            "names": names,
            "memberships": memberships,
        })

        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO security_reference_imports(
                    revision, dataset_id, source, evidence_level, coverage_status,
                    coverage_json, warnings_json, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision,
                    dataset_id,
                    source,
                    evidence_level,
                    coverage_status,
                    json.dumps(coverage, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    json.dumps(warnings, ensure_ascii=False, separators=(",", ":")),
                    imported_at,
                ),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO security_entities(
                    revision, security_id, instrument_type
                ) VALUES (?, ?, ?)
                """,
                (
                    (revision, item["security_id"], item["instrument_type"])
                    for item in securities
                ),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO security_reference_evidence(
                    revision, evidence_id, publisher, title, source_url,
                    document_date, accessed_at, evidence_level, content_sha256, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        revision,
                        item["evidence_id"],
                        item["publisher"],
                        item["title"],
                        item["source_url"],
                        item["document_date"],
                        item["accessed_at"],
                        item["evidence_level"],
                        item["content_sha256"],
                        item["notes"],
                    )
                    for item in evidence
                ),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO security_aliases(
                    revision, security_id, exchange, code, valid_from, valid_to,
                    valid_from_evidence_id, valid_to_evidence_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        revision,
                        item["security_id"],
                        item["exchange"],
                        item["code"],
                        item["valid_from"],
                        item["valid_to"],
                        item["valid_from_evidence_id"],
                        item["valid_to_evidence_id"],
                    )
                    for item in aliases
                ),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO security_names(
                    revision, security_id, name, valid_from, valid_to,
                    valid_from_evidence_id, valid_to_evidence_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        revision,
                        item["security_id"],
                        item["name"],
                        item["valid_from"],
                        item["valid_to"],
                        item["valid_from_evidence_id"],
                        item["valid_to_evidence_id"],
                    )
                    for item in names
                ),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO exchange_memberships(
                    revision, security_id, exchange, valid_from, valid_to,
                    entry_reason, exit_reason, valid_from_evidence_id,
                    valid_to_evidence_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        revision,
                        item["security_id"],
                        item["exchange"],
                        item["valid_from"],
                        item["valid_to"],
                        item["entry_reason"],
                        item["exit_reason"],
                        item["valid_from_evidence_id"],
                        item["valid_to_evidence_id"],
                    )
                    for item in memberships
                ),
            )
            connection.execute(
                """
                INSERT INTO security_reference_heads(dataset_id, source_revision)
                VALUES (?, ?)
                ON CONFLICT(dataset_id) DO UPDATE
                SET source_revision = excluded.source_revision
                """,
                (dataset_id, revision),
            )
        return {
            "available": True,
            "dataset_id": dataset_id,
            "revision": revision,
            "source": source,
            "evidence_level": evidence_level,
            "coverage_status": coverage_status,
            "coverage": coverage,
            "warnings": warnings,
            "counts": {
                "securities": len(securities),
                "aliases": len(aliases),
                "names": len(names),
                "memberships": len(memberships),
                "evidence": len(evidence),
            },
            "imported_at": imported_at,
        }

    def security_reference_as_of(
        self,
        value: str | date | datetime,
        *,
        dataset_id: str = "A_SHARE_HISTORY",
        revision: str | None = None,
    ) -> dict[str, Any]:
        """Project exchange membership and its active exchange-local code at a date."""

        target = _normalize_date(value)
        normalized_dataset_id = str(dataset_id or "").strip().upper()
        self.initialize()
        with self._connect() as connection:
            if revision:
                import_row = connection.execute(
                    "SELECT * FROM security_reference_imports WHERE revision = ? AND dataset_id = ?",
                    (str(revision), normalized_dataset_id),
                ).fetchone()
            else:
                import_row = connection.execute(
                    """
                    SELECT sri.*
                    FROM security_reference_heads srh
                    JOIN security_reference_imports sri
                      ON sri.revision = srh.source_revision
                    WHERE srh.dataset_id = ?
                    """,
                    (normalized_dataset_id,),
                ).fetchone()
            if import_row is None:
                return {
                    "available": False,
                    "dataset_id": normalized_dataset_id,
                    "requested_as_of": target,
                    "resolved_as_of": "",
                    "revision": "",
                    "members": [],
                    "member_count": 0,
                    "issues": ["reference_revision_unavailable"],
                    "historical_research_eligible": False,
                }

            coverage = json.loads(str(import_row["coverage_json"] or "{}"))
            coverage_start = str(coverage.get("coverage_start") or "")
            coverage_end = str(coverage.get("coverage_end") or "")
            in_coverage = bool(
                coverage_start and coverage_end and coverage_start <= target <= coverage_end
            )
            memberships = []
            if in_coverage:
                memberships = connection.execute(
                    """
                    SELECT em.security_id, em.exchange, em.valid_from, em.valid_to,
                           em.entry_reason, em.exit_reason,
                           em.valid_from_evidence_id, em.valid_to_evidence_id,
                           (SELECT COUNT(*) FROM security_aliases sa
                            WHERE sa.revision = em.revision
                              AND sa.security_id = em.security_id
                              AND sa.exchange = em.exchange
                              AND sa.valid_from <= ?
                              AND (sa.valid_to IS NULL OR sa.valid_to > ?)) AS alias_count,
                           (SELECT sa.code FROM security_aliases sa
                            WHERE sa.revision = em.revision
                              AND sa.security_id = em.security_id
                              AND sa.exchange = em.exchange
                              AND sa.valid_from <= ?
                              AND (sa.valid_to IS NULL OR sa.valid_to > ?)
                            ORDER BY sa.valid_from DESC LIMIT 1) AS code,
                           (SELECT COUNT(*) FROM security_names sn
                            WHERE sn.revision = em.revision
                              AND sn.security_id = em.security_id
                              AND sn.valid_from <= ?
                              AND (sn.valid_to IS NULL OR sn.valid_to > ?)) AS name_count,
                           (SELECT sn.name FROM security_names sn
                            WHERE sn.revision = em.revision
                              AND sn.security_id = em.security_id
                              AND sn.valid_from <= ?
                              AND (sn.valid_to IS NULL OR sn.valid_to > ?)
                            ORDER BY sn.valid_from DESC LIMIT 1) AS name
                    FROM exchange_memberships em
                    WHERE em.revision = ?
                      AND em.valid_from <= ?
                      AND (em.valid_to IS NULL OR em.valid_to > ?)
                    ORDER BY em.exchange, em.security_id
                    """,
                    (
                        target, target, target, target, target, target, target, target,
                        str(import_row["revision"]), target, target,
                    ),
                ).fetchall()

        issues = []
        members = []
        for row in memberships:
            alias_count = int(row["alias_count"] or 0)
            name_count = int(row["name_count"] or 0)
            if alias_count != 1:
                issues.append({
                    "impact": "membership",
                    "kind": "missing_code_alias" if alias_count == 0 else "ambiguous_code_alias",
                    "security_id": str(row["security_id"]),
                    "exchange": str(row["exchange"]),
                })
            if name_count != 1:
                issues.append({
                    "impact": "display",
                    "kind": "missing_name" if name_count == 0 else "ambiguous_name",
                    "security_id": str(row["security_id"]),
                    "exchange": str(row["exchange"]),
                })
            members.append({
                "security_id": str(row["security_id"]),
                "exchange": str(row["exchange"]),
                "code": str(row["code"] or ""),
                "name": str(row["name"] or ""),
                "membership_valid_from": str(row["valid_from"]),
                "membership_valid_to": str(row["valid_to"] or ""),
                "entry_reason": str(row["entry_reason"]),
                "exit_reason": str(row["exit_reason"] or ""),
                "valid_from_evidence_id": str(row["valid_from_evidence_id"]),
                "valid_to_evidence_id": str(row["valid_to_evidence_id"] or ""),
            })

        blocking_gaps, informational_gaps, governance_gaps = _coverage_gaps(coverage)
        blocking_issues = [item for item in issues if item["impact"] == "membership"]
        if in_coverage and not members:
            blocking_issues.append({"impact": "membership", "kind": "empty_projection"})
        historical_ready = bool(
            in_coverage
            and str(import_row["coverage_status"]) in {"complete", "declared-complete"}
            and not blocking_gaps
            and not blocking_issues
        )
        return {
            "available": in_coverage,
            "dataset_id": normalized_dataset_id,
            "requested_as_of": target,
            "resolved_as_of": target if in_coverage else "",
            "reference_revision": str(import_row["revision"]),
            "source": str(import_row["source"]),
            "evidence_level": str(import_row["evidence_level"]),
            "coverage_status": str(import_row["coverage_status"]),
            "coverage": coverage,
            "warnings": json.loads(str(import_row["warnings_json"] or "[]")),
            "members": members,
            "member_count": len(members),
            "issues": issues,
            "blocking_gaps": blocking_gaps,
            "informational_gaps": informational_gaps,
            "governance_gaps": governance_gaps,
            "historical_research_eligible": historical_ready,
        }

    def security_reference_coverage_report(
        self,
        *,
        dataset_id: str = "A_SHARE_HISTORY",
        revision: str | None = None,
    ) -> dict[str, Any]:
        """Audit interval continuity and declared coverage for one reference revision."""

        normalized_dataset_id = str(dataset_id or "").strip().upper()
        self.initialize()
        with self._connect() as connection:
            if revision:
                import_row = connection.execute(
                    "SELECT * FROM security_reference_imports WHERE revision = ? AND dataset_id = ?",
                    (str(revision), normalized_dataset_id),
                ).fetchone()
            else:
                import_row = connection.execute(
                    """
                    SELECT sri.*
                    FROM security_reference_heads srh
                    JOIN security_reference_imports sri
                      ON sri.revision = srh.source_revision
                    WHERE srh.dataset_id = ?
                    """,
                    (normalized_dataset_id,),
                ).fetchone()
            if import_row is None:
                return {
                    "available": False,
                    "dataset_id": normalized_dataset_id,
                    "revision": "",
                    "historical_research_eligible": False,
                    "issues": ["reference_revision_unavailable"],
                }
            ref_revision = str(import_row["revision"])
            coverage = json.loads(str(import_row["coverage_json"] or "{}"))
            coverage_start = date.fromisoformat(str(coverage["coverage_start"]))
            coverage_end = date.fromisoformat(str(coverage["coverage_end"]))
            entities_count = int(connection.execute(
                "SELECT COUNT(*) FROM security_entities WHERE revision = ?",
                (ref_revision,),
            ).fetchone()[0])
            alias_rows = connection.execute(
                """SELECT security_id, exchange, code, valid_from, valid_to
                   FROM security_aliases WHERE revision = ?
                   ORDER BY security_id, exchange, valid_from""",
                (ref_revision,),
            ).fetchall()
            memberships = connection.execute(
                """SELECT security_id, exchange, valid_from, valid_to
                   FROM exchange_memberships WHERE revision = ?
                   ORDER BY security_id, exchange, valid_from""",
                (ref_revision,),
            ).fetchall()
            names_count = int(connection.execute(
                "SELECT COUNT(*) FROM security_names WHERE revision = ?",
                (ref_revision,),
            ).fetchone()[0])
            evidence_count = int(connection.execute(
                "SELECT COUNT(*) FROM security_reference_evidence WHERE revision = ?",
                (ref_revision,),
            ).fetchone()[0])

        aliases_by_membership: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in alias_rows:
            key = (str(row["security_id"]), str(row["exchange"]))
            aliases_by_membership.setdefault(key, []).append(dict(row))
        issues = []
        for membership in memberships:
            key = (str(membership["security_id"]), str(membership["exchange"]))
            window_start = max(
                date.fromisoformat(str(membership["valid_from"])), coverage_start
            ).toordinal()
            window_end = min(
                date.fromisoformat(str(membership["valid_to"])).toordinal()
                if membership["valid_to"] else date.max.toordinal() + 1,
                coverage_end.toordinal() + 1,
            )
            aliases_for_member = aliases_by_membership.get(key, [])
            cursor = window_start
            for alias in aliases_for_member:
                alias_start = date.fromisoformat(str(alias["valid_from"])).toordinal()
                alias_end = (
                    date.fromisoformat(str(alias["valid_to"])).toordinal()
                    if alias["valid_to"] else date.max.toordinal() + 1
                )
                clipped_start = max(alias_start, window_start)
                clipped_end = min(alias_end, window_end)
                if clipped_end <= window_start or clipped_start >= window_end:
                    continue
                if clipped_start > cursor:
                    issues.append({
                        "impact": "membership",
                        "kind": "code_alias_gap",
                        "security_id": key[0],
                        "exchange": key[1],
                        "gap_start": date.fromordinal(cursor).isoformat(),
                        "gap_end_exclusive": date.fromordinal(clipped_start).isoformat(),
                    })
                cursor = max(cursor, clipped_end)
            if cursor < window_end:
                issues.append({
                    "impact": "membership",
                    "kind": "code_alias_gap",
                    "security_id": key[0],
                    "exchange": key[1],
                    "gap_start": date.fromordinal(cursor).isoformat(),
                    "gap_end_exclusive": (
                        date.fromordinal(window_end).isoformat()
                        if window_end <= date.max.toordinal()
                        else ""
                    ),
                })

        blocking_gaps, informational_gaps, governance_gaps = _coverage_gaps(coverage)
        interval_blockers = [item for item in issues if item["impact"] == "membership"]
        historical_ready = bool(
            str(import_row["coverage_status"]) in {"complete", "declared-complete"}
            and not blocking_gaps
            and not interval_blockers
        )
        return {
            "available": True,
            "dataset_id": normalized_dataset_id,
            "revision": ref_revision,
            "source": str(import_row["source"]),
            "evidence_level": str(import_row["evidence_level"]),
            "coverage_status": str(import_row["coverage_status"]),
            "coverage": coverage,
            "warnings": json.loads(str(import_row["warnings_json"] or "[]")),
            "counts": {
                "securities": entities_count,
                "aliases": len(alias_rows),
                "names": names_count,
                "memberships": len(memberships),
                "evidence": evidence_count,
            },
            "blocking_gaps": blocking_gaps,
            "informational_gaps": informational_gaps,
            "governance_gaps": governance_gaps,
            "issues": issues,
            "historical_research_eligible": historical_ready,
        }

    def universe_as_of(
        self,
        value: str | date | datetime,
        *,
        allow_previous: bool = False,
    ) -> dict[str, Any]:
        requested_as_of = _normalize_date(value)
        self.initialize()
        with self._connect() as connection:
            if allow_previous:
                head = connection.execute(
                    "SELECT MAX(as_of) AS as_of FROM universe_heads WHERE as_of <= ?",
                    (requested_as_of,),
                ).fetchone()
                resolved_as_of = str(head["as_of"] or "") if head else ""
            else:
                resolved_as_of = requested_as_of
            import_row = connection.execute(
                """
                SELECT ui.*
                FROM universe_heads uh
                JOIN universe_imports ui ON ui.revision = uh.source_revision
                WHERE uh.as_of = ?
                """,
                (resolved_as_of,),
            ).fetchone()
            rows = []
            if import_row is not None:
                rows = connection.execute(
                    """
                    SELECT um.code, um.name, um.exchange, um.listing_status,
                           um.listing_date, um.delisting_date, um.member_source
                    FROM universe_members um
                    JOIN universe_heads uh
                      ON uh.as_of = um.as_of
                     AND uh.source_revision = um.source_revision
                    WHERE um.as_of = ?
                    ORDER BY um.code
                    """,
                    (resolved_as_of,),
                ).fetchall()
        members = [dict(row) for row in rows]
        return {
            "available": import_row is not None,
            "requested_as_of": requested_as_of,
            "resolved_as_of": resolved_as_of if import_row is not None else "",
            "exact_match": import_row is not None and resolved_as_of == requested_as_of,
            "fallback_used": import_row is not None and resolved_as_of != requested_as_of,
            "revision": str(import_row["revision"]) if import_row else "",
            "source": str(import_row["source"]) if import_row else "",
            "evidence_level": str(import_row["evidence_level"]) if import_row else "",
            "coverage_status": str(import_row["coverage_status"]) if import_row else "",
            "coverage": (
                json.loads(str(import_row["coverage_json"] or "{}"))
                if import_row else {}
            ),
            "warnings": (
                json.loads(str(import_row["warnings_json"] or "[]"))
                if import_row else []
            ),
            "imported_at": str(import_row["imported_at"]) if import_row else "",
            "member_count": len(members),
            "members": members,
        }

    def universe_coverage_report(
        self,
        value: str | date | datetime,
        *,
        allow_previous: bool = False,
    ) -> dict[str, Any]:
        """Summarize whether one universe snapshot is fit for current or historical use."""

        universe = self.universe_as_of(value, allow_previous=allow_previous)
        members = universe.get("members") or []
        fields = ("name", "exchange", "listing_date", "member_source")
        field_completeness = {}
        for field in fields:
            present = sum(1 for item in members if str(item.get(field) or "").strip())
            total = len(members)
            field_completeness[field] = {
                "present_count": present,
                "missing_count": total - present,
                "coverage_ratio": round(present / total, 6) if total else 0.0,
            }

        requested_as_of = universe.get("requested_as_of") or _normalize_date(value)
        temporal_errors = {
            "listed_after_as_of": sorted(
                item["code"] for item in members
                if item.get("listing_date") and item["listing_date"] > requested_as_of
            ),
            "delisted_on_or_before_as_of": sorted(
                item["code"] for item in members
                if item.get("delisting_date") and item["delisting_date"] <= requested_as_of
            ),
        }
        coverage = universe.get("coverage") or {}
        blocking_gaps, informational_gaps, governance_gaps = _coverage_gaps(coverage)
        current_membership_gaps = _current_membership_coverage_gaps(coverage)
        blocking_gaps = sorted(set(blocking_gaps).union(current_membership_gaps))
        temporal_error_count = sum(len(items) for items in temporal_errors.values())
        structural_valid = bool(
            universe.get("available")
            and universe.get("exact_match")
            and members
            and temporal_error_count == 0
            and field_completeness["exchange"]["missing_count"] == 0
            and field_completeness["member_source"]["missing_count"] == 0
            and not current_membership_gaps
        )
        historical_ready = bool(
            structural_valid
            and universe.get("coverage_status") in {"complete", "declared-complete"}
            and not blocking_gaps
        )
        return {
            "available": bool(universe.get("available")),
            "requested_as_of": requested_as_of,
            "resolved_as_of": universe.get("resolved_as_of") or "",
            "exact_match": bool(universe.get("exact_match")),
            "fallback_used": bool(universe.get("fallback_used")),
            "revision": universe.get("revision") or "",
            "source": universe.get("source") or "",
            "evidence_level": universe.get("evidence_level") or "",
            "coverage_status": universe.get("coverage_status") or "",
            "member_count": len(members),
            "exchange_counts": dict(sorted(Counter(
                str(item.get("exchange") or "unknown") for item in members
            ).items())),
            "member_source_counts": dict(sorted(Counter(
                str(item.get("member_source") or "unknown") for item in members
            ).items())),
            "field_completeness": field_completeness,
            "temporal_errors": temporal_errors,
            "coverage": coverage,
            "blocking_gaps": sorted(blocking_gaps),
            "informational_gaps": sorted(informational_gaps),
            "governance_gaps": sorted(governance_gaps),
            "warnings": list(universe.get("warnings") or []),
            "current_scan_eligible": structural_valid,
            "historical_research_eligible": historical_ready,
        }

    def status(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as connection:
            calendar_count = int(connection.execute(
                "SELECT COUNT(*) FROM calendar_heads"
            ).fetchone()[0])
            universe_snapshot_count = int(connection.execute(
                "SELECT COUNT(*) FROM universe_heads"
            ).fetchone()[0])
            latest = connection.execute(
                "SELECT MAX(as_of) AS as_of FROM universe_heads"
            ).fetchone()
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        return {
            "schema_version": user_version,
            "database_path": str(self.path),
            "calendar_count": calendar_count,
            "universe_snapshot_count": universe_snapshot_count,
            "latest_universe_as_of": str(latest["as_of"] or "") if latest else "",
            "database_size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }
