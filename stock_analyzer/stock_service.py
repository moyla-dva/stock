# -*- coding: utf-8 -*-
"""Stock data and profile services used by the web layer and scanners."""

import concurrent.futures

from stock_analyzer.analysis import build_analysis_frame
from stock_analyzer.catalog import (
    get_stock_concept_cache_status,
    get_stock_profile,
    refresh_stock_concept_cache,
)
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.multi_timeframe import build_multi_timeframe_payload
from stock_analyzer.scan_explainer import attach_scan_explanation
from stock_analyzer.serializers import analysis_frame_to_chart_payload
from stock_analyzer.tag_profile import attach_stock_tag_profile
from stock_analyzer.trade_plan import build_trade_plan
from stock_analyzer.versioning import DATA_START_DATE


def fetch_and_process_data(code, logger=None, verbose=True):
    normalized = normalize_code(code) or code
    df_display = build_analysis_frame(
        code,
        start_date=DATA_START_DATE,
        fill_initial_ma20=True,
        use_cache=True,
        logger=logger,
        verbose=verbose,
    )
    if df_display is None or df_display.empty:
        return None
    payload = analysis_frame_to_chart_payload(df_display)
    payload["stock_code"] = normalized
    payload["trade_plan"] = build_trade_plan(df_display)
    payload["multi_timeframes"] = build_multi_timeframe_payload(
        normalized,
        df_display,
        logger=logger,
        verbose=verbose,
    )
    profile = get_stock_profile(normalized, require_sector=False)
    attach_stock_tag_profile(payload, profile={**profile, "code": normalized})
    return payload


def get_stock_dataframe(code):
    """Return the analysis frame used by scan calculation."""
    return build_analysis_frame(
        code,
        start_date=DATA_START_DATE,
        use_cache=True,
        use_disable_proxies=True,
    )


def enrich_scan_result_with_profile(
    result,
    code,
    profile=None,
    *,
    get_stock_profile_func=get_stock_profile,
):
    if not result:
        return result
    profile = profile or get_stock_profile_func(code)
    result["name"] = profile.get("name") or result.get("name") or normalize_code(code) or code
    result["sector"] = result.get("sector") or profile.get("sector") or ""
    result["concepts"] = result.get("concepts") or profile.get("concepts") or []
    attach_stock_tag_profile(result, profile=profile)
    attach_scan_explanation(result)
    return result


def load_stock_profiles(codes, *, get_stock_profile_func=get_stock_profile, max_items=80, max_workers=6):
    """Normalize requested codes and load lightweight name/sector profiles."""
    normalized_codes = []
    seen = set()
    for raw_code in codes:
        code = normalize_code(raw_code)
        if not code or code in seen:
            continue
        seen.add(code)
        normalized_codes.append(code)
        if len(normalized_codes) >= max_items:
            break

    profiles = {}
    if not normalized_codes:
        return profiles

    def load_profile(code):
        return code, get_stock_profile_func(code)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for code, profile in pool.map(load_profile, normalized_codes):
            profiles[code] = profile
    return profiles


def get_stock_concepts_status():
    """Return local concept-cache coverage metadata."""
    return get_stock_concept_cache_status()


def refresh_stock_concepts(max_concepts=None, logger=None, progress_callback=None):
    """Refresh the local stock concept cache."""
    return refresh_stock_concept_cache(
        max_concepts=max_concepts,
        logger=logger,
        progress_callback=progress_callback,
    )
