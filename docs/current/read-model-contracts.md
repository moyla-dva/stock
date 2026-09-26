---
status: current
contract_version: 2
last_verified: 2026-09-26
owners: local-user
supersedes: []
---

# Read Model Contracts

## Purpose

当前扫描结果在列表、详情、缓存和单票页面之间复用同一个大型嵌套字典。所谓 compact 候选仍包含大量解释、行业、概念和 V2 内部字段，不适合作为长期 API 契约或 SQLite 表结构。

目标读模型分成三类：

```text
CandidateSummary
CandidateDetail
SingleStockAnalysis
```

读模型服务于页面查询，不替代策略内部 facts，也不要求立即删除现有响应字段。迁移期间允许旧响应和新响应并存，但新模型必须有独立 `schema_version`。

## Common Identity

三个读模型共享以下身份字段：

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | 读模型结构版本 |
| `strategy_version` | string | 策略版本 |
| `code` | string | 六位股票代码 |
| `as_of` | string | 数据覆盖的最后市场时间 |
| `bar_state` | string | `closed`、`preview` 或 `mixed` |
| `data_source` | string | 主要行情来源 |
| `data_revision` | string | 输入数据内容版本或哈希 |
| `start_key` | string | 历史窗口起点身份，例如 `20250429` |
| `generated_at` | string | 结果生成时间，ISO 8601 |
| `calendar_id` | string | 判定 K 线状态所用的日历身份 |
| `calendar_revision` | string | 日历内容 revision |
| `calendar_evidence_level` | string | 日历来源证据等级 |

身份字段缺失时，可以返回 `unknown`，但不能用空字符串暗示已确认。
`CandidateSummary`、`CandidateDetail` 与 `SingleStockAnalysis` 当前均为 schema v2；
`CandidateDetail` 通过其 `summary` 携带候选身份。

## API Read Paths

稳定读模型通过独立接口提供。候选页与单票页均默认使用稳定读模型，并保留兼容接口回退：

```text
GET /api/scan_index/candidates
GET /api/scan_index/candidates/<code>
GET /api/single_stock_analysis?code=<code>
```

前两个接口分别对应 `CandidateSummary` 和 `CandidateDetail`，第三个对应 `SingleStockAnalysis`。

```text
?candidate_source=json         候选页回退到 JSON 工作区读链
?single_stock_source=legacy    单票页回退到既有 /api/analyze 接口
```

候选页默认使用 `/api/scan_index/candidates` 及其详情接口；单票页默认使用
`/api/single_stock_analysis`。两条读链相互独立，也不改变扫描快照事实源。

## CandidateSummary

`CandidateSummary` 只服务候选分页、排序和轻量筛选。目标是单条稳定在约 1 至 3KB，而不是复制完整扫描结果。

建议字段组：

```text
identity
name
pool
event_date
signal_key
signal_label
state
permission
plan_status
priority_score
priority_group
reason_summary
missing_confirmations
invalidation_price
sector
concepts
profile_quality
```

当前 SQLite 实现中的 `priority_score` 是快照本地、可复现的内在优先级，默认响应返回
`ranking.mode=snapshot_local`。请求 `rank_mode=contextual` 且完整覆盖层存在时，每条候选
另外返回 `rank_context`，原有 `priority_score` 不被覆盖；响应通过
`ranking.score_field=rank_context.priority_score` 声明实际排序字段。覆盖层缺失或不完整时
明确回退到 `snapshot_local` 并返回 `fallback_reason`。

约束：

- 不包含完整 `facts`。
- 不包含完整 `trade_plan`。
- 不包含完整行业和概念统计对象。
- 不包含仅用于单个前端组件的重复标签字段。
- 排序所需字段必须直接可查询，不能读取 JSON 后再计算。
- `pool`、`signal_key`、`state`、`permission` 使用稳定机器值，中文标签由统一注册表产生。

## CandidateDetail

`CandidateDetail` 在用户选择候选时按需加载。它负责回答“为什么出现、还缺什么、何时失效”，不承担全市场分页。

建议字段组：

```text
summary
decision_state
score_context
decision_explanation
rule_results
structure_facts
permission
conditional_plan
risk_conditions
environment_context
profile
related_snapshot
```

