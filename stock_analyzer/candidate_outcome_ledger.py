"""Revision-aware SQLite ledger for candidate ranking event-study outcomes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


LEDGER_SCHEMA_VERSION = 1
DEFAULT_CANDIDATE_OUTCOME_LEDGER_PATH = (
    Path(__file__).resolve().parents[1]
    / ".cache"
    / "research"
    / "candidate_outcome_ledger.sqlite3"
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS outcome_audit_runs (
    run_key TEXT PRIMARY KEY,
    pool TEXT NOT NULL,
    snapshot_day TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    ranking_policy_version TEXT NOT NULL,
    context_revision TEXT NOT NULL,
    start_key TEXT NOT NULL,
    max_rank INTEGER NOT NULL,
    entry_model TEXT NOT NULL,
    exit_model TEXT NOT NULL,
    history_adjustment TEXT NOT NULL,
    status TEXT NOT NULL,
    skip_reason TEXT NOT NULL DEFAULT '',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    requested_rank_count INTEGER NOT NULL DEFAULT 0,
    candidates_with_any_outcome INTEGER NOT NULL DEFAULT 0,
    requested_horizons_json TEXT NOT NULL,
    observation_count INTEGER NOT NULL DEFAULT 0,
    first_recorded_at TEXT NOT NULL,
    refreshed_at TEXT NOT NULL,
    refresh_count INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS candidate_outcome_observations (
    run_key TEXT NOT NULL REFERENCES outcome_audit_runs(run_key) ON DELETE CASCADE,
    snapshot_day TEXT NOT NULL,
    rank INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    as_of TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    rank_score REAL,
    history_data_source TEXT NOT NULL,
    history_data_revision TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    return_pct REAL NOT NULL,
    mfe_pct REAL NOT NULL,
    mae_pct REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (run_key, rank, code, horizon)
);

CREATE INDEX IF NOT EXISTS idx_outcome_runs_day
    ON outcome_audit_runs(snapshot_day, pool, strategy_version);
CREATE INDEX IF NOT EXISTS idx_outcome_observations_horizon
    ON candidate_outcome_observations(horizon, snapshot_day);
"""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _run_identity(report: Mapping[str, Any], day_report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pool": str(report.get("pool") or ""),
        "snapshot_day": str(day_report.get("snapshot_day") or ""),
        "strategy_version": str(report.get("strategy_version") or ""),
        "ranking_policy_version": str(report.get("ranking_policy_version") or ""),
        "context_revision": str(day_report.get("context_revision") or ""),
        "start_key": str(report.get("start_key") or ""),
        "max_rank": int(report.get("max_rank") or 0),
        "entry_model": str(report.get("entry_model") or ""),
        "exit_model": str(report.get("exit_model") or ""),
        "history_adjustment": str(report.get("history_adjustment") or ""),
    }


