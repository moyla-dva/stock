"""Provider adapters for THS/AData concept boards and constituents."""

import logging

import akshare as ak
import requests
from bs4 import BeautifulSoup

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.providers.adata_loader import import_adata


CONCEPT_SOURCE_ADATA_THS = "adata_ths_concepts"
CONCEPT_SOURCE_THS = "ths_concept_pages"
THS_CONCEPT_DETAIL_URL = "https://q.10jqka.com.cn/gn/detail/code/{code}/"
THS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://q.10jqka.com.cn/",
}
LOGGER = logging.getLogger(__name__)


def _clean_text(value):
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    return text


def _first_available_column(df, candidates):
    if df is None or df.empty:
        return None
    for column in candidates:
        if column in df.columns:
            return column
    return df.columns[0] if len(df.columns) else None


def _ths_concept_boards_from_frame(df):
    name_column = _first_available_column(df, ("板块名称", "概念名称", "名称", "name"))
    code_column = _first_available_column(df, ("代码", "code"))
    if not name_column or not code_column:
        return []

    boards = []
    seen = set()
    for _, row in df.iterrows():
        name = _clean_text(row.get(name_column))
        code = _clean_text(row.get(code_column))
        if not name or not code or name in seen:
            continue
        seen.add(name)
        boards.append({"name": name, "code": code, "source": CONCEPT_SOURCE_THS})
    return boards


def _adata_ths_concept_boards():
    adata = import_adata()
    frame = adata.stock.info.all_concept_code_ths()
    if frame is None or frame.empty:
        return []

    boards = []
    seen = set()
    for _, row in frame.iterrows():
        name = _clean_text(row.get("name"))
        index_code = _clean_text(row.get("index_code"))
        concept_code = _clean_text(row.get("concept_code"))
        if not name or not index_code or name in seen:
            continue
        seen.add(name)
        boards.append({
            "name": name,
            "index_code": index_code,
            "concept_code": concept_code,
            "code": concept_code or index_code,
            "source": CONCEPT_SOURCE_ADATA_THS,
        })
    return boards


def _stock_rows_from_concept_frame(df):
    code_column = _first_available_column(df, ("stock_code", "股票代码", "代码", "code"))
    name_column = _first_available_column(df, ("short_name", "股票简称", "名称", "name"))
    if df is None or df.empty or not code_column:
        return []

    rows = []
    seen = set()
    for _, row in df.iterrows():
        code = normalize_code(row.get(code_column))
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append({"code": code, "name": _clean_text(row.get(name_column)) if name_column else ""})
    return rows


def _stock_rows_from_ths_concept_html(html):
    soup = BeautifulSoup(html or "", "lxml")
    rows = []
    for table in soup.select("table.m-pager-table"):
        for tr in table.select("tbody tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
            if len(cells) < 3:
                continue
            code = normalize_code(cells[1])
            name = _clean_text(cells[2])
            if not code or not name or "暂无" in "".join(cells):
                continue
            rows.append({"code": code, "name": name})
    return rows


class ConceptProvider:
    """Fetch concept board definitions and stock constituents."""

    def list_boards(self, logger=None):
        try:
            boards = _adata_ths_concept_boards()
            if boards:
                return boards, CONCEPT_SOURCE_ADATA_THS
        except Exception as e:
            message = f"[stock_concepts] 获取 AData 同花顺概念列表失败: {e}"
            if logger:
                logger.warning(message)
            else:
                LOGGER.debug(message)

        boards = _ths_concept_boards_from_frame(ak.stock_board_concept_name_ths())
        return boards, CONCEPT_SOURCE_THS

    def fetch_adata_constituents(self, board):
        index_code = _clean_text((board or {}).get("index_code"))
        if not index_code:
            return []
        adata = import_adata()
        frame = adata.stock.info.concept_constituent_ths(index_code=index_code)
        return _stock_rows_from_concept_frame(frame)

    def fetch_ths_constituents(self, board, timeout=10):
        code = _clean_text((board or {}).get("code"))
        if not code:
            return []
        url = THS_CONCEPT_DETAIL_URL.format(code=code)
        response = requests.get(url, headers=THS_HEADERS, timeout=timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        return _stock_rows_from_ths_concept_html(response.text)


DEFAULT_CONCEPT_PROVIDER = ConceptProvider()
