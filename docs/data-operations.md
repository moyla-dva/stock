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

- 日线历史缓存：单股分析、扫描、回放、真实宽度计算的基础。
- 分钟历史缓存：单股确认时的短周期补充。
- 扫描快照：候选池读取的本地结果。
- 股票画像：名称、行业、概念和关系证据的载体。
- 概念库：股票到概念的本地映射。
- 画像证据：人工或公告确认的股票关系证据。
- 板块行情：行业/概念指数趋势缓存。
- 扫描任务记录：后台扫描进度、历史和中断恢复。
- 概念图谱：实验性关系边，不是当前核心产品入口。

## Scan Policies

- `auto`：跳过有效快照，只补缺失、过期或旧策略结果。
- `cache`：只读本地快照，不计算新结果。
- `force`：忽略当前池快照并重算。

重复发起相同池和相同范围的活动扫描时，后台任务应复用已有任务，而不是创建第二条队列。

## Public Scan Types

当前产品入口只展示：

- `opportunity`：参与候选。
- `risk`：风险验证。

内部兼容仍保留：

- `bottom_div`：底背离/修复观察扫描类型，可存在于历史快照、测试和底层策略中，但不再作为候选池一级入口。

## Governance Placement

| Operation | Placement |
| --- | --- |
| 启动扫描任务 | 数据后台 |
| 强制重扫 | 数据后台 |
| 查看任务历史 | 数据后台 |
| 清理旧策略/无效快照 | 数据后台 |
| 刷新概念库 | 数据后台 |
| 刷新板块行情 | 数据后台 |
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
