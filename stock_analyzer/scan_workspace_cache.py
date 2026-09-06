"""Small in-process cache for the scan workspace API."""

import copy
import threading
import time


_CACHE_LOCK = threading.Lock()
_CACHE = {}


def _now():
    return time.time()


def clear_scan_workspace_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


def get_cached_scan_workspace(key, factory, ttl_seconds=12, force_refresh=False):
    """Return a deep-copied cached workspace payload for short-lived page refresh reuse."""
    now = _now()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if not force_refresh and cached and now - cached["created_at"] <= ttl_seconds:
            return copy.deepcopy(cached["payload"])

    payload = factory()
    created_at = _now()
    with _CACHE_LOCK:
        _CACHE[key] = {
            "created_at": created_at,
            "payload": copy.deepcopy(payload),
        }
    return payload