约束：

- `summary` 与对应 `CandidateSummary` 具有相同身份和排序字段。
- `conditional_plan` 明确是模型计划，不代表用户执行或持仓。
- `rule_results` 保留机器键和可展示解释，不能只有拼接后的自然语言。
- 详情可以引用完整快照位置，但在线请求不应重新构建全部 workspace。
- 未找到详情时返回结构化错误和快照身份，不使用半成品摘要伪装详情。

## SingleStockAnalysis

`SingleStockAnalysis` 独立于候选池。用户直接输入代码时，不应先构建全市场 workspace。

建议顶层结构：

```text
identity
profile
market_data
chart
signal_observations
current_state
conditional_plan
timeframes
event_study
data_quality
```

约束：

- `market_data` 明确末根 K 线状态和最新行情时间。
- `chart` 只包含绘图序列和标记，不夹带工作区统计。
- `signal_observations` 区分已确认信号与盘中预判。
- `current_state` 不推断用户真实持仓。
- `event_study` 使用事件研究术语，并明确 `entry_model`、`horizon` 和样本数。
- `timeframes` 明确每个周期的真实聚合语义；当前 4h 若为交易日内聚合，不应伪装为独立四小时市场周期。
- `data_quality` 返回来源、缓存状态、缺口和降级情况。

当前默认实现复用现有单票分析结果，不重复计算信号，再按上述顶层结构投影。前端通过 `singleStockReadModelAdapter.js` 将稳定模型映射到现有图表消费结构，因此完整历史 K 线及其信号标记继续显示；这不是只读原始行情接口，也不会额外运行第二遍信号分析。页面可通过 `?single_stock_source=legacy` 回退到 `/api/analyze`。

图表中明确声明 K 线数组顺序为 `open / close / low / high`；`current_state` 排除与图表重复的 `normalized_bars` 和 `rectangle_candidates`。日线上游已传递 `bar_state`、`data_source`、`data_revision`、`generated_at` 和缓存状态；旧缓存无来源证据时仍使用 `unknown`。

## Error Contract

所有新 API 错误至少包含：

```json
{
  "error": {
    "code": "stable_machine_code",
    "message": "可展示说明",
    "retryable": false,
    "details": {}
  }
}
```

生产响应不直接返回原始异常字符串。服务端日志保留异常堆栈和内部上下文。

## Storage Mapping

SQLite 第一个离线实现只持久化 `CandidateSummary` 和查询身份：

```text
scan_runs
snapshot_manifest
candidate_summaries
candidate_concepts
candidate_reason_tags
```

池归属直接由 `candidate_summaries.pool` 表达，不增加重复的 pool membership 表。概念和标准原因标签由独立关系表支持索引查询；`concepts_json` 仅作为摘要返回字段。`workspace_builds` 和 `data_source_status` 等运行状态只有在明确查询需求后再建表。

`CandidateDetail` 先从不可变快照按身份读取，`SingleStockAnalysis` 继续按请求计算。不要把完整快照 JSON 原样复制到 SQLite。

当前默认实现已将 `CandidateSummary` 分页与 `CandidateDetail` 详情分开。详情端点通过
`snapshot_manifest` 定位原始文件并校验 revision，不经过 workspace；schema v2 明确投影
决策状态、评分上下文和详情所需的结构事实，并排除 `normalized_bars`、
`rectangle_candidates` 等大对象。索引不可用时整页回退 JSON；显式
`?candidate_source=json` 也可使用兼容读链。

2026-09-23 真实单票冒烟验证：原 `/api/analyze` 响应约 197KB，`SingleStockAnalysis` 投影约 130KB；两者使用同一次分析结果，新模型保留 343 根 K 线、信号标记、多周期摘要和事件研究口径。

## Migration Checks

迁移必须满足：

- 同一扫描运行中新旧候选数量一致。
- 同一候选的池归属、信号、状态、许可和优先级一致。
- 新列表接口不读取完整 detail。
- 候选详情不构建 6000 条 workspace。
- 单票分析不依赖候选索引存在。
- 所有读模型都能追溯到快照或行情 revision。
