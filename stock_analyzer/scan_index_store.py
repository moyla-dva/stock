"""SQLite metadata index for scan snapshots, summaries, and ranking contexts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from stock_analyzer.candidate_reasons import CANDIDATE_REASON_TAGS
from stock_analyzer.candidate_read_model import (
    CANDIDATE_SUMMARY_SCHEMA_VERSION,
    CandidateSummary,
)
from stock_analyzer.scan_rank_context import (
    RANK_CONTEXT_SCHEMA_VERSION,
    RANKING_POLICY_VERSION,
)
from stock_analyzer.scan_snapshot_archive import DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR
from stock_analyzer.scan_snapshot_paths import discover_scan_snapshot_files
from stock_analyzer.scan_snapshot_storage import (
    STORAGE_TIER_ACTIVE,
    STORAGE_TIER_ARCHIVE,
    SnapshotStorageRecord,
    active_snapshot_record,
    discover_snapshot_storage,
    snapshot_storage_revision,
)


SCAN_INDEX_SCHEMA_VERSION = 9
SCAN_INDEX_BUILD_SCOPES = frozenset({"unknown", "partial", "full"})
RANK_CONTEXT_SCOPE_SNAPSHOT = "snapshot"
RANK_CONTEXT_SCOPE_LATEST_FRESH = "latest_fresh"
RANK_CONTEXT_SCOPES = frozenset({
    RANK_CONTEXT_SCOPE_SNAPSHOT,
    RANK_CONTEXT_SCOPE_LATEST_FRESH,
})
DEFAULT_SCAN_INDEX_PATH = Path(os.environ.get(
    "STOCK_ANALYZER_SCAN_INDEX_DB",
    Path(__file__).resolve().parents[1] / ".cache" / "scan_index.sqlite3",
))


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS scan_runs (
    run_key TEXT PRIMARY KEY,
    snapshot_day TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    data_adjust TEXT NOT NULL,
    latest_data_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'observed',
    snapshot_count INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_manifest (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    storage_tier TEXT NOT NULL DEFAULT 'active',
    archive_path TEXT NOT NULL DEFAULT '',
    archive_member TEXT NOT NULL DEFAULT '',
    archive_snapshot_revision TEXT NOT NULL DEFAULT '',
    archive_revision TEXT NOT NULL DEFAULT '',
    snapshot_version INTEGER NOT NULL DEFAULT 0,
    snapshot_revision TEXT NOT NULL DEFAULT '',
    strategy_version TEXT NOT NULL DEFAULT 'unknown',
    data_adjust TEXT NOT NULL DEFAULT 'unknown',
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    sector TEXT NOT NULL DEFAULT '',
    snapshot_day TEXT NOT NULL DEFAULT '',
    data_date TEXT NOT NULL DEFAULT '',
    row_count INTEGER NOT NULL DEFAULT 0,
    file_mtime_ns INTEGER NOT NULL DEFAULT 0,
    file_size INTEGER NOT NULL DEFAULT 0,
    parse_status TEXT NOT NULL DEFAULT 'ok',
    parse_error TEXT NOT NULL DEFAULT '',
    computed_scan_types_json TEXT,
    indexed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshot_manifest_day
    ON snapshot_manifest(snapshot_day, strategy_version, data_adjust);
CREATE INDEX IF NOT EXISTS idx_snapshot_manifest_code
    ON snapshot_manifest(code, snapshot_day DESC);
CREATE INDEX IF NOT EXISTS idx_snapshot_manifest_status
    ON snapshot_manifest(parse_status);
CREATE INDEX IF NOT EXISTS idx_snapshot_manifest_storage
    ON snapshot_manifest(storage_tier, snapshot_day);
CREATE TABLE IF NOT EXISTS candidate_summaries (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshot_manifest(id) ON DELETE CASCADE,
    schema_version INTEGER NOT NULL,
    strategy_version TEXT NOT NULL,
    code TEXT NOT NULL,
    as_of TEXT NOT NULL,
    bar_state TEXT NOT NULL,
    data_source TEXT NOT NULL,
    data_revision TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    calendar_id TEXT NOT NULL DEFAULT 'unknown',
    calendar_revision TEXT NOT NULL DEFAULT 'unknown',
    calendar_evidence_level TEXT NOT NULL DEFAULT 'unknown',
    snapshot_day TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL,
    snapshot_revision TEXT NOT NULL,
    strategy_status TEXT NOT NULL,
    name TEXT NOT NULL,
    pool TEXT NOT NULL,
    event_date TEXT NOT NULL,
    signal_key TEXT NOT NULL,
    signal_label TEXT NOT NULL,
    state TEXT NOT NULL,
    permission TEXT NOT NULL,
    plan_status TEXT NOT NULL,
    priority_score REAL,
    priority_group TEXT NOT NULL,
    reason_summary TEXT NOT NULL,
    missing_confirmations_json TEXT NOT NULL DEFAULT '[]',
    invalidation_price REAL,
    sector TEXT NOT NULL,
    concepts_json TEXT NOT NULL DEFAULT '[]',
    price REAL,
    final_score REAL,
    confirm_score REAL,
    risk_score REAL,
    profile_quality_label TEXT NOT NULL,
    profile_quality_score REAL,
    requires_trade_plan INTEGER NOT NULL DEFAULT 0,
    requires_stop_loss INTEGER NOT NULL DEFAULT 0,
    UNIQUE(snapshot_id, pool)
);

CREATE INDEX IF NOT EXISTS idx_candidate_pool_day_priority
    ON candidate_summaries(pool, snapshot_day DESC, priority_score DESC, code);
CREATE INDEX IF NOT EXISTS idx_candidate_code_day
    ON candidate_summaries(code, snapshot_day DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_signal
    ON candidate_summaries(signal_key, snapshot_day DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_sector
    ON candidate_summaries(sector, snapshot_day DESC);
"""


@dataclass
class ScanIndexBuildStats:
    discovered: int = 0
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    candidates: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _nullable_float(value: Any) -> float | None:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    return output if math.isfinite(output) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _rank_run_key(
    snapshot_day: str,
    strategy_version: str,
    start_key: str,
    context_scope: str = RANK_CONTEXT_SCOPE_SNAPSHOT,
) -> str:
    base = f"{snapshot_day}:{strategy_version}:{start_key}"
    if context_scope == RANK_CONTEXT_SCOPE_SNAPSHOT:
        return base
    return f"{base}:{context_scope}"


def _normalize_rank_context_scope(value: str | None) -> str:
    scope = str(value or RANK_CONTEXT_SCOPE_SNAPSHOT).strip().lower()
    if scope not in RANK_CONTEXT_SCOPES:
        raise ValueError(f"unknown contextual rank scope: {scope}")
    return scope


def _snapshot_filename_identity(path: Path) -> tuple[str, str, str]:
    parts = path.stem.split("_")
    code = parts[0] if parts else ""
    start_key = parts[1] if len(parts) >= 3 else "default"
    snapshot_day = parts[-1] if len(parts) >= 3 else ""
    return code, start_key, snapshot_day


