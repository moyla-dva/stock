"""Utilities for stock code handling."""

import re


_PLAIN_CODE_PATTERN = re.compile(r"^(\d{6})$")
_PREFIXED_CODE_PATTERN = re.compile(r"^(?:sh|sz|bj)(\d{6})$", re.IGNORECASE)
_SUFFIXED_CODE_PATTERN = re.compile(r"^(\d{6})\.(?:sh|sz|bj)$", re.IGNORECASE)
_CACHE_FILENAME_PATTERN = re.compile(r"^(\d{6})_.+$")


def normalize_code(code):
    """Normalize common stock code inputs to a plain 6-digit code."""
    if code is None:
        return None
    code = str(code).strip()
    if not code:
        return None
    for pattern in (_PLAIN_CODE_PATTERN, _PREFIXED_CODE_PATTERN, _SUFFIXED_CODE_PATTERN):
        match = pattern.fullmatch(code)
        if match:
            return match.group(1)
    return None


def code_from_cache_filename(filename):
    """Extract a stock code only from the project's code-prefixed cache names."""
    name = str(filename or "").strip()
    match = _CACHE_FILENAME_PATTERN.fullmatch(name)
    return match.group(1) if match else None
