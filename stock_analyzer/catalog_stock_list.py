"""A-share stock list service with provider fallback."""

import logging

from stock_analyzer.providers.catalog import DEFAULT_STOCK_CATALOG_PROVIDER

LOGGER = logging.getLogger(__name__)


class StockUniverseUnavailable(RuntimeError):
    """Raised when a complete current stock universe cannot be fetched."""


FALLBACK_STOCK_CODES = [
    "600519", "600809", "000858", "000568", "000596", "600197",
    "601398", "601988", "600036", "601328", "601288", "601166", "600016", "601939", "600015", "600000", "601229",
    "601318", "601601", "601336", "601319",
    "600030", "600837", "601066", "600795", "600958", "601377",
    "000002", "600048", "600383", "001979", "600340",
    "601668", "601800", "601390", "601186", "601618",
    "600019", "600022", "600282", "000932",
    "601088", "600508", "600971", "600395", "601001",
    "600219", "600111", "600362", "600489", "000630",
    "600276", "600436", "600518", "600529", "000538", "000566", "300003", "300015",
    "002594", "300750", "002466", "002812", "600733",
    "600438", "002129", "600401", "300274", "601568",
    "002460", "002709", "002074", "002176", "300014",
    "688981", "600460", "002371", "300456", "688008",
    "600745", "000681", "300033", "002410",
    "600050", "601988", "600030", "000063", "600498",
    "600028", "600021", "600905", "601991", "600795",
    "601888", "600233", "600787", "600057", "603056",
    "000333", "000651", "600690", "000921", "600060",
    "600104", "600418", "600660", "000625", "601127",
    "600143", "600309", "600096", "600486", "002601",
    "601857", "600009", "600030", "601166", "600887", "601006", "601989", "601898",
]


def get_stock_codes(
    provider=None,
    *,
    allow_secondary=True,
    allow_static_fallback=True,
):
    """Fetch A-share codes, optionally requiring the complete primary list."""
    provider = provider or DEFAULT_STOCK_CATALOG_PROVIDER
    stock_list = []
    primary_error = None

    try:
        stock_list = provider.fetch_primary_stock_codes()
    except Exception as e:
        primary_error = e
        LOGGER.debug("接口A失败: %s", e, exc_info=True)

    if not stock_list and allow_secondary:
        try:
            stock_list = provider.fetch_secondary_stock_codes()
        except Exception as e:
            LOGGER.debug("接口B失败: %s", e, exc_info=True)

    if not stock_list:
        if not allow_static_fallback:
            detail = f"：{primary_error}" if primary_error else ""
            raise StockUniverseUnavailable(f"无法获取完整的当日股票名单{detail}")
        LOGGER.debug("所有接口失败，使用保底列表")
        stock_list = FALLBACK_STOCK_CODES.copy()

    return stock_list
