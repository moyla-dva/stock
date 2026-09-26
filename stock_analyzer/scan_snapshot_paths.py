"""Shared filename rules for persisted scan snapshots."""

from __future__ import annotations

import re
from pathlib import Path


SCAN_SNAPSHOT_FILENAME_RE = re.compile(r"^\d{6}_[A-Za-z0-9]+_\d{8}\.json$")


def is_scan_snapshot_file(path: str | Path) -> bool:
    return bool(SCAN_SNAPSHOT_FILENAME_RE.fullmatch(Path(path).name))


def discover_scan_snapshot_files(directory: str | Path) -> list[Path]:
    root = Path(directory)
    return [path for path in root.glob("*.json") if is_scan_snapshot_file(path)]
