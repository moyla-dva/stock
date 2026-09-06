"""Compatibility shims for third-party data libraries."""

import sys
import types


def install_py_mini_racer_compat():
    """Expose the legacy py_mini_racer.py_mini_racer module API.

    AData and parts of the THS data stack still import
    ``from py_mini_racer import py_mini_racer``. The maintained ``mini-racer``
    package exposes ``MiniRacer`` at package level instead. This shim lets the
    old import path use the maintained runtime without installing the older
    binary package.
    """
    try:
        import py_mini_racer as package
    except Exception:
        return

    if hasattr(package, "py_mini_racer"):
        return
    if not hasattr(package, "MiniRacer"):
        return

    shim = types.ModuleType("py_mini_racer.py_mini_racer")
    shim.MiniRacer = package.MiniRacer
    sys.modules.setdefault("py_mini_racer.py_mini_racer", shim)
    setattr(package, "py_mini_racer", shim)
