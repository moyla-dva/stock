# Data Operations

## User-Facing Model

数据后台只回答三件事：

- 当前结果是否可用。
- 哪些本地缓存或任务需要治理。
- 需要刷新时应该走哪个后台任务。

默认候选池不承载刷新策略、缓存清理、历史回放或实验校准。

## Data States

| State | Meaning |
| --- | --- |
| `provider` | 可按需请求的外部数据源。 |
| `ready` | 本地已有可用缓存或任务记录。 |
| `warning` | 本地数据存在，但可能过期、旧策略或需要清理。 |
| `empty` | 尚未建立本地缓存。 |
| `experimental` | 可供研究或内部解释，不计入核心可用率。 |

## Current Local Sources

- 日线历史缓存：单股分析、扫描和事件研究的基础。
- 分钟历史缓存：单股确认时的短周期补充。
- 扫描快照：候选池读取的本地结果。
- 股票画像：名称、行业、概念和关系证据的载体。
- 概念库：股票到概念的本地映射。
- 画像证据：人工或公告确认的股票关系证据。
- 扫描任务记录：后台扫描进度、历史和中断恢复。
- 概念图谱：实验性关系边，不是当前核心产品入口。

## Scan Policies

- `auto`：跳过有效快照，只补缺失、过期或旧策略结果。
- `cache`：只读本地快照，不计算新结果。
- `force`：忽略当前池快照并重算。

重复发起相同池和相同范围的活动扫描时，后台任务应复用已有任务，而不是创建第二条队列。

## Public Scan Types

当前候选池展示三个一级入口：

- `opportunity`：参与候选。
- `risk`：风险验证。
- `bottom_div`：修复观察。它保留底背离/修复线索的研究观察语义，不代表入场许可；历史快照与底层策略同样保留。

## Governance Placement

| Operation | Placement |
| --- | --- |
| 启动扫描任务 | 数据后台 |
| 强制重扫 | 数据后台 |
| 查看任务历史 | 数据后台 |
| 清理旧策略/无效快照 | 数据后台 |
| 刷新概念库 | 数据后台 |
| 查看数据源健康 | 数据后台 |
| 候选筛选 | 候选池 |
| 单股执行确认 | 单股确认 |

## Profile Evidence

候选详情可以展示画像关系证据，用来说明股票和行业/概念之间的关系质量。

当前默认候选详情只读展示这些证据，不提供人工校准表单。证据写入 API 仍保留给数据后台、脚本或未来专门的研究工具使用：

```json
POST /api/profile_relations/evidence
{
  "code": "600063",
  "relation": {
    "relation_name": "储能",
    "relation_kind": "business",
    "relation_type": "core_business",
    "source": "manual",
    "confidence": 0.92,
    "evidence": "公告确认主营业务覆盖储能设备",
    "last_verified_date": "2026-05-13"
  }
}
```

## Concept Graph

概念图谱当前是实验层：

- 持久化边存放在 `.cache/catalog/concept_graph_edges.json`。
- `/api/concept_graph` 和 `/api/concept_graph/edges` 继续保留。
- 派生边来自股票画像中的成员重叠，只能说明共现关系，不能直接生成交易结论。
- 在 `/api/data_sources` 中标记为 `experimental`，不计入核心数据源可用率。

## Daily History Cache Scripts（2026-09-19 起的数据脚本入口）

本地日线缓存（`.cache/history`）现使用 canonical 键 `{code}_{start}_{adjust}.csv`（不再把结束日编进文件名）。每日增量与修复使用以下脚本：

- `scripts/append_daily_quotes_to_history_cache.py --data-date YYYY-MM-DD`：用腾讯批量报价补最新一根日线。内置护栏：断档检测（与上一根间隔超过 1 个工作日拒绝，`--allow-gap` 显式放行）、收盘跳变校验（默认 35%，`--max-close-jump-pct` 可调）。
- `scripts/backfill_daily_history_cache.py`：错过多个交易日的区间回补（腾讯 K 线直连）。
- `scripts/rebuild_scan_snapshots_from_history_cache.py`：从历史缓存离线重建全市场快照（多进程，`--codes-from-cache --force-current`）。
- `scripts/cleanup_legacy_history_cache.py`：canonical 全部落位后清理旧命名缓存（默认 dry-run，`--apply` 删除；只删 canonical 数据不落后于 legacy 的文件）。

**qfq 基准漂移风险**：append 注入的是未复权报价、backfill 回补段按"当前"qfq 基准抓取——若区间内发生除权，拼接点会与旧缓存跳变。脚本已做涨跌停幅度校验拦截明显跳变，但除权导致的均线/矩形轻微失真需下次全量重取自然修正。

**在线刷新边界**：以上断档与收盘跳变护栏只用于离线 append 脚本，不覆盖应用内 `force_refresh` 路径。在线路径会把历史 provider 帧与腾讯实时 bar 按日期合并，并可能在收盘后写入历史缓存；当前没有跨源复权基准、长断档或拼接跳变校验。数据身份会标记来源，但这不等同于已验证 qfq 连续性。若发现历史均线/结构异常，应优先回到缓存与 provider 诊断核查；不要把离线脚本的护栏误认为在线刷新也已拦截。

