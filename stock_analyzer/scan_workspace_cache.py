"""Small in-process cache for the scan workspace API."""

import copy
import threading
import time


_CACHE_LOCK = threading.Lock()
_CACHE = {}
_BUILD_LOCKS = {}


def _now():
    return time.time()


def clear_scan_workspace_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


def _build_lock_for_key(key):
    with _CACHE_LOCK:
        lock = _BUILD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _BUILD_LOCKS[key] = lock
        return lock


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
        cached = _CACHE.get(key)
        if not force_refresh and cached and requested_at - cached["created_at"] <= ttl_seconds:
            return copy.deepcopy(cached["payload"]) if copy_payload else cached["payload"]

    build_lock = _build_lock_for_key(key)
    with build_lock:
        now = _now()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached:
                fresh = now - cached["created_at"] <= ttl_seconds
                refreshed_after_request = cached["created_at"] >= requested_at
                if (not force_refresh and fresh) or (force_refresh and refreshed_after_request):
                    return copy.deepcopy(cached["payload"]) if copy_payload else cached["payload"]

        payload = factory()
        created_at = _now()
        with _CACHE_LOCK:
            _CACHE[key] = {
                "created_at": created_at,
                "payload": copy.deepcopy(payload) if copy_payload else payload,
            }
    return payload
