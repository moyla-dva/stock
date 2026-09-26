import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_analyzer.candidate_outcome_ledger import CandidateOutcomeLedger


def _report(context_revision="context-1", return_pct=2.0, history_revision="history-1", horizons=(1,)):
    observations = []
    for horizon in horizons:
        observations.append({
            "snapshot_day": "20260924",
            "rank": 1,
            "code": "600001",
            "name": "sample",
            "as_of": "2026-09-24",
            "horizon": horizon,
            "rank_score": 510.0,
            "history_data_source": "tencent",
            "history_data_revision": history_revision,
            "entry_date": "2026-09-25",
            "exit_date": "2026-09-25",
            "entry_price": 10.0,
            "exit_price": 10.2,
            "return_pct": return_pct,
            "mfe_pct": 3.0,
            "mae_pct": -1.0,
        })
    return {
        "strategy_version": "2026.09.20.1",
        "ranking_policy_version": "stock-structure-macro-only-v1",
        "pool": "opportunity",
        "start_key": "20250429",
        "entry_model": "next_session_open",
        "exit_model": "close_on_horizon_session_including_entry_session",
        "history_adjustment": "qfq",
        "max_rank": 100,
        "horizons": list(horizons),
        "day_reports": [{
            "snapshot_day": "20260924",
            "status": "evaluated",
            "context_revision": context_revision,
            "candidate_count": 3000,
            "requested_rank_count": 100,
            "candidates_with_any_outcome": 1,
        }],
        "observations": observations,
    }


class CandidateOutcomeLedgerTest(unittest.TestCase):
    def test_same_revision_is_idempotent_and_refreshes_observation(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite3"
            ledger = CandidateOutcomeLedger(path)
            ledger.upsert_report(_report(return_pct=2.0, history_revision="history-1"))
            status = ledger.upsert_report(_report(return_pct=3.5, history_revision="history-2"))
            with sqlite3.connect(path) as connection:
                run = connection.execute(
                    "SELECT refresh_count, observation_count FROM outcome_audit_runs"
                ).fetchone()
                observation = connection.execute(
                    "SELECT return_pct, history_data_revision FROM candidate_outcome_observations"
                ).fetchone()

        self.assertEqual(status["run_count"], 1)
        self.assertEqual(status["observation_count"], 1)
        self.assertEqual(run, (2, 1))
        self.assertEqual(observation, (3.5, "history-2"))

    def test_new_context_revision_preserves_separate_research_run(self):
        with TemporaryDirectory() as tmp:
            ledger = CandidateOutcomeLedger(Path(tmp) / "ledger.sqlite3")
            ledger.upsert_report(_report(context_revision="context-1"))
            status = ledger.upsert_report(_report(context_revision="context-2"))

        self.assertEqual(status["run_count"], 2)
        self.assertEqual(status["observation_count"], 2)

    def test_partial_horizon_refresh_preserves_existing_other_horizons(self):
        with TemporaryDirectory() as tmp:
            ledger = CandidateOutcomeLedger(Path(tmp) / "ledger.sqlite3")
            ledger.upsert_report(_report(horizons=(1, 3)))
            status = ledger.upsert_report(_report(horizons=(1,), return_pct=4.0))

        self.assertEqual(status["run_count"], 1)
        self.assertEqual(status["observation_count"], 2)
        self.assertEqual(status["horizons"], [1, 3])


if __name__ == "__main__":
    unittest.main()
