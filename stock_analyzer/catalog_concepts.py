"""Stock concept cache service."""

from stock_analyzer.catalog_cache import (
    concept_cache_path,
    profile_cache_path,
    read_concept_cache,
    read_concept_cache_source,
    read_profile_cache,
    write_concept_cache,
    write_profile_cache,
)
from stock_analyzer.catalog_profiles import _PROFILE_CACHE_LOCK, normalize_profile
from stock_analyzer.catalog_utils import merge_concepts, normalize_concepts, path_mtime_text
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.providers.concepts import CONCEPT_SOURCE_THS, DEFAULT_CONCEPT_PROVIDER


def get_stock_concept_cache_status(cache_dir):
    """Return lightweight local concept-cache coverage metadata."""
    concept_cache = read_concept_cache(cache_dir)
    profile_cache = read_profile_cache(cache_dir)
    combined = {}

    for raw_code, profile in profile_cache.items():
        code = normalize_code(raw_code)
        if not code:
            continue
        concepts = normalize_concepts((profile or {}).get("concepts") if isinstance(profile, dict) else None)
        if concepts:
            combined[code] = concepts
    for code, concepts in concept_cache.items():
        combined[code] = merge_concepts(combined.get(code), concepts)

    unique_concepts = sorted({concept for concepts in combined.values() for concept in concepts})
    concept_updated = path_mtime_text(concept_cache_path(cache_dir))
    profile_updated = path_mtime_text(profile_cache_path(cache_dir))
    updated_at = max([value for value in (concept_updated, profile_updated) if value] or [""])
    return {
        "available": bool(combined),
        "stock_count": len(combined),
        "concept_count": len(unique_concepts),
        "updated_at": updated_at or "-",
        "source": read_concept_cache_source(cache_dir) or CONCEPT_SOURCE_THS,
    }


def refresh_stock_concept_cache(max_concepts=None, logger=None, progress_callback=None, provider=None, cache_dir=None):
    """Build a stock->concept cache from AData THS data, falling back to THS pages."""
    provider = provider or DEFAULT_CONCEPT_PROVIDER
    concept_boards, source = provider.list_boards(logger=logger)
    if max_concepts is not None:
        concept_boards = concept_boards[:max(0, int(max_concepts))]

    stock_concepts = {}
    stock_names = {}
    error_count = 0
    fallback_count = 0
    total = len(concept_boards)
    if progress_callback:
        progress_callback(total=total, completed=0, current_concept="", stock_count=0)
    for index, board in enumerate(concept_boards, start=1):
        concept_name = board["name"]
        stock_rows = []
        used_fallback = False
        try:
            if board.get("index_code"):
                try:
                    stock_rows = provider.fetch_adata_constituents(board)
                except Exception as e:
                    used_fallback = True
                    message = (
                        f"[stock_concepts] AData 概念 {concept_name}"
                        f"({board.get('index_code')}) 成分失败，尝试 HTML 兜底: {e}"
                    )
                    if logger:
                        logger.warning(message)
                    else:
                        print(message)
            if not stock_rows:
                used_fallback = True
                stock_rows = provider.fetch_ths_constituents(board)
            if used_fallback:
                fallback_count += 1
        except Exception as e:
            error_count += 1
            message = f"[stock_concepts] 获取同花顺概念 {concept_name}({board.get('index_code') or board.get('code')}) 成分失败: {e}"
            if logger:
                logger.warning(message)
            else:
                print(message)
        for stock in stock_rows:
            code = stock.get("code")
            if not code:
                continue
            stock_concepts.setdefault(code, []).append(concept_name)
            if stock.get("name"):
                stock_names.setdefault(code, stock["name"])
        if progress_callback:
            progress_callback(
                total=total,
                completed=index,
                current_concept=concept_name,
                stock_count=len(stock_concepts),
            )

    stock_concepts = {
        code: normalize_concepts(concepts)
        for code, concepts in stock_concepts.items()
        if concepts
    }

    if stock_concepts or not read_concept_cache(cache_dir):
        write_concept_cache(stock_concepts, source=source, cache_dir=cache_dir)

    with _PROFILE_CACHE_LOCK:
        profiles = read_profile_cache(cache_dir)
        for code, concepts in stock_concepts.items():
            profile = normalize_profile(code, profiles.get(code))
            if stock_names.get(code) and (not profile.get("name") or profile.get("name") == code):
                profile["name"] = stock_names[code]
            profile["concepts"] = merge_concepts(profile.get("concepts"), concepts)
            profiles[code] = profile
        write_profile_cache(profiles, cache_dir)

    return {
        "source": source,
        "concept_count": len(concept_boards),
        "completed_count": len(concept_boards),
        "error_count": error_count,
        "fallback_count": fallback_count,
        "stock_count": len(stock_concepts),
        "updated_at": get_stock_concept_cache_status(cache_dir)["updated_at"],
    }
