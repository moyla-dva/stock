"""Provider adapters for stock code lists and stock metadata."""

import akshare as ak

from stock_analyzer.providers.tdx_client import fetch_tdx_stock_codes


NAME_ITEMS = ("股票简称", "简称")
SECTOR_ITEMS = ("行业", "所属行业", "所属板块", "板块")
CONCEPT_ITEMS = ("概念题材", "所属概念", "概念板块", "题材概念")


def _clean_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def _info_value(df_info, item_names):
    if df_info is None or df_info.empty:
        return ""
    if "item" not in df_info.columns or "value" not in df_info.columns:
        return ""

    items = df_info["item"].astype(str)
    for item_name in item_names:
        rows = df_info[items == item_name]
        if not rows.empty:
            return _clean_text(rows["value"].values[0])
    return ""


def _first_row_value(df_info, column_names):
    if df_info is None or df_info.empty:
        return ""
    for column_name in column_names:
        if column_name in df_info.columns:
            return _clean_text(df_info.iloc[0][column_name])
    return ""


class StockCatalogProvider:
    """Fetch raw stock catalog data from external providers."""

    def fetch_primary_stock_codes(self):
        """Authoritative SH/SZ/BJ list from the exchanges themselves."""
        frame = ak.stock_info_a_code_name()
        return frame["code"].tolist()

    def fetch_secondary_stock_codes(self):
        """Best-effort list from TDX quote servers (host quirks may truncate it)."""
        return fetch_tdx_stock_codes()

    def fetch_profile_from_cninfo(self, code):
        frame = ak.stock_profile_cninfo(symbol=code)
        return {
            "code": code,
            "name": _first_row_value(frame, ("A股简称", "证券简称", "公司简称")),
            "sector": _first_row_value(frame, ("所属行业", "行业")),
            "concepts": _first_row_value(frame, ("所属概念", "概念题材", "概念板块")),
        }


DEFAULT_STOCK_CATALOG_PROVIDER = StockCatalogProvider()
