"""Small in-process cache for the scan workspace API."""

import copy
import os
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager


_CACHE_LOCK = threading.Lock()
_CACHE = OrderedDict()
_BUILD_LOCKS = OrderedDict()
_CACHE_MAX_ENTRIES = max(1, int(os.environ.get("SCAN_WORKSPACE_MEMORY_CACHE_MAX_ENTRIES", "64")))
_CACHE_RETENTION_SECONDS = max(
    1,
    int(os.environ.get("SCAN_WORKSPACE_MEMORY_CACHE_RETENTION_SECONDS", "300")),
)
_BUILD_LOCK_MAX_ENTRIES = max(1, _CACHE_MAX_ENTRIES * 2)


def _now():
    return time.time()


def clear_scan_workspace_cache():
    with _CACHE_LOCK:
        _CACHE.clear()
        _BUILD_LOCKS.clear()


def _prune_cache(now):
    expired = [
        key
        for key, cached in _CACHE.items()
        if now - cached["created_at"] > _CACHE_RETENTION_SECONDS
    ]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.popitem(last=False)


def _prune_build_locks():
    for key in list(_BUILD_LOCKS):
        if len(_BUILD_LOCKS) <= _BUILD_LOCK_MAX_ENTRIES:
            break
        entry = _BUILD_LOCKS[key]
        if entry["users"] == 0:
            _BUILD_LOCKS.pop(key, None)


@contextmanager
def _build_lock_for_key(key):
    with _CACHE_LOCK:
        entry = _BUILD_LOCKS.get(key)
        if entry is None:
            entry = {"lock": threading.Lock(), "users": 0}
            _BUILD_LOCKS[key] = entry
        entry["users"] += 1
        _BUILD_LOCKS.move_to_end(key)
    entry["lock"].acquire()
    try:
        yield
    finally:
        entry["lock"].release()
        with _CACHE_LOCK:
            current = _BUILD_LOCKS.get(key)
            if current is entry:
                current["users"] -= 1
                _BUILD_LOCKS.move_to_end(key)
            _prune_build_locks()


def get_cached_scan_workspace(
    key,
    factory,
    ttl_seconds=12,
    force_refresh=False,
    *,
    copy_payload=True,
):
    """Return a cached workspace, copying by default to protect mutable consumers."""
    requested_at = _now()
    with _CACHE_LOCK:
        _prune_cache(requested_at)
        cached = _CACHE.get(key)
        if not force_refresh and cached and requested_at - cached["created_at"] <= ttl_seconds:
            _CACHE.move_to_end(key)
            return copy.deepcopy(cached["payload"]) if copy_payload else cached["payload"]

    with _build_lock_for_key(key):
        now = _now()
        with _CACHE_LOCK:
            _prune_cache(now)
            cached = _CACHE.get(key)
            if cached:
                fresh = now - cached["created_at"] <= ttl_seconds
                refreshed_after_request = cached["created_at"] >= requested_at
                if (not force_refresh and fresh) or (force_refresh and refreshed_after_request):
                    _CACHE.move_to_end(key)
                    return copy.deepcopy(cached["payload"]) if copy_payload else cached["payload"]

        payload = factory()
        created_at = _now()
        with _CACHE_LOCK:
            _CACHE[key] = {
                "created_at": created_at,
                "payload": copy.deepcopy(payload) if copy_payload else payload,
            }
            _CACHE.move_to_end(key)
            _prune_cache(created_at)
    return payload