class ScanIndexStore:
    """Persistent, rebuildable index over immutable scan snapshot files."""

    _initialize_lock = threading.RLock()

    def __init__(self, path: str | Path = DEFAULT_SCAN_INDEX_PATH):
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
        with self._initialize_lock:
            with self._connect() as connection:
                current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if current_version > SCAN_INDEX_SCHEMA_VERSION:
                    raise RuntimeError(
                        f"scan index schema {current_version} is newer than supported "
                        f"{SCAN_INDEX_SCHEMA_VERSION}"
                    )
                if current_version < 1:
                    connection.executescript(SCHEMA_V1)
                    connection.execute("PRAGMA user_version = 1")
                    current_version = 1
                if current_version < 2:
                    self._migrate_v1_to_v2(connection)
                    connection.execute("PRAGMA user_version = 2")
                    current_version = 2
                if current_version < 3:
                    self._migrate_v2_to_v3(connection)
                    connection.execute("PRAGMA user_version = 3")
                    current_version = 3
                if current_version < 4:
                    self._migrate_v3_to_v4(connection)
                    connection.execute("PRAGMA user_version = 4")
                    current_version = 4
                if current_version < 5:
                    self._migrate_v4_to_v5(connection)
                    connection.execute("PRAGMA user_version = 5")
                    current_version = 5
                if current_version < 6:
                    self._migrate_v5_to_v6(connection)
                    connection.execute("PRAGMA user_version = 6")
                    current_version = 6
                if current_version < 7:
                    self._migrate_v6_to_v7(connection)
                    connection.execute("PRAGMA user_version = 7")
                    current_version = 7
                if current_version < 8:
                    self._migrate_v7_to_v8(connection)
                    connection.execute("PRAGMA user_version = 8")
                    current_version = 8
                if current_version < 9:
                    self._migrate_v8_to_v9(connection)
                    connection.execute("PRAGMA user_version = 9")
                self._normalize_candidate_schema_versions(connection)

    @staticmethod
    def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
        for table in ("scan_runs", "snapshot_manifest", "candidate_summaries"):
            columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "start_key" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN start_key TEXT NOT NULL DEFAULT 'default'"
                )

        manifest_rows = connection.execute(
            "SELECT id, path FROM snapshot_manifest"
        ).fetchall()
        updates = []
        for row in manifest_rows:
            _, start_key, _ = _snapshot_filename_identity(Path(str(row["path"])))
            updates.append((start_key, int(row["id"])))
        if updates:
            connection.executemany(
                "UPDATE snapshot_manifest SET start_key = ? WHERE id = ?",
                updates,
            )
            connection.executemany(
                "UPDATE candidate_summaries SET start_key = ? WHERE snapshot_id = ?",
                updates,
            )
        connection.execute("DELETE FROM scan_runs")
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_candidate_pool_start_day_priority
                ON candidate_summaries(
                    pool, start_key, snapshot_day DESC, priority_score DESC, code
                )
            """
        )

    @staticmethod
    def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS index_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS candidate_concepts (
                candidate_id INTEGER NOT NULL
                    REFERENCES candidate_summaries(id) ON DELETE CASCADE,
                concept TEXT NOT NULL,
                PRIMARY KEY(candidate_id, concept)
            );
            CREATE INDEX IF NOT EXISTS idx_candidate_concepts_lookup
                ON candidate_concepts(concept, candidate_id);

            CREATE TABLE IF NOT EXISTS candidate_reason_tags (
                candidate_id INTEGER NOT NULL
                    REFERENCES candidate_summaries(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                PRIMARY KEY(candidate_id, tag)
            );
            CREATE INDEX IF NOT EXISTS idx_candidate_reason_tags_lookup
                ON candidate_reason_tags(tag, candidate_id);
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO candidate_concepts(candidate_id, concept)
            SELECT cs.id, CAST(item.value AS TEXT)
            FROM candidate_summaries cs, json_each(cs.concepts_json) AS item
            WHERE json_valid(cs.concepts_json) AND CAST(item.value AS TEXT) != ''
            """
        )
        candidate_count = int(
            connection.execute("SELECT COUNT(*) FROM candidate_summaries").fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO index_metadata(key, value)
            VALUES ('reason_tags_complete', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("0" if candidate_count else "1",),
        )

    @staticmethod
    def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(candidate_summaries)").fetchall()
        }
        for column in (
            "calendar_id",
            "calendar_revision",
            "calendar_evidence_level",
        ):
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE candidate_summaries ADD COLUMN {column} "
                    "TEXT NOT NULL DEFAULT 'unknown'"
                )

    @staticmethod
    def _normalize_candidate_schema_versions(connection: sqlite3.Connection) -> None:
        stale = connection.execute(
            "SELECT 1 FROM candidate_summaries WHERE schema_version != ? LIMIT 1",
            (CANDIDATE_SUMMARY_SCHEMA_VERSION,),
        ).fetchone()
        if stale is not None:
            connection.execute(
                "UPDATE candidate_summaries SET schema_version = ? "
                "WHERE schema_version != ?",
                (
                    CANDIDATE_SUMMARY_SCHEMA_VERSION,
                    CANDIDATE_SUMMARY_SCHEMA_VERSION,
                ),
            )

    @staticmethod
    def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS rank_context_runs (
                context_revision TEXT PRIMARY KEY,
                run_key TEXT NOT NULL,
                snapshot_day TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                start_key TEXT NOT NULL,
                source_fingerprint_json TEXT NOT NULL,
                status TEXT NOT NULL,
                candidate_count INTEGER NOT NULL,
                computed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rank_context_runs_identity
                ON rank_context_runs(snapshot_day, strategy_version, start_key, computed_at DESC);

            CREATE TABLE IF NOT EXISTS candidate_rank_contexts (
                context_revision TEXT NOT NULL
                    REFERENCES rank_context_runs(context_revision) ON DELETE CASCADE,
                candidate_id INTEGER NOT NULL
                    REFERENCES candidate_summaries(id) ON DELETE CASCADE,
                context_priority_score REAL,
                context_priority_group TEXT NOT NULL DEFAULT '',
                context_final_score REAL,
                sector_score REAL,
                concept_score REAL,
                market_boost REAL,
                PRIMARY KEY(context_revision, candidate_id)
            );
            CREATE INDEX IF NOT EXISTS idx_candidate_rank_context_priority
                ON candidate_rank_contexts(
                    context_revision, context_priority_score DESC,
                    context_final_score DESC, candidate_id
                );

            CREATE TABLE IF NOT EXISTS rank_context_heads (
                run_key TEXT PRIMARY KEY,
                context_revision TEXT NOT NULL
                    REFERENCES rank_context_runs(context_revision) ON DELETE CASCADE
            );
            """
        )

    @staticmethod
    def _migrate_v5_to_v6(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(candidate_rank_contexts)").fetchall()
        }
        if "environment_permission" not in columns:
            connection.execute(
                "ALTER TABLE candidate_rank_contexts ADD COLUMN "
                "environment_permission TEXT NOT NULL DEFAULT 'unknown'"
            )
        if "market_context_json" not in columns:
            connection.execute(
                "ALTER TABLE candidate_rank_contexts ADD COLUMN "
                "market_context_json TEXT NOT NULL DEFAULT '{}'"
            )

    @staticmethod
    def _migrate_v6_to_v7(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(snapshot_manifest)").fetchall()
        }
        if "computed_scan_types_json" not in columns:
            connection.execute(
                "ALTER TABLE snapshot_manifest ADD COLUMN computed_scan_types_json TEXT"
            )

    @staticmethod
    def _migrate_v7_to_v8(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_snapshot_manifest_planning
                ON snapshot_manifest(
                    snapshot_day, strategy_version, start_key,
                    parse_status, data_date, id
                )
            """
        )

    @staticmethod
    def _migrate_v8_to_v9(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(snapshot_manifest)").fetchall()
        }
        definitions = {
            "storage_tier": "TEXT NOT NULL DEFAULT 'active'",
            "archive_path": "TEXT NOT NULL DEFAULT ''",
            "archive_member": "TEXT NOT NULL DEFAULT ''",
            "archive_snapshot_revision": "TEXT NOT NULL DEFAULT ''",
            "archive_revision": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in definitions.items():
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE snapshot_manifest ADD COLUMN {column} {definition}"
                )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshot_manifest_storage "
            "ON snapshot_manifest(storage_tier, snapshot_day)"
        )

    def clear(self) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute("DELETE FROM rank_context_heads")
            connection.execute("DELETE FROM rank_context_runs")
            connection.execute("DELETE FROM candidate_summaries")
            connection.execute("DELETE FROM snapshot_manifest")
            connection.execute("DELETE FROM scan_runs")
            self._set_metadata(connection, "reason_tags_complete", "1")
            self._set_metadata(connection, "build_scope", "unknown")
            self._set_metadata(connection, "full_rebuild_source_snapshot_count", "0")
            self._set_metadata(connection, "full_rebuild_source_directory", "")
            self._set_metadata(connection, "full_rebuild_completed_at", "")
            self._set_metadata(connection, "source_sync_snapshot_count", "0")
            self._set_metadata(connection, "source_sync_directory", "")
            self._set_metadata(connection, "source_sync_archive_directory", "")
            self._set_metadata(connection, "source_sync_storage_revision", "")
            self._set_metadata(connection, "source_sync_active_snapshot_count", "0")
            self._set_metadata(connection, "source_sync_archive_snapshot_count", "0")
            self._set_metadata(connection, "source_sync_revision", "")
            self._set_metadata(connection, "source_sync_completed_at", "")
            self._set_metadata(connection, "snapshot_index_revision", uuid.uuid4().hex)

    def index_snapshot_files(
        self,
        paths: Iterable[str | Path],
        *,
        reset: bool = False,
        force: bool = False,
        batch_size: int = 500,
        progress_callback: Callable[[int, int, ScanIndexBuildStats], None] | None = None,
    ) -> ScanIndexBuildStats:
        """Index snapshot files, skipping unchanged files unless force is true."""

        records = []
        for value in paths:
            path = Path(value).expanduser().resolve()
            try:
                records.append(active_snapshot_record(path))
            except OSError:
                records.append(SnapshotStorageRecord(
                    logical_path=path,
                    storage_tier=STORAGE_TIER_ACTIVE,
                    size_bytes=0,
                    mtime_ns=0,
                ))
        return self.index_snapshot_records(
            records,
            reset=reset,
            force=force,
            batch_size=batch_size,
            progress_callback=progress_callback,
        )

    def index_snapshot_records(
        self,
        records: Iterable[SnapshotStorageRecord],
        *,
        reset: bool = False,
        force: bool = False,
        batch_size: int = 500,
        progress_callback: Callable[[int, int, ScanIndexBuildStats], None] | None = None,
    ) -> ScanIndexBuildStats:
        """Index logical snapshots from either active files or verified archives."""

        self.initialize()
        record_list = list(records)
        stats = ScanIndexBuildStats(discovered=len(record_list))
        batch_size = max(1, int(batch_size))

        with self._connect() as connection:
            if reset:
                connection.execute("DELETE FROM rank_context_heads")
                connection.execute("DELETE FROM rank_context_runs")
                connection.execute("DELETE FROM candidate_summaries")
                connection.execute("DELETE FROM snapshot_manifest")
                connection.execute("DELETE FROM scan_runs")
                self._set_metadata(connection, "reason_tags_complete", "0")
                self._set_metadata(connection, "build_scope", "partial")
                self._set_metadata(connection, "source_sync_revision", "")
                connection.commit()

            for position, record in enumerate(record_list, start=1):
                savepoint = f"snapshot_{position}"
                connection.execute(f"SAVEPOINT {savepoint}")
                try:
                    outcome, candidate_count = self._index_snapshot_record(
                        connection,
                        record,
                        force=force,
                    )
                except Exception as exc:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    self._upsert_error_manifest(connection, record, str(exc))
                    outcome, candidate_count = "failed", 0
                else:
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                if outcome == "indexed":
                    stats.indexed += 1
                    stats.candidates += candidate_count
                elif outcome == "skipped":
                    stats.skipped += 1
                else:
                    stats.failed += 1

                if position % batch_size == 0:
                    connection.commit()
                if progress_callback:
                    progress_callback(position, len(record_list), stats)

            self._refresh_scan_runs(connection)
            if reset:
                self._set_metadata(connection, "reason_tags_complete", "1")
            elif (
                record_list
                and self._metadata(connection, "build_scope", "unknown") == "unknown"
            ):
                self._set_metadata(connection, "build_scope", "partial")
            if reset or stats.indexed or stats.failed:
                self._set_metadata(connection, "snapshot_index_revision", uuid.uuid4().hex)
                self._set_metadata(connection, "source_sync_revision", "")
            connection.commit()
        return stats

    def record_build_scope(
        self,
        scope: str,
        *,
        source_snapshot_count: int | None = None,
        source_directory: str | Path | None = None,
        completed_at: str | None = None,
    ) -> None:
        """Record whether this rebuild covered the complete source snapshot set."""

        normalized_scope = str(scope or "unknown").strip().lower()
        if normalized_scope not in SCAN_INDEX_BUILD_SCOPES:
            raise ValueError(f"unknown scan index build scope: {normalized_scope}")
        self.initialize()
        with self._connect() as connection:
            self._set_metadata(connection, "build_scope", normalized_scope)
            if normalized_scope == "full":
                if source_snapshot_count is None:
                    raise ValueError("full build scope requires source_snapshot_count")
                self._set_metadata(
                    connection,
                    "full_rebuild_source_snapshot_count",
                    str(max(0, int(source_snapshot_count))),
                )
                self._set_metadata(
                    connection,
                    "full_rebuild_source_directory",
                    str(Path(source_directory).resolve()) if source_directory else "",
                )
                self._set_metadata(
                    connection,
                    "full_rebuild_completed_at",
                    str(completed_at or _utc_now_text()),
                )
                manifest_count = int(connection.execute(
                    "SELECT COUNT(*) FROM snapshot_manifest"
                ).fetchone()[0])
                if manifest_count != max(0, int(source_snapshot_count)):
                    raise ValueError(
                        "full build source count does not match indexed manifest count"
                    )
                revision = self._metadata(connection, "snapshot_index_revision", "")
                self._set_metadata(
                    connection,
                    "source_sync_snapshot_count",
                    str(manifest_count),
                )
                self._set_metadata(
                    connection,
                    "source_sync_directory",
                    str(Path(source_directory).resolve()) if source_directory else "",
                )
                self._set_metadata(connection, "source_sync_revision", revision)
                self._set_metadata(
                    connection,
                    "source_sync_completed_at",
                    str(completed_at or _utc_now_text()),
                )
            else:
                self._set_metadata(connection, "source_sync_revision", "")
            connection.commit()

    def reconcile_source_directory(
        self,
        source_directory: str | Path,
        *,
        archive_directory: str | Path | None = None,
        delete_missing: bool = True,
        apply_changes: bool = True,
    ) -> dict[str, Any]:
        """Reconcile manifest membership across active and archive storage tiers."""

        self.initialize()
        resolved_directory = str(Path(source_directory).resolve())
        resolved_archive_directory = str(Path(
            archive_directory or DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR
        ).expanduser().resolve())
        storage_records = discover_snapshot_storage(
            resolved_directory,
            resolved_archive_directory,
        )
        source_records = {str(record.logical_path): record for record in storage_records}
        source_paths = set(source_records)
        with self._connect() as connection:
            manifest_rows = connection.execute(
                "SELECT id, path, snapshot_revision, file_size, storage_tier, "
                "archive_path, archive_member, archive_snapshot_revision, archive_revision "
                "FROM snapshot_manifest"
            ).fetchall()
            manifest_by_path = {str(row["path"]): row for row in manifest_rows}
            manifest_paths = {
                path: int(row["id"]) for path, row in manifest_by_path.items()
            }
            missing_from_source = sorted(set(manifest_paths) - source_paths)
            missing_from_index = sorted(source_paths - set(manifest_paths))
            archive_mismatches = []
            blocking_archive_mismatches = []
            storage_updates = []
            for path in sorted(source_paths & set(manifest_paths)):
                record = source_records[path]
                row = manifest_by_path[path]
                archive_matches = bool(
                    not record.archive_snapshot_revision
                    or (
                        record.archive_snapshot_revision
                        == str(row["snapshot_revision"] or "")
                        and record.size_bytes == int(row["file_size"] or 0)
                    )
                )
                if not archive_matches:
                    archive_mismatches.append(path)
                    if record.storage_tier == STORAGE_TIER_ARCHIVE:
                        blocking_archive_mismatches.append(path)
                archive_path = str(record.archive_path or "") if archive_matches else ""
                archive_member = record.archive_member if archive_matches else ""
                archive_snapshot_revision = (
                    record.archive_snapshot_revision if archive_matches else ""
                )
                archive_revision = record.archive_revision if archive_matches else ""
                storage_tier = (
                    record.storage_tier
                    if record.storage_tier == STORAGE_TIER_ACTIVE or archive_matches
                    else str(row["storage_tier"] or STORAGE_TIER_ACTIVE)
                )
                desired = (
                    storage_tier,
                    archive_path,
                    archive_member,
                    archive_snapshot_revision,
                    archive_revision,
                )
                current = (
                    str(row["storage_tier"] or STORAGE_TIER_ACTIVE),
                    str(row["archive_path"] or ""),
                    str(row["archive_member"] or ""),
                    str(row["archive_snapshot_revision"] or ""),
                    str(row["archive_revision"] or ""),
                )
                if desired != current:
                    storage_updates.append((*desired, int(row["id"])))

            if apply_changes and storage_updates:
                connection.executemany(
                    """
                    UPDATE snapshot_manifest
                    SET storage_tier = ?, archive_path = ?, archive_member = ?,
                        archive_snapshot_revision = ?, archive_revision = ?
                    WHERE id = ?
                    """,
                    storage_updates,
                )
            deleted_count = 0
            if apply_changes and delete_missing and missing_from_source:
                connection.executemany(
                    "DELETE FROM snapshot_manifest WHERE id = ?",
                    [(manifest_paths[path],) for path in missing_from_source],
                )
                deleted_count = len(missing_from_source)
                connection.execute("DELETE FROM rank_context_heads")
                connection.execute("DELETE FROM rank_context_runs")
                self._refresh_scan_runs(connection)
                revision = uuid.uuid4().hex
                self._set_metadata(connection, "snapshot_index_revision", revision)
                manifest_paths = {
                    path: snapshot_id
                    for path, snapshot_id in manifest_paths.items()
                    if path not in set(missing_from_source)
                }
            else:
                revision = self._metadata(connection, "snapshot_index_revision", "")

            invalid_count = int(connection.execute(
                "SELECT COUNT(*) FROM snapshot_manifest WHERE parse_status != 'ok'"
            ).fetchone()[0])
            build_scope = self._metadata(connection, "build_scope", "unknown")
            synchronized = bool(
                build_scope == "full"
                and invalid_count == 0
                and not missing_from_index
                and (delete_missing or not missing_from_source)
                and not blocking_archive_mismatches
                and len(manifest_paths) == len(source_paths)
            )
            active_count = sum(
                record.storage_tier == STORAGE_TIER_ACTIVE for record in storage_records
            )
            archive_count = len(storage_records) - active_count
            storage_revision = snapshot_storage_revision(storage_records)
            if apply_changes and synchronized:
                completed_at = _utc_now_text()
                self._set_metadata(
                    connection,
                    "source_sync_snapshot_count",
                    str(len(source_paths)),
                )
                self._set_metadata(
                    connection,
                    "source_sync_directory",
                    resolved_directory,
                )
                self._set_metadata(
                    connection,
                    "source_sync_archive_directory",
                    resolved_archive_directory,
                )
                self._set_metadata(
                    connection,
                    "source_sync_storage_revision",
                    storage_revision,
                )
                self._set_metadata(
                    connection,
                    "source_sync_active_snapshot_count",
                    str(active_count),
                )
                self._set_metadata(
                    connection,
                    "source_sync_archive_snapshot_count",
                    str(archive_count),
                )
                self._set_metadata(connection, "source_sync_revision", revision)
                self._set_metadata(
                    connection,
                    "source_sync_completed_at",
                    completed_at,
                )
                self._set_metadata(
                    connection,
                    "full_rebuild_source_snapshot_count",
                    str(len(source_paths)),
                )
            elif apply_changes:
                self._set_metadata(connection, "source_sync_revision", "")
                self._set_metadata(connection, "source_sync_storage_revision", "")
            if apply_changes:
                connection.commit()
        return {
            "synchronized": synchronized,
            "source_snapshot_count": len(source_paths),
            "active_snapshot_count": active_count,
            "archive_snapshot_count": archive_count,
            "manifest_snapshot_count": len(manifest_paths),
            "missing_from_index_count": len(missing_from_index),
            "missing_from_source_count": len(missing_from_source),
            "archive_mismatch_count": len(archive_mismatches),
            "blocking_archive_mismatch_count": len(blocking_archive_mismatches),
            "archive_mismatch_paths": archive_mismatches[:20],
            "storage_update_count": len(storage_updates),
            "storage_revision": storage_revision,
            "deleted_manifest_count": deleted_count,
            "changes_applied": bool(apply_changes),
        }

    def cache_fingerprint(self, source_directory: str | Path) -> dict[str, Any]:
        """Return a cheap snapshot-index revision for cache invalidation."""

        self.initialize()
        resolved_directory = str(Path(source_directory).resolve())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN parse_status = 'error' THEN 1 ELSE 0 END) AS invalid,
                       SUM(CASE WHEN storage_tier = 'active' THEN 1 ELSE 0 END) AS active_count,
                       SUM(CASE WHEN storage_tier = 'archive' THEN 1 ELSE 0 END) AS archive_count,
                       MAX(snapshot_day) AS latest_snapshot_day,
                       MAX(indexed_at) AS latest_indexed_at
                FROM snapshot_manifest
                """
            ).fetchone()
            total = int(row["total"] or 0)
            invalid = int(row["invalid"] or 0)
            build_scope = self._metadata(connection, "build_scope", "unknown")
            expected_total = _safe_int(self._metadata(
                connection,
                "source_sync_snapshot_count",
                "0",
            ))
            indexed_directory = self._metadata(
                connection,
                "source_sync_directory",
                "",
            )
            revision = self._metadata(connection, "snapshot_index_revision", "")
            source_sync_revision = self._metadata(
                connection,
                "source_sync_revision",
                "",
            )
            source_sync_archive_directory = self._metadata(
                connection,
                "source_sync_archive_directory",
                "",
            )
            source_sync_storage_revision = self._metadata(
                connection,
                "source_sync_storage_revision",
                "",
            )
            incomplete_planning_count = int(connection.execute(
                "SELECT COUNT(*) FROM snapshot_manifest "
                "WHERE parse_status = 'ok' AND computed_scan_types_json IS NULL"
            ).fetchone()[0])
            if not revision:
                revision = hashlib.sha256(_json_text({
                    "total": total,
                    "invalid": invalid,
                    "indexed_at": str(row["latest_indexed_at"] or ""),
                    "snapshot_day": str(row["latest_snapshot_day"] or ""),
                }).encode("utf-8")).hexdigest()
                self._set_metadata(connection, "snapshot_index_revision", revision)
            connection.commit()
        complete = bool(
            build_scope == "full"
            and invalid == 0
            and total == expected_total
            and indexed_directory
            and str(Path(indexed_directory).resolve()) == resolved_directory
            and source_sync_revision == revision
        )
        return {
            "available": complete,
            "revision": revision,
            "snapshot_count": total,
            "latest_snapshot_day": str(row["latest_snapshot_day"] or ""),
            "invalid_snapshot_count": invalid,
            "build_scope": build_scope,
            "source_directory": indexed_directory,
            "source_sync_revision": source_sync_revision,
            "source_sync_archive_directory": source_sync_archive_directory,
            "source_sync_storage_revision": source_sync_storage_revision,
            "active_snapshot_count": int(row["active_count"] or 0),
            "archive_snapshot_count": int(row["archive_count"] or 0),
            "planning_metadata_complete": incomplete_planning_count == 0,
        }

    def scan_history_rows(
        self,
        *,
        start_key: str,
        scan_types: Iterable[str],
        current_strategy_version: str,
        current_data_adjust: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Aggregate historical snapshot days without reopening source JSON."""

        self.initialize()
        pools = tuple(dict.fromkeys(str(item) for item in scan_types if str(item)))
        # Day-level aggregation is small and the caller applies the display
        # limit. Returning every day preserves total-day and total-file counts.
        del limit
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT snapshot_day,
                       COUNT(*) AS snapshot_count,
                       SUM(CASE WHEN strategy_version = ? AND data_adjust = ? THEN 1 ELSE 0 END)
                           AS current_strategy_count,
                       SUM(CASE WHEN strategy_version = ? AND data_adjust = ? THEN 0 ELSE 1 END)
                           AS legacy_strategy_count,
                       MAX(data_date) AS latest_data_date
                FROM snapshot_manifest
                WHERE parse_status = 'ok' AND start_key = ? AND snapshot_day != ''
                GROUP BY snapshot_day
                ORDER BY snapshot_day DESC
                """,
                (
                    current_strategy_version,
                    current_data_adjust,
                    current_strategy_version,
                    current_data_adjust,
                    str(start_key),
                ),
            ).fetchall()
            days = [str(row["snapshot_day"] or "") for row in rows]
            pool_counts: dict[tuple[str, str], int] = {}
            if days and pools:
                day_placeholders = ",".join("?" for _ in days)
                pool_placeholders = ",".join("?" for _ in pools)
                count_rows = connection.execute(
                    f"""
                    SELECT sm.snapshot_day, cs.pool, COUNT(*) AS candidate_count
                    FROM candidate_summaries cs
                    JOIN snapshot_manifest sm ON sm.id = cs.snapshot_id
                    WHERE sm.parse_status = 'ok' AND sm.start_key = ?
                      AND sm.snapshot_day IN ({day_placeholders})
                      AND cs.pool IN ({pool_placeholders})
                    GROUP BY sm.snapshot_day, cs.pool
                    """,
                    (str(start_key), *days, *pools),
                ).fetchall()
                pool_counts = {
                    (str(row["snapshot_day"]), str(row["pool"])): int(row["candidate_count"] or 0)
                    for row in count_rows
                }
        return [
            {
                "snapshot_day": str(row["snapshot_day"] or ""),
                "snapshot_count": int(row["snapshot_count"] or 0),
                "current_strategy_count": int(row["current_strategy_count"] or 0),
                "legacy_strategy_count": int(row["legacy_strategy_count"] or 0),
                "latest_data_date": str(row["latest_data_date"] or "-"),
                "pool_counts": {
                    pool: pool_counts.get((str(row["snapshot_day"] or ""), pool), 0)
                    for pool in pools
                },
            }
            for row in rows
        ]

    @staticmethod
    def _rank_context_candidate_rows_for_connection(
        connection: sqlite3.Connection,
        *,
        snapshot_day: str,
        strategy_version: str,
        start_key: str,
        context_scope: str,
    ) -> list[sqlite3.Row]:
        scope = _normalize_rank_context_scope(context_scope)
        clauses = [
            "cs.snapshot_day = ?",
            "cs.strategy_version = ?",
            "cs.start_key = ?",
            "sm.parse_status = 'ok'",
        ]
        params: list[Any] = [snapshot_day, strategy_version, start_key]
        if scope == RANK_CONTEXT_SCOPE_LATEST_FRESH:
            eligible_dates = ScanIndexStore._recent_snapshot_data_dates(
                connection,
                snapshot_day=snapshot_day,
                strategy_version=strategy_version,
                start_key=start_key,
            )
            if not eligible_dates:
                return []
            placeholders = ", ".join("?" for _ in eligible_dates)
            clauses.append(f"sm.data_date IN ({placeholders})")
            params.extend(eligible_dates)
        return connection.execute(
            "SELECT cs.id, cs.pool, cs.code, cs.event_date "
            "FROM candidate_summaries cs "
            "JOIN snapshot_manifest sm ON sm.id = cs.snapshot_id "
            f"WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()

    def materialize_rank_context(
        self,
        *,
        snapshot_day: str,
        strategy_version: str,
        start_key: str,
        source_fingerprint: Mapping[str, Any],
        candidates: Iterable[Mapping[str, Any]],
        context_scope: str = RANK_CONTEXT_SCOPE_SNAPSHOT,
        computed_at: str | None = None,
    ) -> dict[str, Any]:
        """Atomically publish one complete contextual-ranking overlay."""

        self.initialize()
        normalized_day = str(snapshot_day or "").replace("-", "")
        normalized_strategy = str(strategy_version or "")
        normalized_start = str(start_key or "default")
        normalized_scope = _normalize_rank_context_scope(context_scope)
        if len(normalized_day) != 8 or not normalized_day.isdigit():
            raise ValueError("snapshot_day must use YYYYMMDD or YYYY-MM-DD")
        if not normalized_strategy:
            raise ValueError("strategy_version is required")

        normalized_candidates = []
        provided_by_key = {}
        for candidate in candidates:
            record = {
                "pool": str(candidate.get("pool") or ""),
                "code": str(candidate.get("code") or ""),
                "event_date": str(candidate.get("event_date") or ""),
                "context_priority_score": _nullable_float(
                    candidate.get("context_priority_score")
                ),
                "context_priority_group": str(
                    candidate.get("context_priority_group") or ""
                ),
                "context_final_score": _nullable_float(
                    candidate.get("context_final_score")
                ),
                "sector_score": _nullable_float(candidate.get("sector_score")),
                "concept_score": _nullable_float(candidate.get("concept_score")),
                "market_boost": _nullable_float(candidate.get("market_boost")),
                "environment_permission": str(
                    candidate.get("environment_permission") or "unknown"
                ),
                "market_context": (
                    dict(candidate.get("market_context"))
                    if isinstance(candidate.get("market_context"), Mapping)
                    else {}
                ),
            }
            key = (record["pool"], record["code"])
            if not all(key):
                raise ValueError("each contextual rank requires pool and code")
            if key in provided_by_key:
                raise ValueError(f"duplicate contextual rank: {key[0]}:{key[1]}")
            provided_by_key[key] = record
            normalized_candidates.append(record)

        fingerprint_json = json.dumps(
            dict(source_fingerprint),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        revision_payload = json.dumps(
            {
                "snapshot_day": normalized_day,
                "strategy_version": normalized_strategy,
                "start_key": normalized_start,
                "context_scope": normalized_scope,
                "source_fingerprint": json.loads(fingerprint_json),
                "candidates": sorted(
                    normalized_candidates,
                    key=lambda item: (item["pool"], item["code"]),
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        context_revision = f"sha256:{hashlib.sha256(revision_payload).hexdigest()}"
        run_key = _rank_run_key(
            normalized_day,
            normalized_strategy,
            normalized_start,
            normalized_scope,
        )
        computed_at = str(computed_at or _utc_now_text())

        with self._connect() as connection:
            rows = self._rank_context_candidate_rows_for_connection(
                connection,
                snapshot_day=normalized_day,
                strategy_version=normalized_strategy,
                start_key=normalized_start,
                context_scope=normalized_scope,
            )
            indexed_by_key = {
                (str(row["pool"]), str(row["code"])): row
                for row in rows
            }
            provided_keys = set(provided_by_key)
            indexed_keys = set(indexed_by_key)
            if provided_keys != indexed_keys:
                missing = sorted(indexed_keys - provided_keys)[:10]
                extra = sorted(provided_keys - indexed_keys)[:10]
                raise ValueError(
                    "contextual rank coverage mismatch: "
                    f"indexed={len(indexed_keys)}, provided={len(provided_keys)}, "
                    f"missing={missing}, extra={extra}"
                )
            for key, record in provided_by_key.items():
                indexed_event_date = str(indexed_by_key[key]["event_date"] or "")
                if record["event_date"] and record["event_date"] != indexed_event_date:
                    raise ValueError(
                        f"contextual rank event mismatch for {key[0]}:{key[1]}"
                    )

            connection.execute(
                """
                INSERT INTO rank_context_runs(
                    context_revision, run_key, snapshot_day, strategy_version,
                    start_key, source_fingerprint_json, status,
                    candidate_count, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'complete', ?, ?)
                ON CONFLICT(context_revision) DO UPDATE SET
                    source_fingerprint_json = excluded.source_fingerprint_json,
                    status = 'complete',
                    candidate_count = excluded.candidate_count,
                    computed_at = excluded.computed_at
                """,
                (
                    context_revision,
                    run_key,
                    normalized_day,
                    normalized_strategy,
                    normalized_start,
                    fingerprint_json,
                    len(indexed_keys),
                    computed_at,
                ),
            )
            connection.execute(
                "DELETE FROM candidate_rank_contexts WHERE context_revision = ?",
                (context_revision,),
            )
            if indexed_keys:
                connection.executemany(
                    """
                    INSERT INTO candidate_rank_contexts(
                        context_revision, candidate_id, context_priority_score,
                        context_priority_group, context_final_score,
                        sector_score, concept_score, market_boost,
                        environment_permission, market_context_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            context_revision,
                            int(indexed_by_key[key]["id"]),
                            record["context_priority_score"],
                            record["context_priority_group"],
                            record["context_final_score"],
                            record["sector_score"],
                            record["concept_score"],
                            record["market_boost"],
                            record["environment_permission"],
                            json.dumps(
                                record["market_context"],
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                                default=str,
                            ),
                        )
                        for key, record in provided_by_key.items()
                    ),
                )
            inserted_count = int(connection.execute(
                "SELECT COUNT(*) FROM candidate_rank_contexts WHERE context_revision = ?",
                (context_revision,),
            ).fetchone()[0])
            if inserted_count != len(indexed_keys):
                raise RuntimeError("contextual rank overlay insert is incomplete")
            connection.execute(
                """
                INSERT INTO rank_context_heads(run_key, context_revision)
                VALUES (?, ?)
                ON CONFLICT(run_key) DO UPDATE
                SET context_revision = excluded.context_revision
                """,
                (run_key, context_revision),
            )
            # The head switch and stale-revision cleanup share one transaction,
            # so readers never observe a missing contextual revision.
            connection.execute(
                """
                DELETE FROM rank_context_runs
                WHERE run_key = ? AND context_revision <> ?
                """,
                (run_key, context_revision),
            )

        return self.rank_context_status(
            snapshot_day=normalized_day,
            strategy_version=normalized_strategy,
            start_key=normalized_start,
            context_scope=normalized_scope,
        )

    @staticmethod
    def _rank_context_status_for_connection(
        connection: sqlite3.Connection,
        *,
        snapshot_day: str,
        strategy_version: str,
        start_key: str,
        context_scope: str = RANK_CONTEXT_SCOPE_SNAPSHOT,
    ) -> dict[str, Any]:
        scope = _normalize_rank_context_scope(context_scope)
        run_key = _rank_run_key(snapshot_day, strategy_version, start_key, scope)
        snapshot_candidate_count = int(connection.execute(
            """
            SELECT COUNT(*) FROM candidate_summaries
            WHERE snapshot_day = ? AND strategy_version = ? AND start_key = ?
            """,
            (snapshot_day, strategy_version, start_key),
        ).fetchone()[0])
        scoped_candidates = ScanIndexStore._rank_context_candidate_rows_for_connection(
            connection,
            snapshot_day=snapshot_day,
            strategy_version=strategy_version,
            start_key=start_key,
            context_scope=scope,
        )
        expected_scope_count = len(scoped_candidates)
        run = connection.execute(
            """
            SELECT r.*
            FROM rank_context_heads h
            JOIN rank_context_runs r ON r.context_revision = h.context_revision
            WHERE h.run_key = ?
            """,
            (run_key,),
        ).fetchone()
        if run is None:
            return {
                "available": False,
                "reason": "not_materialized",
                "run_key": run_key,
                "context_scope": scope,
                "context_revision": "",
                "candidate_count": expected_scope_count,
                "snapshot_candidate_count": snapshot_candidate_count,
                "overlay_count": 0,
            }
        overlay_rows = connection.execute(
            """
            SELECT cs.id
            FROM candidate_rank_contexts crc
            JOIN candidate_summaries cs ON cs.id = crc.candidate_id
            WHERE crc.context_revision = ?
              AND cs.snapshot_day = ? AND cs.strategy_version = ? AND cs.start_key = ?
            """,
            (
                str(run["context_revision"]),
                snapshot_day,
                strategy_version,
                start_key,
            ),
        ).fetchall()
        overlay_ids = {int(row["id"]) for row in overlay_rows}
        scoped_ids = {int(row["id"]) for row in scoped_candidates}
        overlay_count = len(overlay_ids)
        scope_matches = overlay_ids == scoped_ids
        expected_count = int(run["candidate_count"] or 0)
        source_fingerprint = json.loads(
            str(run["source_fingerprint_json"] or "{}")
        )
        policy_matches = (
            source_fingerprint.get("schema_version") == RANK_CONTEXT_SCHEMA_VERSION
            and source_fingerprint.get("ranking_policy_version") == RANKING_POLICY_VERSION
        )
        legacy_factor_count = int(connection.execute(
            """
            SELECT COUNT(*)
            FROM candidate_rank_contexts
            WHERE context_revision = ?
              AND (
                sector_score IS NOT NULL
                OR concept_score IS NOT NULL
                OR market_boost IS NOT NULL
                OR market_context_json != '{}'
              )
            """,
            (str(run["context_revision"]),),
        ).fetchone()[0])
        factors_match = legacy_factor_count == 0
        available = (
            str(run["status"]) == "complete"
            and scope_matches
            and expected_count == expected_scope_count
            and policy_matches
            and factors_match
        )
        reason = ""
        if not policy_matches:
            reason = "ranking_policy_mismatch"
        elif not factors_match:
            reason = "ranking_policy_violation"
        elif not available:
            reason = "incomplete"
        return {
            "available": available,
            "reason": reason,
            "run_key": run_key,
            "context_scope": scope,
            "context_revision": str(run["context_revision"]),
            "status": str(run["status"]),
            "candidate_count": expected_scope_count,
            "snapshot_candidate_count": snapshot_candidate_count,
            "expected_count": expected_count,
            "overlay_count": overlay_count,
            "scope_matches": scope_matches,
            "missing_overlay_count": len(scoped_ids - overlay_ids),
            "out_of_scope_overlay_count": len(overlay_ids - scoped_ids),
            "computed_at": str(run["computed_at"]),
            "source_fingerprint": source_fingerprint,
        }

    def rank_context_status(
        self,
        *,
        snapshot_day: str | None = None,
        strategy_version: str,
        start_key: str,
        context_scope: str = RANK_CONTEXT_SCOPE_SNAPSHOT,
    ) -> dict[str, Any]:
        self.initialize()
        with self._connect() as connection:
            resolved_day = self._resolve_snapshot_day(
                connection,
                snapshot_day=snapshot_day,
                strategy_version=strategy_version,
                start_key=start_key,
            )
            return self._rank_context_status_for_connection(
                connection,
                snapshot_day=resolved_day,
                strategy_version=strategy_version,
                start_key=start_key,
                context_scope=context_scope,
            )

    def prune_stale_rank_contexts(self) -> int:
        """Delete revisions that are no longer published by any context head."""

        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM rank_context_runs
                WHERE context_revision NOT IN (
                    SELECT context_revision FROM rank_context_heads
                )
                """
            )
            return max(0, int(cursor.rowcount or 0))

    def _index_snapshot_record(
        self,
        connection: sqlite3.Connection,
        record: SnapshotStorageRecord,
        *,
        force: bool,
    ) -> tuple[str, int]:
        path = record.logical_path
        resolved_path = str(path)

        existing = connection.execute(
            "SELECT file_mtime_ns, file_size, snapshot_revision, parse_status, storage_tier "
            "FROM snapshot_manifest WHERE path = ?",
            (resolved_path,),
        ).fetchone()
        if not force and existing is not None and existing["parse_status"] == "ok":
            if record.storage_tier == STORAGE_TIER_ACTIVE:
                unchanged = bool(
                    int(existing["file_mtime_ns"]) == record.mtime_ns
                    and int(existing["file_size"]) == record.size_bytes
                    and existing["storage_tier"] == STORAGE_TIER_ACTIVE
                )
            else:
                unchanged = bool(
                    str(existing["snapshot_revision"] or "") == record.content_revision
                    and int(existing["file_size"]) == record.size_bytes
                    and existing["storage_tier"] == STORAGE_TIER_ARCHIVE
                )
            if unchanged:
                return "skipped", 0

        try:
            raw = record.read_bytes()
            snapshot = json.loads(raw.decode("utf-8"))
            if not isinstance(snapshot, Mapping):
                raise ValueError("snapshot root must be an object")
            results = snapshot.get("results")
            if not isinstance(results, Mapping):
                raise ValueError("snapshot results must be an object")
        except Exception as exc:
            self._upsert_error_manifest(connection, record, str(exc))
            return "failed", 0

        snapshot_revision = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        if record.content_revision and snapshot_revision != record.content_revision:
            self._upsert_error_manifest(
                connection,
                record,
                "snapshot storage revision does not match archived content",
            )
            return "failed", 0
        _, start_key, _ = _snapshot_filename_identity(path)
        snapshot_id = self._upsert_snapshot_manifest(
            connection,
            record,
            snapshot,
            snapshot_revision,
        )
        connection.execute(
            "DELETE FROM candidate_summaries WHERE snapshot_id = ?",
            (snapshot_id,),
        )

        candidate_count = 0
        for pool in results:
            summary = CandidateSummary.from_snapshot(
                snapshot,
                str(pool),
                snapshot_revision=snapshot_revision,
                start_key=start_key,
            )
            if summary is None:
                continue
            self._insert_candidate(connection, snapshot_id, summary)
            candidate_count += 1
        return "indexed", candidate_count

    def _upsert_snapshot_manifest(
        self,
        connection: sqlite3.Connection,
        record: SnapshotStorageRecord,
        snapshot: Mapping[str, Any],
        snapshot_revision: str,
    ) -> int:
        path = record.logical_path
        resolved_path = str(path)
        _, start_key, _ = _snapshot_filename_identity(path)
        connection.execute(
            """
            INSERT INTO snapshot_manifest (
                path, storage_tier, archive_path, archive_member,
                archive_snapshot_revision, archive_revision,
                snapshot_version, snapshot_revision, strategy_version,
                data_adjust, code, name, sector, snapshot_day, start_key,
                data_date, row_count, file_mtime_ns, file_size, parse_status,
                parse_error, computed_scan_types_json, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', '', ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                storage_tier = excluded.storage_tier,
                archive_path = excluded.archive_path,
                archive_member = excluded.archive_member,
                archive_snapshot_revision = excluded.archive_snapshot_revision,
                archive_revision = excluded.archive_revision,
                snapshot_version = excluded.snapshot_version,
                snapshot_revision = excluded.snapshot_revision,
                strategy_version = excluded.strategy_version,
                data_adjust = excluded.data_adjust,
                code = excluded.code,
                name = excluded.name,
                sector = excluded.sector,
                snapshot_day = excluded.snapshot_day,
                start_key = excluded.start_key,
                data_date = excluded.data_date,
                row_count = excluded.row_count,
                file_mtime_ns = excluded.file_mtime_ns,
                file_size = excluded.file_size,
                parse_status = 'ok',
                parse_error = '',
                computed_scan_types_json = excluded.computed_scan_types_json,
                indexed_at = excluded.indexed_at
            """,
            (
                resolved_path,
                record.storage_tier,
                str(record.archive_path or ""),
                record.archive_member,
                record.archive_snapshot_revision,
                record.archive_revision,
                _safe_int(snapshot.get("version")),
                snapshot_revision,
                str(snapshot.get("strategy_version") or "unknown"),
                str(snapshot.get("data_adjust") or "unknown"),
                str(snapshot.get("code") or ""),
                str(snapshot.get("name") or ""),
                str(snapshot.get("sector") or ""),
                str(snapshot.get("snapshot_day") or ""),
                start_key,
                str(snapshot.get("data_date") or ""),
                _safe_int(snapshot.get("rows")),
                record.mtime_ns,
                record.size_bytes,
                _json_text(_string_list(snapshot.get("computed_scan_types"))),
                _utc_now_text(),
            ),
        )
        row = connection.execute(
            "SELECT id FROM snapshot_manifest WHERE path = ?",
            (resolved_path,),
        ).fetchone()
        return int(row["id"])

    def _upsert_error_manifest(
        self,
        connection: sqlite3.Connection,
        record: SnapshotStorageRecord,
        error: str,
    ) -> None:
        path = record.logical_path
        code, start_key, snapshot_day = _snapshot_filename_identity(path)
        resolved_path = str(path)
        connection.execute(
            """
            INSERT INTO snapshot_manifest (
                path, storage_tier, archive_path, archive_member,
                archive_snapshot_revision, archive_revision,
                code, snapshot_day, start_key, file_mtime_ns, file_size,
                parse_status, parse_error, computed_scan_types_json, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'error', ?, NULL, ?)
            ON CONFLICT(path) DO UPDATE SET
                storage_tier = excluded.storage_tier,
                archive_path = excluded.archive_path,
                archive_member = excluded.archive_member,
                archive_snapshot_revision = excluded.archive_snapshot_revision,
                archive_revision = excluded.archive_revision,
                code = excluded.code,
                snapshot_day = excluded.snapshot_day,
                start_key = excluded.start_key,
                file_mtime_ns = excluded.file_mtime_ns,
                file_size = excluded.file_size,
                parse_status = 'error',
                parse_error = excluded.parse_error,
                computed_scan_types_json = NULL,
                indexed_at = excluded.indexed_at
            """,
            (
                resolved_path,
                record.storage_tier,
                str(record.archive_path or ""),
                record.archive_member,
                record.archive_snapshot_revision,
                record.archive_revision,
                code,
                snapshot_day,
                start_key,
                record.mtime_ns,
                record.size_bytes,
                str(error)[:1000],
                _utc_now_text(),
            ),
        )
        row = connection.execute(
            "SELECT id FROM snapshot_manifest WHERE path = ?",
            (resolved_path,),
        ).fetchone()
        if row is not None:
            connection.execute(
                "DELETE FROM candidate_summaries WHERE snapshot_id = ?",
                (int(row["id"]),),
            )

    def _insert_candidate(
        self,
        connection: sqlite3.Connection,
        snapshot_id: int,
        summary: CandidateSummary,
    ) -> None:
        cursor = connection.execute(
            """
            INSERT INTO candidate_summaries (
                snapshot_id, schema_version, strategy_version, code, as_of,
                bar_state, data_source, data_revision, generated_at,
                calendar_id, calendar_revision, calendar_evidence_level,
                snapshot_day, snapshot_version, snapshot_revision,
                start_key, strategy_status, name, pool, event_date, signal_key,
                signal_label, state, permission, plan_status, priority_score,
                priority_group, reason_summary, missing_confirmations_json,
                invalidation_price, sector, concepts_json, price, final_score,
                confirm_score, risk_score, profile_quality_label,
                profile_quality_score, requires_trade_plan, requires_stop_loss
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                snapshot_id,
                summary.schema_version,
                summary.strategy_version,
                summary.code,
                summary.as_of,
                summary.bar_state,
                summary.data_source,
                summary.data_revision,
                summary.generated_at,
                summary.calendar_id,
                summary.calendar_revision,
                summary.calendar_evidence_level,
                summary.snapshot_day,
                summary.snapshot_version,
                summary.snapshot_revision,
                summary.start_key,
                summary.strategy_status,
                summary.name,
                summary.pool,
                summary.event_date,
                summary.signal_key,
                summary.signal_label,
                summary.state,
                summary.permission,
                summary.plan_status,
                summary.priority_score,
                summary.priority_group,
                summary.reason_summary,
                _json_text(summary.missing_confirmations),
                summary.invalidation_price,
                summary.sector,
                _json_text(summary.concepts),
                summary.price,
                summary.final_score,
                summary.confirm_score,
                summary.risk_score,
                summary.profile_quality_label,
                summary.profile_quality_score,
                int(summary.requires_trade_plan),
                int(summary.requires_stop_loss),
            ),
        )
        candidate_id = int(cursor.lastrowid)
        if summary.concepts:
            connection.executemany(
                "INSERT INTO candidate_concepts(candidate_id, concept) VALUES (?, ?)",
                ((candidate_id, concept) for concept in summary.concepts),
            )
        if summary.reason_tags:
            connection.executemany(
                "INSERT INTO candidate_reason_tags(candidate_id, tag) VALUES (?, ?)",
                ((candidate_id, tag) for tag in summary.reason_tags),
            )

    def _refresh_scan_runs(self, connection: sqlite3.Connection) -> None:
        refreshed_at = _utc_now_text()
        connection.execute("DELETE FROM scan_runs")
        connection.execute(
            """
            INSERT INTO scan_runs (
                run_key, snapshot_day, strategy_version, data_adjust, start_key,
                latest_data_date, status, snapshot_count, candidate_count,
                refreshed_at
            )
            SELECT
                sm.snapshot_day || ':' || sm.strategy_version || ':' || sm.data_adjust || ':' || sm.start_key,
                sm.snapshot_day,
                sm.strategy_version,
                sm.data_adjust,
                sm.start_key,
                MAX(sm.data_date),
                'observed',
                COUNT(DISTINCT sm.id),
                COUNT(cs.id),
                ?
            FROM snapshot_manifest sm
            LEFT JOIN candidate_summaries cs ON cs.snapshot_id = sm.id
            WHERE sm.parse_status = 'ok' AND sm.snapshot_day != ''
            GROUP BY sm.snapshot_day, sm.strategy_version, sm.data_adjust, sm.start_key
            """,
            (refreshed_at,),
        )

    @staticmethod
    def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            """
            INSERT INTO index_metadata(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(key), str(value)),
        )

    @staticmethod
    def _metadata(connection: sqlite3.Connection, key: str, default: str = "") -> str:
        row = connection.execute(
            "SELECT value FROM index_metadata WHERE key = ?",
            (str(key),),
        ).fetchone()
        return str(row["value"]) if row else default

    @staticmethod
    def _validate_reason(reason: str | None) -> str:
        value = str(reason or "").strip()
        if value and value not in CANDIDATE_REASON_TAGS:
            raise ValueError(f"unknown candidate reason: {value}")
        return value

    @staticmethod
    def _resolve_snapshot_day(
        connection: sqlite3.Connection,
        *,
        snapshot_day: str | None,
        strategy_version: str | None,
        start_key: str | None,
    ) -> str:
        if snapshot_day:
            return str(snapshot_day)
        clauses = []
        params: list[Any] = []
        if strategy_version:
            clauses.append("strategy_version = ?")
            params.append(str(strategy_version))
        if start_key:
            clauses.append("start_key = ?")
            params.append(str(start_key))
        sql = "SELECT MAX(snapshot_day) AS snapshot_day FROM scan_runs"
        if clauses:
            sql += f" WHERE {' AND '.join(clauses)}"
        row = connection.execute(sql, params).fetchone()
        return str(row["snapshot_day"] or "") if row else ""

    @staticmethod
    def _candidate_query_parts(
        *,
        pool: str,
        snapshot_day: str,
        strategy_version: str | None,
        start_key: str | None,
        sector: str | None,
        concept: str | None,
        signal_key: str | None,
        reason: str,
        query: str | None,
    ) -> tuple[list[str], list[Any]]:
        clauses = ["cs.pool = ?", "cs.snapshot_day = ?"]
        params: list[Any] = [str(pool), str(snapshot_day)]
        if strategy_version:
            clauses.append("cs.strategy_version = ?")
            params.append(str(strategy_version))
        if start_key:
            clauses.append("cs.start_key = ?")
            params.append(str(start_key))
        if sector:
            clauses.append("cs.sector = ?")
            params.append(str(sector))
        if concept:
            clauses.append(
                "EXISTS ("
                "SELECT 1 FROM candidate_concepts cc "
                "WHERE cc.candidate_id = cs.id AND cc.concept = ?"
                ")"
            )
            params.append(str(concept))
        if signal_key:
            clauses.append("cs.signal_key = ?")
            params.append(str(signal_key))
        if reason:
            clauses.append(
                "EXISTS ("
                "SELECT 1 FROM candidate_reason_tags rt "
                "WHERE rt.candidate_id = cs.id AND rt.tag = ?"
                ")"
            )
            params.append(reason)
        if query:
            clauses.append(
                "(cs.code LIKE ? ESCAPE '\\' OR cs.name LIKE ? ESCAPE '\\' "
                "OR cs.sector LIKE ? ESCAPE '\\' "
                "OR cs.signal_label LIKE ? ESCAPE '\\' "
                "OR cs.reason_summary LIKE ? ESCAPE '\\' "
                "OR EXISTS ("
                "SELECT 1 FROM candidate_concepts cq "
                "WHERE cq.candidate_id = cs.id AND cq.concept LIKE ? ESCAPE '\\'"
                "))"
            )
            escaped_query = (
                str(query).strip().replace("\\", "\\\\").replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped_query}%"
            params.extend([pattern, pattern, pattern, pattern, pattern, pattern])
        return clauses, params

    @staticmethod
    def _recent_snapshot_data_dates(
        connection: sqlite3.Connection,
        *,
        snapshot_day: str,
        strategy_version: str | None,
        start_key: str | None,
    ) -> tuple[str, ...]:
        from stock_analyzer.scan_snapshot import is_recent_snapshot

        clauses = ["snapshot_day = ?", "parse_status = 'ok'"]
        params: list[Any] = [str(snapshot_day)]
        if strategy_version:
            clauses.append("strategy_version = ?")
            params.append(str(strategy_version))
        if start_key:
            clauses.append("start_key = ?")
            params.append(str(start_key))
        rows = connection.execute(
            "SELECT DISTINCT snapshot_day, data_date FROM snapshot_manifest WHERE "
            + " AND ".join(clauses),
            params,
        ).fetchall()
        return tuple(sorted({
            str(row["data_date"] or "")
            for row in rows
            if is_recent_snapshot({
                "snapshot_day": str(row["snapshot_day"] or ""),
                "data_date": str(row["data_date"] or ""),
            })
        }))

    @staticmethod
    def _append_recent_snapshot_filter(
        clauses: list[str],
        params: list[Any],
        *,
        snapshot_day: str,
        strategy_version: str | None,
        start_key: str | None,
        eligible_data_dates: tuple[str, ...],
    ) -> None:
        if not eligible_data_dates:
            clauses.append("0 = 1")
            return
        manifest_clauses = ["sm.snapshot_day = ?", "sm.parse_status = 'ok'"]
        manifest_params: list[Any] = [str(snapshot_day)]
        if strategy_version:
            manifest_clauses.append("sm.strategy_version = ?")
            manifest_params.append(str(strategy_version))
        if start_key:
            manifest_clauses.append("sm.start_key = ?")
            manifest_params.append(str(start_key))
        placeholders = ", ".join("?" for _ in eligible_data_dates)
        manifest_clauses.append(f"sm.data_date IN ({placeholders})")
        manifest_params.extend(eligible_data_dates)
        clauses.append(
            "cs.snapshot_id IN (SELECT sm.id FROM snapshot_manifest sm WHERE "
            + " AND ".join(manifest_clauses)
            + ")"
        )
        params.extend(manifest_params)

    def _query_candidate_rows(
        self,
        connection: sqlite3.Connection,
        clauses: list[str],
        params: list[Any],
        *,
        limit: int,
        offset: int,
        context_revision: str = "",
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        safe_offset = max(0, int(offset))
        context_select = ""
        context_join = ""
        query_params = list(params)
        if context_revision:
            context_select = """,
                crc.context_revision AS rank_context_revision,
                crc.context_priority_score,
                crc.context_priority_group,
                crc.context_final_score,
                crc.sector_score AS rank_context_sector_score,
                crc.concept_score AS rank_context_concept_score,
                crc.market_boost AS rank_context_market_boost,
                crc.environment_permission AS rank_context_environment_permission,
                crc.market_context_json AS rank_context_market_context_json
            """
            context_join = (
                "LEFT JOIN candidate_rank_contexts crc "
                "ON crc.candidate_id = cs.id AND crc.context_revision = ?"
            )
            query_params.insert(0, context_revision)
            order_by = """
                CASE WHEN cs.strategy_status = 'current' THEN 0 ELSE 1 END,
                crc.context_priority_score IS NULL,
                crc.context_priority_score DESC,
                crc.context_final_score DESC,
                cs.priority_score IS NULL,
                cs.priority_score DESC,
                cs.final_score DESC,
                cs.event_date DESC,
                cs.code DESC
            """
        else:
            order_by = """
                CASE WHEN cs.strategy_status = 'current' THEN 0 ELSE 1 END,
                cs.priority_score IS NULL,
                cs.priority_score DESC,
                cs.final_score DESC,
                cs.event_date DESC,
                cs.code DESC
            """
        sql = f"""
            SELECT
                cs.*,
                sm.path AS snapshot_path,
                COALESCE((
                    SELECT json_group_array(rt.tag)
                    FROM candidate_reason_tags rt
                    WHERE rt.candidate_id = cs.id
                ), '[]') AS reason_tags_json
                {context_select}
            FROM candidate_summaries cs
            JOIN snapshot_manifest sm ON sm.id = cs.snapshot_id
            {context_join}
            WHERE {' AND '.join(clauses)}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """
        rows = connection.execute(
            sql,
            [*query_params, safe_limit, safe_offset],
        ).fetchall()
        return [self._candidate_row_to_dict(row) for row in rows]

    def query_candidates(
        self,
        *,
        pool: str,
        snapshot_day: str | None = None,
        strategy_version: str | None = None,
        start_key: str | None = None,
        sector: str | None = None,
        concept: str | None = None,
        signal_key: str | None = None,
        reason: str | None = None,
        query: str | None = None,
        limit: int = 120,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.initialize()
        reason = self._validate_reason(reason)
        with self._connect() as connection:
            if reason and self._metadata(connection, "reason_tags_complete", "0") != "1":
                raise RuntimeError("candidate reason tags require a full index rebuild")
            resolved_day = self._resolve_snapshot_day(
                connection,
                snapshot_day=snapshot_day,
                strategy_version=strategy_version,
                start_key=start_key,
            )
            clauses, params = self._candidate_query_parts(
                pool=pool,
                snapshot_day=resolved_day,
                strategy_version=strategy_version,
                start_key=start_key,
                sector=sector,
                concept=concept,
                signal_key=signal_key,
                reason=reason,
                query=query,
            )
            return self._query_candidate_rows(
                connection,
                clauses,
                params,
                limit=limit,
                offset=offset,
            )

    def query_candidate_page(
        self,
        *,
        pool: str,
        snapshot_day: str | None = None,
        strategy_version: str | None = None,
        rank_context_strategy_version: str | None = None,
        start_key: str | None = None,
        sector: str | None = None,
        concept: str | None = None,
        signal_key: str | None = None,
        reason: str | None = None,
        query: str | None = None,
        limit: int = 120,
        offset: int = 0,
        rank_mode: str = "snapshot_local",
        recent_only: bool = False,
    ) -> dict[str, Any]:
        """Return a stable CandidateSummary page without loading snapshot JSON."""

        self.initialize()
        reason = self._validate_reason(reason)
        requested_rank_mode = str(rank_mode or "snapshot_local").strip().lower()
        if requested_rank_mode not in {"snapshot_local", "contextual"}:
            raise ValueError(f"unknown candidate rank mode: {requested_rank_mode}")
        safe_limit = max(1, min(int(limit), 1000))
        safe_offset = max(0, int(offset))
        with self._connect() as connection:
            if reason and self._metadata(connection, "reason_tags_complete", "0") != "1":
                raise RuntimeError("candidate reason tags require a full index rebuild")
            resolved_day = self._resolve_snapshot_day(
                connection,
                snapshot_day=snapshot_day,
                strategy_version=strategy_version,
                start_key=start_key,
            )
            eligible_data_dates = None
            if recent_only:
                eligible_data_dates = self._recent_snapshot_data_dates(
                    connection,
                    snapshot_day=resolved_day,
                    strategy_version=strategy_version,
                    start_key=start_key,
                )
            clauses, params = self._candidate_query_parts(
                pool=pool,
                snapshot_day=resolved_day,
                strategy_version=strategy_version,
                start_key=start_key,
                sector=sector,
                concept=concept,
                signal_key=signal_key,
                reason=reason,
                query=query,
            )
            if eligible_data_dates is not None:
                self._append_recent_snapshot_filter(
                    clauses,
                    params,
                    snapshot_day=resolved_day,
                    strategy_version=strategy_version,
                    start_key=start_key,
                    eligible_data_dates=eligible_data_dates,
                )
            rank_context = (
                self._rank_context_status_for_connection(
                    connection,
                    snapshot_day=resolved_day,
                    strategy_version=str(rank_context_strategy_version or strategy_version or ""),
                    start_key=str(start_key or "default"),
                    context_scope=(
                        RANK_CONTEXT_SCOPE_LATEST_FRESH
                        if recent_only
                        else RANK_CONTEXT_SCOPE_SNAPSHOT
                    ),
                )
                if requested_rank_mode == "contextual"
                else {
                    "available": False,
                    "reason": "not_requested",
                    "context_revision": "",
                }
            )
            effective_rank_mode = (
                "contextual"
                if requested_rank_mode == "contextual" and rank_context["available"]
                else "snapshot_local"
            )
            results = self._query_candidate_rows(
                connection,
                clauses,
                params,
                limit=safe_limit,
                offset=safe_offset,
                context_revision=(
                    rank_context["context_revision"]
                    if effective_rank_mode == "contextual"
                    else ""
                ),
            )
            count = int(connection.execute(
                f"SELECT COUNT(*) FROM candidate_summaries cs WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()[0])
            pool_clauses, pool_params = self._candidate_query_parts(
                pool=pool,
                snapshot_day=resolved_day,
                strategy_version=strategy_version,
                start_key=start_key,
                sector=None,
                concept=None,
                signal_key=None,
                reason="",
                query=None,
            )
            if eligible_data_dates is not None:
                self._append_recent_snapshot_filter(
                    pool_clauses,
                    pool_params,
                    snapshot_day=resolved_day,
                    strategy_version=strategy_version,
                    start_key=start_key,
                    eligible_data_dates=eligible_data_dates,
                )
            pool_count = int(connection.execute(
                f"SELECT COUNT(*) FROM candidate_summaries cs WHERE {' AND '.join(pool_clauses)}",
                pool_params,
            ).fetchone()[0])
            run_clauses = ["snapshot_day = ?"]
            run_params: list[Any] = [resolved_day]
            if strategy_version:
                run_clauses.append("strategy_version = ?")
                run_params.append(str(strategy_version))
            if start_key:
                run_clauses.append("start_key = ?")
                run_params.append(str(start_key))
            run = connection.execute(
                "SELECT MAX(latest_data_date) AS latest_data_date "
                f"FROM scan_runs WHERE {' AND '.join(run_clauses)}",
                run_params,
            ).fetchone()

        loaded_count = min(count, safe_offset + len(results))
        return {
            "source": "sqlite_index",
            "schema_version": SCAN_INDEX_SCHEMA_VERSION,
            "ranking": {
                "requested_mode": requested_rank_mode,
                "mode": effective_rank_mode,
                "score_field": (
                    "rank_context.priority_score"
                    if effective_rank_mode == "contextual"
                    else "priority_score"
                ),
                "context_applied": effective_rank_mode == "contextual",
                "context_strategy_version": (
                    str(rank_context_strategy_version or strategy_version or "")
                    if effective_rank_mode == "contextual"
                    else ""
                ),
                "context_coverage": (
                    "current_strategy_only"
                    if effective_rank_mode == "contextual" and not strategy_version
                    else "filtered_strategy"
                    if effective_rank_mode == "contextual"
                    else "none"
                ),
                "context_revision": (
                    rank_context.get("context_revision") or ""
                    if effective_rank_mode == "contextual"
                    else ""
                ),
                "fallback_reason": (
                    rank_context.get("reason") or ""
                    if requested_rank_mode == "contextual"
                    and effective_rank_mode != "contextual"
                    else ""
                ),
            },
            "scan_type": str(pool),
            "filters": {
                "sector": str(sector or ""),
                "concept": str(concept or ""),
                "query": str(query or ""),
                "reason": reason,
                "signal_key": str(signal_key or ""),
            },
            "offset": safe_offset,
            "limit": safe_limit,
            "count": count,
            "loaded_count": loaded_count,
            "has_more": loaded_count < count,
            "pool_count": pool_count,
            "results": results,
            "snapshot_day": resolved_day,
            "latest_data_date": str(run["latest_data_date"] or "") if run else "",
            "history_mode": bool(snapshot_day),
            "history_snapshot_day": resolved_day if snapshot_day else "",
        }

    def get_candidate_reference(
        self,
        *,
        pool: str,
        code: str,
        snapshot_day: str | None = None,
        strategy_version: str | None = None,
        start_key: str | None = None,
        event_date: str | None = None,
    ) -> dict[str, Any] | None:
        """Return an internal exact snapshot reference plus its public summary."""

        self.initialize()
        with self._connect() as connection:
            resolved_day = self._resolve_snapshot_day(
                connection,
                snapshot_day=snapshot_day,
                strategy_version=strategy_version,
                start_key=start_key,
            )
            clauses = ["cs.pool = ?", "cs.code = ?", "cs.snapshot_day = ?"]
            params: list[Any] = [str(pool), str(code), resolved_day]
            if strategy_version:
                clauses.append("cs.strategy_version = ?")
                params.append(str(strategy_version))
            if start_key:
                clauses.append("cs.start_key = ?")
                params.append(str(start_key))
            if event_date:
                clauses.append("cs.event_date = ?")
                params.append(str(event_date))
            row = connection.execute(
                f"""
                SELECT
                    cs.*,
                    sm.path AS snapshot_path,
                    sm.storage_tier AS snapshot_storage_tier,
                    sm.archive_path AS snapshot_archive_path,
                    sm.archive_member AS snapshot_archive_member,
                    sm.archive_revision AS snapshot_archive_revision,
                    COALESCE((
                        SELECT json_group_array(rt.tag)
                        FROM candidate_reason_tags rt
                        WHERE rt.candidate_id = cs.id
                    ), '[]') AS reason_tags_json
                FROM candidate_summaries cs
                JOIN snapshot_manifest sm ON sm.id = cs.snapshot_id
                WHERE {' AND '.join(clauses)}
                LIMIT 1
                """,
                params,
            ).fetchone()
        if row is None:
            return None
        return {
            "summary": self._candidate_row_to_dict(row),
            "snapshot_path": str(row["snapshot_path"]),
            "storage_tier": str(row["snapshot_storage_tier"] or STORAGE_TIER_ACTIVE),
            "archive_path": str(row["snapshot_archive_path"] or ""),
            "archive_member": str(row["snapshot_archive_member"] or ""),
            "archive_revision": str(row["snapshot_archive_revision"] or ""),
        }

    def latest_snapshot_day(
        self,
        *,
        strategy_version: str | None = None,
        start_key: str | None = None,
    ) -> str:
        self.initialize()
        sql = "SELECT MAX(snapshot_day) AS snapshot_day FROM scan_runs"
        clauses = []
        params: list[Any] = []
        if strategy_version:
            clauses.append("strategy_version = ?")
            params.append(str(strategy_version))
        if start_key:
            clauses.append("start_key = ?")
            params.append(str(start_key))
        if clauses:
            sql += f" WHERE {' AND '.join(clauses)}"
        with self._connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return str(row["snapshot_day"] or "") if row else ""

    def snapshot_storage_counts(self, snapshot_day: str) -> dict[str, int]:
        """Return manifest storage-tier counts for one snapshot day."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT storage_tier, COUNT(*) AS total
                FROM snapshot_manifest
                WHERE snapshot_day = ?
                GROUP BY storage_tier
                """,
                (str(snapshot_day),),
            ).fetchall()
        counts = {
            STORAGE_TIER_ACTIVE: 0,
            STORAGE_TIER_ARCHIVE: 0,
        }
        for row in rows:
            tier = str(row["storage_tier"] or "")
            if tier in counts:
                counts[tier] = int(row["total"] or 0)
        counts["total"] = counts[STORAGE_TIER_ACTIVE] + counts[STORAGE_TIER_ARCHIVE]
        return counts

    def planning_snapshot_rows(self, *, start_key: str) -> list[dict[str, Any]]:
        """Return manifest-only inputs needed by scan planning policy."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT code, snapshot_day, data_date, strategy_version, data_adjust,
                       computed_scan_types_json
                FROM snapshot_manifest
                WHERE parse_status = 'ok' AND start_key = ?
                ORDER BY code DESC, snapshot_day DESC, id DESC
                """,
                (str(start_key or "default"),),
            ).fetchall()
        snapshots = []
        for row in rows:
            try:
                computed_scan_types = json.loads(row["computed_scan_types_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                computed_scan_types = []
            snapshots.append({
                "code": str(row["code"] or ""),
                "snapshot_day": str(row["snapshot_day"] or ""),
                "data_date": str(row["data_date"] or ""),
                "strategy_version": str(row["strategy_version"] or "unknown"),
                "data_adjust": str(row["data_adjust"] or "unknown"),
                "computed_scan_types": (
                    list(computed_scan_types)
                    if isinstance(computed_scan_types, list)
                    else []
                ),
            })
        return snapshots

    def status(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as connection:
            manifest = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN parse_status = 'ok' THEN 1 ELSE 0 END) AS valid,
                    SUM(CASE WHEN parse_status = 'error' THEN 1 ELSE 0 END) AS invalid,
                    SUM(CASE WHEN storage_tier = 'active' THEN 1 ELSE 0 END) AS active_count,
                    SUM(CASE WHEN storage_tier = 'archive' THEN 1 ELSE 0 END) AS archive_count
                FROM snapshot_manifest
                """
            ).fetchone()
            candidate_count = int(connection.execute(
                "SELECT COUNT(*) FROM candidate_summaries"
            ).fetchone()[0])
            run_count = int(connection.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0])
            concept_count = int(connection.execute(
                "SELECT COUNT(*) FROM candidate_concepts"
            ).fetchone()[0])
            reason_tag_count = int(connection.execute(
                "SELECT COUNT(*) FROM candidate_reason_tags"
            ).fetchone()[0])
            rank_context_run_count = int(connection.execute(
                "SELECT COUNT(*) FROM rank_context_runs"
            ).fetchone()[0])
            rank_context_head_count = int(connection.execute(
                "SELECT COUNT(*) FROM rank_context_heads"
            ).fetchone()[0])
            rank_context_candidate_count = int(connection.execute(
                "SELECT COUNT(*) FROM candidate_rank_contexts"
            ).fetchone()[0])
            freshness = connection.execute(
                """
                SELECT
                    MAX(snapshot_day) AS latest_snapshot_day,
                    MAX(indexed_at) AS latest_indexed_at
                FROM snapshot_manifest
                WHERE parse_status = 'ok'
                """
            ).fetchone()
            reason_tags_complete = self._metadata(
                connection,
                "reason_tags_complete",
                "0",
            ) == "1"
            build_scope = self._metadata(connection, "build_scope", "unknown")
            if build_scope not in SCAN_INDEX_BUILD_SCOPES:
                build_scope = "unknown"
            full_rebuild_source_snapshot_count = _safe_int(self._metadata(
                connection,
                "full_rebuild_source_snapshot_count",
                "0",
            ))
            full_rebuild_source_directory = self._metadata(
                connection,
                "full_rebuild_source_directory",
                "",
            )
            full_rebuild_completed_at = self._metadata(
                connection,
                "full_rebuild_completed_at",
                "",
            )
            source_sync_snapshot_count = _safe_int(self._metadata(
                connection,
                "source_sync_snapshot_count",
                "0",
            ))
            source_sync_directory = self._metadata(
                connection,
                "source_sync_directory",
                "",
            )
            source_sync_archive_directory = self._metadata(
                connection,
                "source_sync_archive_directory",
                "",
            )
            source_sync_storage_revision = self._metadata(
                connection,
                "source_sync_storage_revision",
                "",
            )
            source_sync_revision = self._metadata(
                connection,
                "source_sync_revision",
                "",
            )
            source_sync_completed_at = self._metadata(
                connection,
                "source_sync_completed_at",
                "",
            )
            snapshot_index_revision = self._metadata(
                connection,
                "snapshot_index_revision",
                "",
            )
            incomplete_planning_count = int(connection.execute(
                "SELECT COUNT(*) FROM snapshot_manifest "
                "WHERE parse_status = 'ok' AND computed_scan_types_json IS NULL"
            ).fetchone()[0])
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        invalid_snapshot_count = int(manifest["invalid"] or 0)
        snapshot_count = int(manifest["total"] or 0)
        index_complete = bool(
            build_scope == "full"
            and invalid_snapshot_count == 0
            and source_sync_directory
            and source_sync_snapshot_count == snapshot_count
            and source_sync_revision
            and source_sync_revision == snapshot_index_revision
        )
        return {
            "schema_version": user_version,
            "database_path": str(self.path),
            "snapshot_count": snapshot_count,
            "valid_snapshot_count": int(manifest["valid"] or 0),
            "invalid_snapshot_count": invalid_snapshot_count,
            "candidate_count": candidate_count,
            "concept_membership_count": concept_count,
            "reason_tag_count": reason_tag_count,
            "reason_tags_complete": reason_tags_complete,
            "rank_context_run_count": rank_context_run_count,
            "rank_context_head_count": rank_context_head_count,
            "rank_context_candidate_count": rank_context_candidate_count,
            "build_scope": build_scope,
            "index_complete": index_complete,
            "full_rebuild_source_snapshot_count": full_rebuild_source_snapshot_count,
            "full_rebuild_source_directory": full_rebuild_source_directory,
            "full_rebuild_completed_at": full_rebuild_completed_at,
            "source_sync_snapshot_count": source_sync_snapshot_count,
            "source_sync_directory": source_sync_directory,
            "source_sync_archive_directory": source_sync_archive_directory,
            "source_sync_storage_revision": source_sync_storage_revision,
            "active_snapshot_count": int(manifest["active_count"] or 0),
            "archive_snapshot_count": int(manifest["archive_count"] or 0),
            "source_sync_revision": source_sync_revision,
            "source_sync_completed_at": source_sync_completed_at,
            "planning_metadata_complete": incomplete_planning_count == 0,
            "run_count": run_count,
            "latest_snapshot_day": str(freshness["latest_snapshot_day"] or ""),
            "latest_indexed_at": str(freshness["latest_indexed_at"] or ""),
            "database_size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

    @staticmethod
    def _candidate_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload.pop("id", None)
        payload.pop("snapshot_id", None)
        payload.pop("snapshot_path", None)
        payload.pop("snapshot_storage_tier", None)
        payload.pop("snapshot_archive_path", None)
        payload.pop("snapshot_archive_member", None)
        payload.pop("snapshot_archive_revision", None)
        payload["missing_confirmations"] = json.loads(
            payload.pop("missing_confirmations_json") or "[]"
        )
        reason_tags = json.loads(payload.pop("reason_tags_json") or "[]")
        reason_order = {tag: index for index, tag in enumerate(CANDIDATE_REASON_TAGS)}
        payload["reason_tags"] = sorted(
            reason_tags,
            key=lambda tag: reason_order.get(tag, len(reason_order)),
        )
        payload["concepts"] = json.loads(payload.pop("concepts_json") or "[]")
        payload["requires_trade_plan"] = bool(payload["requires_trade_plan"])
        payload["requires_stop_loss"] = bool(payload["requires_stop_loss"])
        context_revision = payload.pop("rank_context_revision", None)
        context_values = {
            "priority_score": payload.pop("context_priority_score", None),
            "priority_group": payload.pop("context_priority_group", None),
            "final_score": payload.pop("context_final_score", None),
            "sector_score": payload.pop("rank_context_sector_score", None),
            "concept_score": payload.pop("rank_context_concept_score", None),
            "market_boost": payload.pop("rank_context_market_boost", None),
            "environment_permission": payload.pop(
                "rank_context_environment_permission", "unknown"
            ),
        }
        try:
            market_context = json.loads(
                payload.pop("rank_context_market_context_json", "{}") or "{}"
            )
        except (TypeError, json.JSONDecodeError):
            market_context = {}
        context_values["market_context"] = (
            market_context if isinstance(market_context, dict) else {}
        )
        if context_revision:
            payload["rank_context"] = {
                "revision": context_revision,
                **context_values,
            }
        return payload
