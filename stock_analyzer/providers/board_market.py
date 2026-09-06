"""Provider adapters for market-level industry and concept board data."""

import akshare as ak

from stock_analyzer.data_fetcher import beijing_now, disable_proxies, parse_start_date
from stock_analyzer.providers.adata_loader import import_adata
from stock_analyzer.versioning import DATA_START_DATE


SOURCE_THS_INDUSTRY_INDEX = "ths_industry_index"
SOURCE_ADATA_THS_CONCEPT_INDEX = "adata_ths_concept_index"


def _date_text(value, compact=False):
    parsed = parse_start_date(value) if value is not None else beijing_now()
    return parsed.strftime("%Y%m%d" if compact else "%Y-%m-%d")


class BoardMarketProvider:
    """Fetch raw industry/concept board histories from external providers."""

    def fetch_industry_history(self, name, start_date=DATA_START_DATE, end_date=None):
        if not name:
            raise ValueError("行业名称不能为空")
        disable_proxies()
        frame = ak.stock_board_industry_index_ths(
            symbol=name,
            start_date=_date_text(start_date, compact=True),
            end_date=_date_text(end_date, compact=True),
        )
        return {
            "name": name,
            "index_code": name,
            "frame": frame,
            "source": SOURCE_THS_INDUSTRY_INDEX,
        }

    def resolve_concept_board(self, name=None, index_code=None):
        if index_code:
            return {"name": name or index_code, "index_code": index_code}
        if not name:
            raise ValueError("概念名称或指数代码不能为空")

        adata = import_adata()
        frame = adata.stock.info.all_concept_code_ths()
        rows = frame[frame["name"].astype(str) == str(name)]
        if rows.empty:
            raise ValueError(f"未找到概念: {name}")
        row = rows.iloc[0]
        return {"name": str(row["name"]), "index_code": str(row["index_code"])}

    def fetch_concept_history(self, name=None, index_code=None):
        board = self.resolve_concept_board(name=name, index_code=index_code)
        adata = import_adata()
        frame = adata.stock.market.get_market_concept_ths(index_code=board["index_code"], k_type=1)
        return {
            "name": board["name"],
            "index_code": board["index_code"],
            "frame": frame,
            "source": SOURCE_ADATA_THS_CONCEPT_INDEX,
        }


DEFAULT_BOARD_MARKET_PROVIDER = BoardMarketProvider()