def _run_key(identity: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(_json_text(identity).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class CandidateOutcomeLedger:
    def __init__(self, path: str | Path = DEFAULT_CANDIDATE_OUTCOME_LEDGER_PATH):
        self.path = Path(path).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > LEDGER_SCHEMA_VERSION:
                raise RuntimeError(
                    f"candidate outcome ledger schema {version} is newer than supported {LEDGER_SCHEMA_VERSION}"
                )
            connection.executescript(SCHEMA)
            connection.execute(f"PRAGMA user_version = {LEDGER_SCHEMA_VERSION}")

    def upsert_report(self, report: Mapping[str, Any]) -> dict[str, Any]:
        self.initialize()
        recorded_at = datetime.now().astimezone().isoformat()
        day_reports = {
            str(item.get("snapshot_day") or ""): item
            for item in report.get("day_reports") or []
            if isinstance(item, Mapping) and item.get("snapshot_day")
        }
        observations_by_day: dict[str, list[Mapping[str, Any]]] = {}
        for observation in report.get("observations") or []:
            if not isinstance(observation, Mapping):
                continue
            observations_by_day.setdefault(str(observation.get("snapshot_day") or ""), []).append(observation)

        runs_upserted = 0
        observations_upserted = 0
        with self._connect() as connection:
            for snapshot_day, day_report in day_reports.items():
                identity = _run_identity(report, day_report)
                run_key = _run_key(identity)
                connection.execute(
                    """
                    INSERT INTO outcome_audit_runs (
                        run_key, pool, snapshot_day, strategy_version,
                        ranking_policy_version, context_revision, start_key,
                        max_rank, entry_model, exit_model, history_adjustment,
                        status, skip_reason, candidate_count, requested_rank_count,
                        candidates_with_any_outcome, requested_horizons_json,
                        first_recorded_at, refreshed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_key) DO UPDATE SET
                        status = excluded.status,
                        skip_reason = excluded.skip_reason,
                        candidate_count = excluded.candidate_count,
                        requested_rank_count = excluded.requested_rank_count,
                        candidates_with_any_outcome = excluded.candidates_with_any_outcome,
                        requested_horizons_json = excluded.requested_horizons_json,
                        refreshed_at = excluded.refreshed_at,
                        refresh_count = outcome_audit_runs.refresh_count + 1
                    """,
                    (
                        run_key,
                        identity["pool"],
                        identity["snapshot_day"],
                        identity["strategy_version"],
                        identity["ranking_policy_version"],
                        identity["context_revision"],
                        identity["start_key"],
                        identity["max_rank"],
                        identity["entry_model"],
                        identity["exit_model"],
                        identity["history_adjustment"],
                        str(day_report.get("status") or "unknown"),
                        str(day_report.get("reason") or ""),
                        int(day_report.get("candidate_count") or 0),
                        int(day_report.get("requested_rank_count") or 0),
                        int(day_report.get("candidates_with_any_outcome") or 0),
                        _json_text(sorted({int(value) for value in report.get("horizons") or []})),
                        recorded_at,
                        recorded_at,
                    ),
                )
                runs_upserted += 1

                for observation in observations_by_day.get(snapshot_day, []):
                    connection.execute(
                        """
                        INSERT INTO candidate_outcome_observations (
                            run_key, snapshot_day, rank, code, name, as_of, horizon, rank_score,
                            history_data_source, history_data_revision,
                            entry_date, exit_date, entry_price, exit_price,
                            return_pct, mfe_pct, mae_pct, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(run_key, rank, code, horizon) DO UPDATE SET
                            name = excluded.name,
                            as_of = excluded.as_of,
                            rank_score = excluded.rank_score,
                            history_data_source = excluded.history_data_source,
                            history_data_revision = excluded.history_data_revision,
                            entry_date = excluded.entry_date,
                            exit_date = excluded.exit_date,
                            entry_price = excluded.entry_price,
                            exit_price = excluded.exit_price,
                            return_pct = excluded.return_pct,
                            mfe_pct = excluded.mfe_pct,
                            mae_pct = excluded.mae_pct,
                            recorded_at = excluded.recorded_at
                        """,
                        (
                            run_key,
                            snapshot_day,
                            int(observation.get("rank") or 0),
                            str(observation.get("code") or ""),
                            str(observation.get("name") or ""),
                            str(observation.get("as_of") or ""),
                            int(observation.get("horizon") or 0),
                            observation.get("rank_score"),
                            str(observation.get("history_data_source") or "unknown"),
                            str(observation.get("history_data_revision") or "unknown"),
                            str(observation.get("entry_date") or ""),
                            str(observation.get("exit_date") or ""),
                            float(observation.get("entry_price") or 0),
                            float(observation.get("exit_price") or 0),
                            float(observation.get("return_pct") or 0),
                            float(observation.get("mfe_pct") or 0),
                            float(observation.get("mae_pct") or 0),
                            recorded_at,
                        ),
                    )
                    observations_upserted += 1
                observation_count = int(connection.execute(
                    "SELECT COUNT(*) FROM candidate_outcome_observations WHERE run_key = ?",
                    (run_key,),
                ).fetchone()[0])
                connection.execute(
                    "UPDATE outcome_audit_runs SET observation_count = ? WHERE run_key = ?",
                    (observation_count, run_key),
                )
            connection.commit()
        return {
            "database_path": str(self.path),
            "schema_version": LEDGER_SCHEMA_VERSION,
            "runs_upserted": runs_upserted,
            "observations_upserted": observations_upserted,
            **self.status(),
        }

    def status(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as connection:
            run_count = int(connection.execute("SELECT COUNT(*) FROM outcome_audit_runs").fetchone()[0])
            observation_count = int(connection.execute(
                "SELECT COUNT(*) FROM candidate_outcome_observations"
            ).fetchone()[0])
            days = [
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT snapshot_day FROM outcome_audit_runs ORDER BY snapshot_day"
                )
            ]
            horizons = [
                int(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT horizon FROM candidate_outcome_observations ORDER BY horizon"
                )
            ]
        return {
            "run_count": run_count,
            "observation_count": observation_count,
            "snapshot_days": days,
            "horizons": horizons,
        }
