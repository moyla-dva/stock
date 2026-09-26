"""Persistent cache for compact scan workspace responses."""

import hashlib
import json
import logging
import stat
import time
import uuid
from datetime import datetime
from pathlib import Path

from stock_analyzer import catalog, scan_snapshot
from stock_analyzer.profile_relations import profile_relation_evidence_path
from stock_analyzer.versioning import (
    DATA_ADJUST,
    SCAN_EXPLANATION_VERSION,
    SCAN_STRATEGY_VERSION,
    SCAN_SNAPSHOT_SCHEMA_VERSION,
)


SCAN_WORKSPACE_CACHE_SCHEMA_VERSION = 2
SCAN_WORKSPACE_RESPONSE_CACHE_DIR = (
    Path(__file__).resolve().parents[1] / ".cache" / "scan_workspace_responses"
)
SCAN_WORKSPACE_RESPONSE_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
SCAN_WORKSPACE_RESPONSE_CACHE_MAX_BYTES = 512 * 1024 * 1024
LOGGER = logging.getLogger(__name__)


def _now_text():
    return datetime.now().isoformat(timespec="seconds")


def _path_stat(path):
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return {
            "path": str(path),
            "exists": False,
            "mtime_ns": 0,
            "size": 0,
        }
    return {
        "path": str(path),
        "exists": True,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def scan_workspace_dependency_fingerprint(
    start_date=None,
    snapshot_day=None,
    *,
    index_store=None,
):
    """Return a cheap invalidation fingerprint for compact workspace responses."""
    try:
        indexed = index_store.cache_fingerprint(scan_snapshot.SNAPSHOT_DIR) if index_store else {}
    except Exception:
        LOGGER.debug("SQLite snapshot fingerprint unavailable; using file metadata", exc_info=True)
        indexed = {}
    if indexed.get("available"):
        snapshots = {
            "path": str(scan_snapshot.SNAPSHOT_DIR),
            "file_count": indexed["snapshot_count"],
            "latest_snapshot_day": indexed["latest_snapshot_day"],
            "index_revision": indexed["revision"],
            "index_build_scope": indexed["build_scope"],
        }
    else:
        snapshot_paths = (
            scan_snapshot.scan_snapshot_day_files(
                start_date=start_date,
                snapshot_day=snapshot_day,
            )
            if snapshot_day
            else scan_snapshot.scan_snapshot_files(start_date=start_date)
        )
        latest_snapshot_day = ""
        snapshot_count = 0
        latest_mtime_ns = 0
        total_size = 0
        file_signatures = []
        for path in snapshot_paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot_count += 1
            latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
            total_size += stat.st_size
            file_signatures.append((path.name, stat.st_mtime_ns, stat.st_size))
            day = scan_snapshot.normalize_snapshot_day(str(path.stem).rsplit("_", 1)[-1])
            if day > latest_snapshot_day:
                latest_snapshot_day = day
        snapshots = {
            "path": str(scan_snapshot.SNAPSHOT_DIR),
            "file_count": snapshot_count,
            "latest_snapshot_day": latest_snapshot_day,
            "latest_mtime_ns": latest_mtime_ns,
            "total_size": total_size,
            "file_revision": hashlib.sha256(
                json.dumps(sorted(file_signatures), separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "revision_source": "filesystem",
        }

    return {
        "schema_version": SCAN_WORKSPACE_CACHE_SCHEMA_VERSION,
        "strategy_version": SCAN_STRATEGY_VERSION,
        "snapshot_schema_version": SCAN_SNAPSHOT_SCHEMA_VERSION,
        "explanation_version": SCAN_EXPLANATION_VERSION,
        "data_adjust": DATA_ADJUST,
        "snapshots": snapshots,
        "catalog": [
            _path_stat(catalog.profile_cache_path()),
            _path_stat(catalog.concept_cache_path()),
            _path_stat(profile_relation_evidence_path(cache_dir=catalog.CATALOG_CACHE_DIR)),
        ],
    }


def _cache_digest(key, fingerprint):
    payload = {
        "key": key,
        "fingerprint": fingerprint,
    }
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _json_key(key):
    if isinstance(key, tuple):
        return list(key)
    if isinstance(key, list):
        return key
    return [key]


def _is_lite_workspace_key(key):
    json_key = _json_key(key)
    return bool(json_key and json_key[0] == "scan_workspace_lite")


def _is_cacheable_payload(payload, key):
    if not isinstance(payload, dict):
        return False
    if not _is_lite_workspace_key(key):
        return True
    return isinstance(payload.get("snapshot_meta"), dict) and isinstance(payload.get("strategy_meta"), dict)


def _cache_path(key, fingerprint):
    return SCAN_WORKSPACE_RESPONSE_CACHE_DIR / f"{_cache_digest(key, fingerprint)}.json"


def _prune_response_cache(cache_dir=None, *, now=None):
    """Bound only derived workspace responses by age and total disk usage."""
    cache_dir = Path(cache_dir or SCAN_WORKSPACE_RESPONSE_CACHE_DIR)
    entries = []
    try:
        paths = cache_dir.glob("*.json")
    except OSError:
        return 0
    for path in paths:
        try:
            metadata = path.stat()
        except OSError:
            continue
        if stat.S_ISREG(metadata.st_mode):
            entries.append((path, metadata.st_mtime, metadata.st_size))
    current_time = float(now if now is not None else time.time())
    cutoff = current_time - SCAN_WORKSPACE_RESPONSE_CACHE_MAX_AGE_SECONDS
    expired = [entry for entry in entries if entry[1] < cutoff]
    retained = [entry for entry in entries if entry[1] >= cutoff]
    total_bytes = sum(entry[2] for entry in retained)
    remove = {entry[0] for entry in expired}
    for path, _modified, size in sorted(retained, key=lambda entry: entry[1]):
        if total_bytes <= SCAN_WORKSPACE_RESPONSE_CACHE_MAX_BYTES:
            break
        remove.add(path)
        total_bytes -= size
    removed = 0
    for path in remove:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _read_cached_payload(path, key, fingerprint):
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    meta = payload.get("workspace_cache_meta") if isinstance(payload, dict) else {}
    if not isinstance(meta, dict):
        return None
    if meta.get("schema_version") != SCAN_WORKSPACE_CACHE_SCHEMA_VERSION:
        return None
    if meta.get("key") != _json_key(key) or meta.get("fingerprint") != fingerprint:
        return None
    if not _is_cacheable_payload(payload, key):
        return None
    payload["workspace_cache_meta"] = dict(meta, hit=True)
    return payload


def _write_cached_payload(path, payload, key, fingerprint):
    if not _is_cacheable_payload(payload, key):
        return payload
    cached = dict(payload)
    cached["workspace_cache_meta"] = {
        "schema_version": SCAN_WORKSPACE_CACHE_SCHEMA_VERSION,
        "key": _json_key(key),
        "fingerprint": fingerprint,
        "stored_at": _now_text(),
        "hit": False,
    }
    tmp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(cached, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(path)
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except Exception:
                pass
        return payload
    _prune_response_cache(path.parent)
    return cached


def put_cached_compact_workspace_response(key, fingerprint, payload):
    """Store a compact workspace response without reading it first."""
    return _write_cached_payload(_cache_path(key, fingerprint), payload, key, fingerprint)


def get_cached_compact_workspace_response(key, fingerprint, factory, force_refresh=False):
    """Read or build a compact workspace response from a persistent JSON cache."""
    cache_path = _cache_path(key, fingerprint)
    if not force_refresh:
        cached = _read_cached_payload(cache_path, key, fingerprint)
        if cached is not None:
            return cached
    payload = factory()
    return _write_cached_payload(cache_path, payload, key, fingerprint)
