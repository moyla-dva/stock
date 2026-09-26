"""Local JSON cache repository for stock profiles and concepts."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.catalog_utils import clean_text, normalize_concepts
from stock_analyzer.providers.concepts import CONCEPT_SOURCE_THS


DEFAULT_CATALOG_CACHE_DIR = Path(os.environ.get(
    "STOCK_ANALYZER_CATALOG_CACHE_DIR",
    Path(__file__).resolve().parents[1] / ".cache" / "catalog",
))
PROFILE_CACHE_FILENAME = "stock_profiles.json"
CONCEPT_CACHE_FILENAME = "stock_concepts.json"
LOGGER = logging.getLogger(__name__)


def profile_cache_path(cache_dir=DEFAULT_CATALOG_CACHE_DIR):
    return Path(cache_dir) / PROFILE_CACHE_FILENAME


def concept_cache_path(cache_dir=DEFAULT_CATALOG_CACHE_DIR):
    return Path(cache_dir) / CONCEPT_CACHE_FILENAME


def read_profile_cache(cache_dir=DEFAULT_CATALOG_CACHE_DIR):
    path = profile_cache_path(cache_dir)
    try:
        with path.open("r", encoding="utf-8") as handle:
            cache = json.load(handle)
            if isinstance(cache, dict):
                return cache
    except FileNotFoundError:
        return {}
    except Exception as e:
        LOGGER.debug("读取股票画像缓存失败: %s", e, exc_info=True)
    return {}


def read_concept_cache(cache_dir=DEFAULT_CATALOG_CACHE_DIR):
    path = concept_cache_path(cache_dir)
    try:
        with path.open("r", encoding="utf-8") as handle:
            cache = json.load(handle)
            if isinstance(cache, dict):
                if isinstance(cache.get("stocks"), dict):
                    cache = cache["stocks"]
                return {
                    normalize_code(code) or str(code): normalize_concepts(concepts)
                    for code, concepts in cache.items()
                    if normalize_code(code)
                }
    except FileNotFoundError:
        return {}
    except Exception as e:
        LOGGER.debug("读取股票概念缓存失败: %s", e, exc_info=True)
    return {}


def read_concept_cache_source(cache_dir=DEFAULT_CATALOG_CACHE_DIR):
    path = concept_cache_path(cache_dir)
    try:
        with path.open("r", encoding="utf-8") as handle:
            cache = json.load(handle)
            if isinstance(cache, dict):
                return clean_text(cache.get("source"))
    except Exception:
        return ""
    return ""


def write_profile_cache(cache, cache_dir=DEFAULT_CATALOG_CACHE_DIR):
    path = profile_cache_path(cache_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(cache, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(path)
    except Exception as e:
        LOGGER.debug("写入股票画像缓存失败: %s", e, exc_info=True)


def write_concept_cache(cache, source=CONCEPT_SOURCE_THS, cache_dir=DEFAULT_CATALOG_CACHE_DIR):
    path = concept_cache_path(cache_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        payload = {
            "source": source,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "stocks": cache,
        }
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(path)
    except Exception as e:
        LOGGER.debug("写入股票概念缓存失败: %s", e, exc_info=True)
