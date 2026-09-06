"""AData import helper with local vendor fallback."""

import sys
from pathlib import Path

from stock_analyzer.compat import install_py_mini_racer_compat


def import_adata():
    install_py_mini_racer_compat()
    try:
        import adata
        return adata
    except ModuleNotFoundError:
        vendor_path = Path(__file__).resolve().parents[2] / "vendor" / "adata"
        if vendor_path.exists():
            sys.path.insert(0, str(vendor_path))
            import adata
            return adata
        raise

