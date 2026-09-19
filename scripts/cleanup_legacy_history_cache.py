"""Clean up legacy daily-history cache files after the canonical cache-key migration.

历史缓存键曾把"结束日"编进文件名（{code}_{start}_{end}_{adjust}.csv），每天必然
miss 重取并堆积文件。data_fetcher 现已改用 canonical 键（{code}_{start}_{adjust}.csv），
并在读取时把 legacy 文件迁移进 canonical。本脚本在迁移完成后回收 legacy 文件：

- 只删除同 (code, start, adjust) 已存在 canonical、且 canonical 数据不落后于
  legacy（latest_date 比较，读 meta 旁车，缺失时回退读 CSV date 列）的 legacy 文件；
- canonical 缺失或数据更旧的 legacy 一律保留并给出原因；
- 默认 dry-run，仅打印将删除的文件与可回收空间；--apply 才真正删除。

用法：
    python scripts/cleanup_legacy_history_cache.py            # 预览
    python scripts/cleanup_legacy_history_cache.py --apply    # 执行删除
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.data_fetcher import (
    CACHE_DIR,
    _history_meta_path,
    _read_latest_history_date_text,
)


def _latest_date_of(path):
    return _read_latest_history_date_text(path) or ""


def _meta_mtime(path):
    meta_path = _history_meta_path(path)
    try:
        return meta_path.stat().st_mtime
    except OSError:
        return 0.0


def classify_legacy_files(cache_dir=None):
    """Return (deletable, keep_reasons) for legacy cache files in cache_dir."""
    cache_dir = Path(cache_dir or CACHE_DIR)
    if not cache_dir.exists():
        return [], []
    canonical_latest = {}
    deletable = []
    keep_reasons = []
    for path in sorted(cache_dir.glob("*.csv")):
        parts = path.stem.split("_")
        if len(parts) != 4:
            continue
        code, start_text, end_text, adjust = parts
        if not (len(code) == 6 and code.isdigit() and len(start_text) == 8 and start_text.isdigit()
                and len(end_text) == 8 and end_text.isdigit()):
            continue
        canonical = cache_dir / f"{code}_{start_text}_{adjust}.csv"
        if not canonical.exists():
            keep_reasons.append((path, "canonical 缺失，保留迁移来源"))
            continue
        key = (code, start_text, adjust)
        if key not in canonical_latest:
            canonical_latest[key] = _latest_date_of(canonical)
        canonical_date = canonical_latest[key]
        legacy_date = _latest_date_of(path)
        if not legacy_date:
            keep_reasons.append((path, "legacy 最新日期不可读，保守保留"))
            continue
        if not canonical_date:
            keep_reasons.append((path, "canonical 最新日期不可读，保守保留"))
            continue
        if legacy_date > canonical_date:
            keep_reasons.append((path, f"legacy 更新（{legacy_date} > {canonical_date}），先重刷再清理"))
            continue
        deletable.append((path, legacy_date, canonical_date))
    return deletable, keep_reasons


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="实际删除（默认只预览）")
    parser.add_argument("--cache-dir", default=None, help="覆盖缓存目录")
    parser.add_argument("--limit", type=int, default=None, help="最多处理 N 个文件")
    args = parser.parse_args(argv)

    deletable, keep_reasons = classify_legacy_files(args.cache_dir)
    total_bytes = sum(path.stat().st_size for path, _, _ in deletable)
    print(f"缓存目录: {Path(args.cache_dir or CACHE_DIR)}")
    print(f"可删除 legacy 文件: {len(deletable)} 个，约 {total_bytes / 1024 / 1024:.1f} MB")
    print(f"保留: {len(keep_reasons)} 个")
    for path, reason in keep_reasons[:10]:
        print(f"  保留 {path.name}: {reason}")
    if len(keep_reasons) > 10:
        print(f"  ... 其余 {len(keep_reasons) - 10} 条略")

    if not args.apply:
        print("dry-run 预览结束（加 --apply 执行删除）")
        return 0

    freed = 0
    deleted = 0
    for index, (path, _, _) in enumerate(deletable):
        if args.limit is not None and index >= args.limit:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            meta_path = _history_meta_path(path)
            if meta_path.exists():
                meta_path.unlink()
            deleted += 1
            freed += size
        except OSError as exc:
            print(f"  删除失败 {path.name}: {exc}")
    print(f"已删除 {deleted} 个文件，回收 {freed / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