日线 CSV 与 `.meta.json` 分别通过临时文件原子替换，但两者不是一个文件系统事务。新写 sidecar 带 `cache_payload_revision`，读取时会校验 canonical OHLCV 内容与元数据是否匹配；错配缓存会被拒绝，旧 sidecar 没有该字段时仍兼容读取。`generated_at` 是本次分析请求时间，`cache_written_at` 才是本地缓存落盘时间。

## Market Reference Metadata

交易日历和历史时点股票池保存在 `.cache/market_metadata.sqlite3`：

```bash
./venv/bin/python scripts/refresh_market_metadata.py calendar
./venv/bin/python scripts/refresh_market_metadata.py universe --as-of 2026-09-22
./venv/bin/python scripts/validate_market_metadata.py --as-of 2026-09-22
./venv/bin/python scripts/audit_market_universe.py --as-of 2026-09-22
```

日历刷新读取当前 AkShare 包内置历史序列，并用仓库内经审核的交易所年度休市公告
清单覆盖 2026 年，不在运行时抓取网页。日期级证据可通过 `session_context` 区分
`provider` 与 `exchange-official`。股票池刷新访问交易所名单接口；历史快照会明确
记录 coverage 缺口，不得将 `partial` 当成完整回测股票池。

`audit_market_universe.py` 将缺口分为成员资格阻断、展示信息和治理三类，并分别输出
`current_scan_eligible` 与 `historical_research_eligible`。自动历史任务应增加
`--require-historical-ready`，当前北交所退市历史未补齐时会以状态码 2 主动拒绝。

## Scan Snapshot Storage Audit

SQLite 已接管候选列表、筛选和排序查询，但 `.cache/scan_snapshots/` 中的 JSON
仍是候选详情与复现的事实源，不能因为 SQLite 可查询就直接删除。使用只读工具盘点：

```bash
./venv/bin/python scripts/audit_scan_snapshot_storage.py \
  --keep-latest-days 5 \
  --output .cache/reports/scan-snapshot-storage.json
```

工具会按快照日统计 active/archive 逻辑文件数与体积，并核对 SQLite manifest 的目录、
成员数、内容 revision、storage revision、文件大小和解析状态。`archive_review` 只表示该日
可进入冷归档评估，不表示可删除。审计脚本故意不提供 `--apply`；实际移动由下方可逆迁移
命令单独负责。

## Scan Snapshot Cold Archive

冷归档采用按快照日分割的 ZIP，每个成员都在 `_manifest.json` 中记录字节数和
SHA-256。归档命令只复制与校验，不删除源 JSON：

```bash
./venv/bin/python scripts/archive_scan_snapshot_day.py --snapshot-day 20260515
./venv/bin/python scripts/archive_scan_snapshot_day.py --snapshot-day 20260515 --verify-only
```

读链会优先读取 `.cache/scan_snapshots/` 中的活跃文件；只在精确路径缺失时，才从
`.cache/scan_snapshot_archives/scan_snapshots_YYYYMMDD.zip` 读取并校验。候选详情和
显式历史日回放已接入该读链，历史日列表默认由 SQLite 聚合。

SQLite schema v9 已把 active 文件与已验证归档视为同一个逻辑快照集合，并分别记录内容
revision 与 storage revision。迁移分四种模式：

```bash
# 零写入预检
./venv/bin/python scripts/migrate_scan_snapshot_day_to_archive.py --snapshot-day 20260515

# 第一阶段：源文件仍保留，只登记归档路径、成员和 checksum
./venv/bin/python scripts/migrate_scan_snapshot_day_to_archive.py \
  --snapshot-day 20260515 --register

# 第二阶段：仅移入可恢复隔离区，不永久删除
./venv/bin/python scripts/migrate_scan_snapshot_day_to_archive.py \
  --snapshot-day 20260515 --apply

# 回滚到活跃目录
./venv/bin/python scripts/migrate_scan_snapshot_day_to_archive.py \
  --snapshot-day 20260515 --restore
```

`--apply` 前必须确认所有运行中的 Web 进程都使用 schema v9 和 archive-aware 读链。2026-09-27
的 20260515 试点已完成 `--apply`：唯一源 JSON 被移入 `.cache/scan_snapshot_quarantine/20260515/`，
没有永久删除。全库审计确认 active 103,436 + archive 1 = manifest 103,437、revision 完全匹配；
该日归档详情和 SQLite 历史日读取通过。其余日期不随本次批量迁移，需观察试点后再逐日决定。
脚本没有 purge/delete 模式；隔离区保留期和任何未来永久清理必须另行制定策略。

若存储层对账遇到损坏或冲突归档，扫描任务仍会记录索引降级并继续尝试排序上下文；全局
source-sync 会保持未通过，需先修复归档再执行全量对账，不能把失败视为归档已验证。
