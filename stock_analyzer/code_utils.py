"""Utilities for stock code handling."""

import re


def normalize_code(code):
    """Normalize common stock code inputs to a plain 6-digit code."""
    if code is None:
        return None
    code = str(code).strip()
    if not code:
        return None
    match = re.search(r"(\d{6})", code)
    return match.group(1) if match else None

