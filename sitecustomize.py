"""Project-wide interpreter compatibility hooks."""

try:
    from stock_analyzer.compat import install_py_mini_racer_compat

    install_py_mini_racer_compat()
except Exception:
    pass
