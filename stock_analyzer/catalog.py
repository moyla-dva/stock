"""Stock metadata and stock-code list access.

This module remains the public facade. Implementation is split into cache,
profile, concept, and stock-list services so callers keep a stable API while
module boundaries stay small.
"""

from stock_analyzer.catalog_cache import (
    CONCEPT_CACHE_FILENAME,
    DEFAULT_CATALOG_CACHE_DIR,
    PROFILE_CACHE_FILENAME,
    concept_cache_path as _concept_cache_path,
    profile_cache_path as _profile_cache_path,
)
from stock_analyzer.catalog_concepts import (
    get_stock_concept_cache_status as _get_stock_concept_cache_status,
    refresh_stock_concept_cache as _refresh_stock_concept_cache,
)
from stock_analyzer.catalog_profiles import (
    get_cached_stock_profile as _get_cached_stock_profile,
    get_cached_stock_profiles as _get_cached_stock_profiles,
    get_stock_profile as _get_stock_profile,
)
from stock_analyzer.catalog_stock_list import (
    FALLBACK_STOCK_CODES,
    StockUniverseUnavailable,
    get_stock_codes as _get_stock_codes,
)
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.data_fetcher import disable_proxies
from stock_analyzer.providers.adata_loader import import_adata


CATALOG_CACHE_DIR = DEFAULT_CATALOG_CACHE_DIR


def _import_adata():
    return import_adata()


def profile_cache_path():
    return _profile_cache_path(CATALOG_CACHE_DIR)


def concept_cache_path():
    return _concept_cache_path(CATALOG_CACHE_DIR)


def get_cached_stock_profiles():
    """Return the local stock-profile cache without hitting the network."""
    return _get_cached_stock_profiles(CATALOG_CACHE_DIR)


def get_cached_stock_profile(code):
    """Return a single cached stock profile without hitting the network."""
    return _get_cached_stock_profile(code, CATALOG_CACHE_DIR)


def get_stock_profile(code, use_cache=True, require_sector=True, provider=None):
    """Fetch stock display name and sector, returning local fallbacks on failure."""
    return _get_stock_profile(
        code,
        cache_dir=CATALOG_CACHE_DIR,
        use_cache=use_cache,
        require_sector=require_sector,
        provider=provider,
        before_provider_fetch=disable_proxies,
    )


def get_stock_name(code):
    """Fetch stock display name, returning the normalized code on failure."""
    profile = get_stock_profile(code, require_sector=False)
    return profile.get("name") or normalize_code(code) or ""


def get_stock_sector(code):
    """Fetch stock sector/industry, returning an empty string on failure."""
    return get_stock_profile(code).get("sector") or ""


def get_stock_concepts(code):
    """Fetch cached concept/topic tags for a stock."""
    return get_stock_profile(code, require_sector=False).get("concepts") or []


def get_stock_concept_cache_status():
    """Return lightweight local concept-cache coverage metadata."""
    return _get_stock_concept_cache_status(CATALOG_CACHE_DIR)


def refresh_stock_concept_cache(max_concepts=None, logger=None, progress_callback=None, provider=None):
    """Build a stock->concept cache from AData THS data, falling back to THS pages."""
    disable_proxies()
    return _refresh_stock_concept_cache(
        max_concepts=max_concepts,
        logger=logger,
        progress_callback=progress_callback,
        provider=provider,
        cache_dir=CATALOG_CACHE_DIR,
    )


def get_stock_codes(
    use_disable_proxies=True,
    provider=None,
    *,
    allow_secondary=True,
    allow_static_fallback=True,
):
    """Fetch A-share stock codes with provider fallback and a local safety list."""
    if use_disable_proxies:
        disable_proxies()
    return _get_stock_codes(
        provider=provider,
        allow_secondary=allow_secondary,
        allow_static_fallback=allow_static_fallback,
    )
