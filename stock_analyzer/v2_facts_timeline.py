"""Incrementally reusable timeline adapter for V2 event facts."""

from collections import OrderedDict
from dataclasses import dataclass
import threading

import pandas as pd

from stock_analyzer.c_signal_v2_facts import build_c_signal_v2_event_facts


@dataclass(frozen=True)
class V2FactsPoint:
    idx: int
    latest: object
    facts: dict


@dataclass(frozen=True)
class V2FactsTimeline:
    start_idx: int
    previous_facts: dict
    points: tuple
    built_count: int = 0
    reused_count: int = 0


@dataclass(frozen=True)
class _V2FactsTimelineCacheEntry:
    schema_fingerprint: tuple
    row_hashes: tuple
    facts_by_idx: dict


class V2FactsTimelineCache:
    """Reuse facts for an unchanged frame prefix across appended-bar requests."""

    def __init__(self, max_entries=24):
        self.max_entries = max(1, int(max_entries))
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _row_hashes(frame):
        if frame is None or frame.empty:
            return tuple()
        try:
            values = pd.util.hash_pandas_object(frame, index=False)
        except Exception:
            return None
        return tuple(int(value) for value in values.tolist())

    @staticmethod
    def _schema_fingerprint(frame):
        if frame is None:
            return tuple()
        return tuple(
            (str(column), str(dtype))
            for column, dtype in zip(frame.columns, frame.dtypes)
        )

    def known_facts(self, scope, frame):
        """Return facts whose complete input prefix is unchanged."""

        if not scope:
            return {}
        row_hashes = self._row_hashes(frame)
        if row_hashes is None:
            return {}
        with self._lock:
            entry = self._entries.get(str(scope))
            if entry is None:
                return {}
            self._entries.move_to_end(str(scope))
        if entry.schema_fingerprint != self._schema_fingerprint(frame):
            return {}
        common_length = 0
        for previous, current in zip(entry.row_hashes, row_hashes):
            if previous != current:
                break
            common_length += 1
        return {
            idx: facts
            for idx, facts in entry.facts_by_idx.items()
            if idx < common_length
        }

    def store(self, scope, frame, timeline):
        if not scope or not isinstance(timeline, V2FactsTimeline):
            return
        row_hashes = self._row_hashes(frame)
        if row_hashes is None:
            return
        facts_by_idx = {
            point.idx: point.facts
            for point in timeline.points
            if isinstance(point.facts, dict)
        }
        if timeline.start_idx > 0 and isinstance(timeline.previous_facts, dict):
            facts_by_idx[timeline.start_idx - 1] = timeline.previous_facts
        key = str(scope)
        with self._lock:
            self._entries[key] = _V2FactsTimelineCacheEntry(
                schema_fingerprint=self._schema_fingerprint(frame),
                row_hashes=row_hashes,
                facts_by_idx=facts_by_idx,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self):
        with self._lock:
            self._entries.clear()


def v2_timeline_start_index(df_display, lookback=None):
    if not lookback:
        return 0
    return max(0, len(df_display) - int(lookback))


def _known_facts_at(known_facts_by_idx, idx):
    if not isinstance(known_facts_by_idx, dict):
        return None
    facts = known_facts_by_idx.get(idx)
    return facts if isinstance(facts, dict) else None


def build_v2_facts_timeline(
    df_display,
    lookback=None,
    facts_builder=None,
    known_facts_by_idx=None,
):
    """Build V2 facts for each displayed prefix that event builders inspect."""
    facts_builder = facts_builder or build_c_signal_v2_event_facts
    start_idx = v2_timeline_start_index(df_display, lookback=lookback)
    previous_facts = {}
    built_count = 0
    reused_count = 0
    if start_idx > 0:
        previous_idx = start_idx - 1
        previous_facts = _known_facts_at(known_facts_by_idx, previous_idx)
        if previous_facts is None:
            previous_facts = facts_builder(df_display.iloc[:start_idx])
            built_count += 1
            if not isinstance(previous_facts, dict):
                previous_facts = {}
        else:
            reused_count += 1

    points = []
    for idx in range(start_idx, len(df_display)):
        frame = df_display.iloc[:idx + 1]
        facts = _known_facts_at(known_facts_by_idx, idx)
        if facts is None:
            facts = facts_builder(frame)
            built_count += 1
            if not isinstance(facts, dict):
                facts = {}
        else:
            reused_count += 1
        points.append(V2FactsPoint(
            idx=idx,
            latest=frame.iloc[-1],
            facts=facts,
        ))
    return V2FactsTimeline(
        start_idx=start_idx,
        previous_facts=previous_facts,
        points=tuple(points),
        built_count=built_count,
        reused_count=reused_count,
    )
