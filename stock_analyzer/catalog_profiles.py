"""Stock profile service built on catalog cache and provider adapters."""

import logging
import threading

from stock_analyzer.catalog_cache import read_concept_cache, read_profile_cache, write_profile_cache
from stock_analyzer.catalog_utils import clean_text, merge_concepts, normalize_concepts
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.contracts import StockProfile
from stock_analyzer.providers.catalog import DEFAULT_STOCK_CATALOG_PROVIDER


_PROFILE_CACHE_LOCK = threading.Lock()
LOGGER = logging.getLogger(__name__)


def normalize_profile(code, profile=None):
    profile = profile or {}
    return StockProfile(
        code=code,
        name=clean_text(profile.get("name")) or code,
        sector=clean_text(profile.get("sector")),
        concepts=normalize_concepts(profile.get("concepts") or profile.get("concept")),
    ).to_dict()


def merge_profile(base, update):
    merged = dict(base)
    for key in ("name", "sector"):
        value = clean_text((update or {}).get(key))
        if value:
            merged[key] = value
    concepts = merge_concepts(
        merged.get("concepts"),
        (update or {}).get("concepts") or (update or {}).get("concept"),
    )
    if concepts:
        merged["concepts"] = concepts
    return merged


def profile_has_metadata(profile, code):
    return bool(
        profile.get("sector")
        or profile.get("concepts")
        or (profile.get("name") and profile.get("name") != code)
    )


def update_profile_cache(code, profile, cache_dir):
    with _PROFILE_CACHE_LOCK:
        cache = read_profile_cache(cache_dir)
        cache[code] = normalize_profile(code, profile)
        write_profile_cache(cache, cache_dir)


def get_cached_stock_profiles(cache_dir):
    """Return the local stock-profile cache without hitting the network."""
    profiles = read_profile_cache(cache_dir)
    concepts = read_concept_cache(cache_dir)
    codes = set(profiles.keys()) | set(concepts.keys())
    output = {}
    for raw_code in codes:
        code = normalize_code(raw_code)
        if not code:
            continue
        profile = normalize_profile(code, profiles.get(raw_code) or profiles.get(code))
        profile["concepts"] = merge_concepts(profile.get("concepts"), concepts.get(code))
        output[code] = profile
    return output


def get_cached_stock_profile(code, cache_dir):
    """Return a single cached stock profile without hitting the network."""
    code = normalize_code(code)
    if not code:
        return StockProfile.empty().to_dict()
    return get_cached_stock_profiles(cache_dir).get(code, normalize_profile(code))


def get_stock_profile(
    code,
    *,
    cache_dir,
    use_cache=True,
    require_sector=True,
    provider=None,
    before_provider_fetch=None,
):
    """Fetch stock display name and sector, returning local fallbacks on failure."""
    code = normalize_code(code)
    if not code:
        return StockProfile.empty().to_dict()

    cache = read_profile_cache(cache_dir)
    concept_cache = read_concept_cache(cache_dir)
    cached = normalize_profile(code, cache.get(code))
    cached["concepts"] = merge_concepts(cached.get("concepts"), concept_cache.get(code))
    if use_cache and (cached.get("sector") or (not require_sector and cached.get("name") != code)):
        return cached

    if before_provider_fetch:
        before_provider_fetch()
    provider = provider or DEFAULT_STOCK_CATALOG_PROVIDER
    profile = cached
    for provider_name, source_func in (
        ("cninfo", provider.fetch_profile_from_cninfo),
    ):
        try:
            profile = merge_profile(profile, source_func(code))
            if profile.get("sector") or (not require_sector and profile.get("name") != code):
                update_profile_cache(code, profile, cache_dir)
                return profile
        except Exception as e:
            LOGGER.debug("%s 获取股票 %s 画像失败: %s", provider_name, code, e, exc_info=True)

    if profile_has_metadata(profile, code):
        update_profile_cache(code, profile, cache_dir)
    return profile
