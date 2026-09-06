"""Shared network guardrails for external market data providers."""

import os
import socket

DEFAULT_PROVIDER_TIMEOUT_SECONDS = 15.0


def provider_timeout_seconds():
    """Return the bounded timeout used for provider HTTP calls."""
    raw_value = os.environ.get("STOCK_ANALYZER_PROVIDER_TIMEOUT_SECONDS")
    if raw_value is None:
        return DEFAULT_PROVIDER_TIMEOUT_SECONDS
    try:
        timeout = float(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_PROVIDER_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_PROVIDER_TIMEOUT_SECONDS


def configure_default_socket_timeout(timeout=None):
    """Apply a process-wide fallback timeout for libraries without a timeout arg."""
    timeout = provider_timeout_seconds() if timeout is None else float(timeout)
    current = socket.getdefaulttimeout()
    if current is None or current > timeout:
        socket.setdefaulttimeout(timeout)
    return timeout
