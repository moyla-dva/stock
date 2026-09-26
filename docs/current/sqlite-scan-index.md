---
status: current
contract_version: 3
last_verified: 2026-09-26
implementation_status: default-summary-detail-frontend
owners: local-user
supersedes: []
---

# SQLite Scan Index

## Current Status

SQLite 扫描索引已经接管候选页默认摘要、筛选、分页与按需详情读取。详情 API 通过
manifest 定位原始 JSON 快照并校验 revision，再投影为 `CandidateDetail`；若单条详情读取
失败，只为当前候选回退到精确 JSON 详情。列表索引不完整、上下文排序不可用或分页失败时
整页回退 JSON，并在页面标明来源；不会将两种来源拼在同一页。`?candidate_source=json`
可以显式使用旧 JSON 工作区读链。

JSON 快照仍是完整扫描事实和详情来源；SQLite 是可重建的默认查询索引，不是新的事实源。
数据后台和明确的 JSON 回退路径仍可读取快照。

## Storage Boundary

SQLite 保存：

- 快照路径、文件状态、内容哈希和策略身份。
- 按日期、策略版本和复权方式聚合的扫描运行索引。
- 每个快照命中池的 `CandidateSummary`。
- 候选分页、排序和常用筛选所需的列。

SQLite 不保存：

- 完整 V2 facts。
- 归一化 K 线序列。
- 完整交易计划。
- 完整候选详情。
- 日线或分钟线行情。

详情继续由 `snapshot_manifest.path` 定位到不可变 JSON 快照。

索引状态另外记录 `build_scope`、`snapshot_index_revision` 和源目录同步 revision。局部验证和
从后台单票扫描新建的索引标记为 `partial`。`index_complete` 只有在以下条件同时成立时为真：

- `build_scope=full`；
- manifest 无解析失败；
- 严格文件规则识别出的源快照数量与 manifest 成功行数一致；
- `source_sync_revision` 与当前 `snapshot_index_revision` 一致。

新增、修改或删除快照都会使 source-sync 失效；完成目录对账后才恢复完整状态。不能再用
“数据库存在”或“有候选行”推断全市场覆盖完整。

## Tables

### `scan_runs`

按 `snapshot_day + strategy_version + data_adjust + start_key` 聚合快照数与候选数。当前状态为 `observed`，不宣称对应扫描任务一定完整成功。

### `snapshot_manifest`

每个 JSON 文件一行，保存：

- 路径、大小和修改时间。
- SHA-256 内容哈希。
- 股票、日期、策略和复权身份。
- 快照声明的已计算扫描类型。
- 解析成功或失败状态。

### `candidate_summaries`

每个 `snapshot + pool` 一行。只保存稳定摘要列和短 JSON 数组，不复制完整结果对象。

### `candidate_concepts`

候选与概念的多对多索引，用于概念精确筛选和搜索，避免查询时遍历 `concepts_json`。

### `candidate_reason_tags`

候选与标准原因标签的多对多索引。只接受中央注册的机器键，未知 reason 不再静默匹配全部候选。

## Default Read API

候选页默认消费以下摘要与详情 API；它们也可单独用于影子验证：

```text
GET /api/scan_index/status
GET /api/scan_index/candidates?scan_type=opportunity&limit=120
GET /api/scan_index/candidates?scan_type=opportunity&rank_mode=contextual
GET /api/scan_index/candidates/600001?scan_type=opportunity
```

候选接口返回 `CandidateSummary` 分页，支持 `snapshot_day`、`sector`、`concept`、`signal_key`、`reason`、`query`、`limit` 和 `offset`。它不读取快照 JSON，也不构建 workspace。
快照绝对路径仅在服务端 manifest 内使用，不属于 `CandidateSummary` API 契约。
分页响应默认使用 `ranking.mode=snapshot_local`，表示按快照内在优先级排序。
`rank_mode=contextual` 只在目标 run 的覆盖层完整时启用；每条候选新增独立
`rank_context`，基础 `priority_score` 保持不变。覆盖层缺失、策略版本过期、类别因子不为空
或因快照重建失效时，响应明确返回 `mode=snapshot_local` 和 `fallback_reason`；旧版本即使仍
保存在 SQLite 中也不会被当前接口应用。

当前排序政策见 [ADR-0002](../adr/0002-candidate-ranking-ownership.md)：工作区
`contextual` 优先级只基于个股信号/结构、确认、风险和该股宏观许可，不含行业/概念共振、
板块指数行情、市场宽度或类别分桶回放。`sector_score`、`concept_score`、`market_boost`
等 SQLite 列为兼容旧数据结构而保留；新策略写入 NULL/空对象。此处 `contextual` 是
兼容 API 参数，不再表示“共振排序”。行业与概念标签、候选计数仍用于描述、筛选和分布统计。
旧板块行情查询和刷新端点 `/api/board_market`、`/api/board_market/refresh` 返回 `410 Gone`，
不会触发外部板块行情请求。

单候选详情接口通过 manifest 定位原始快照，优先读活跃 JSON，精确路径缺失时可回读按日冷归档；归档成员先校验字节数与 SHA-256，再校验 SQLite 记录的 snapshot revision。随后返回 schema v2 的 `CandidateDetail`。它保留决策状态、解释、评分上下文、规则结果、结构事实、许可、条件计划、画像关系、风险和环境上下文，但剔除 `normalized_bars` 和结构候选全集。快照与索引 revision 不同时返回 409，不拼凑半成品详情。前端 adapter 将该稳定模型映射到现有详情展示；接口错误或读模型版本不兼容时，只回退所选候选的 JSON 详情，不改变其余 SQLite 摘要列表。

`/api/scan_workspace/candidates` 继续作为 JSON 兼容与故障回退接口。详情请求传入摘要的精确
`snapshot_day`、`event_date` 和代码，并校验返回身份，避免错接同代码的其他池或日期。

本地体验：普通首页即使用 SQLite 候选读模型；页面缓存条显示摘要来源、索引快照数和排序
模式。添加 `?candidate_source=json` 可显式切回旧 JSON 工作区。若一次运行因索引故障自动
回退，刷新页面会重新尝试 SQLite。

## Rebuild

增量刷新默认跳过路径、大小和修改时间均未变化的有效文件：

```bash
./venv/bin/python scripts/rebuild_scan_index.py
```

清空并重建的只是 SQLite 索引，不会删除源快照：

```bash
./venv/bin/python scripts/rebuild_scan_index.py --reset
```

索引同步后可分别物化完整快照与当前最新新鲜候选的上下文排序。`snapshot` 用于显式
历史日查询；`latest_fresh` 与默认 latest JSON 工作区采用相同的新鲜度筛选。两个 scope
各自持有 revision，查询会按 `recent_only` 选择对应上下文，并校验候选 ID 集合完整：

```bash
./venv/bin/python scripts/materialize_candidate_rank_context.py
./venv/bin/python scripts/materialize_candidate_rank_context.py --scope latest_fresh
```

任一候选快照重新索引后，对应覆盖行会通过外键失效；新鲜候选集合变化时，ID 集合完整性
检查也会拒绝使用旧上下文。在重新物化前 contextual 查询不会使用残缺结果。

小范围验证：

```bash
./venv/bin/python scripts/rebuild_scan_index.py --limit 100 --reset --json
```

该命令产生的数据库会明确标记为 `partial`，不能作为全市场候选读源。

逐条核对某一快照日的新旧摘要：

```bash
./venv/bin/python scripts/validate_scan_index.py --snapshot-day 20260922
```

真实请求影子比较（默认比较三池，排序差异只记录、不作为失败条件）：

```bash
./venv/bin/python scripts/compare_scan_candidate_reads.py
./venv/bin/python scripts/compare_scan_candidate_reads.py --reason plan_ready
./venv/bin/python scripts/compare_scan_candidate_reads.py --snapshot-day 20260922
./venv/bin/python scripts/compare_scan_candidate_reads.py \
  --rank-mode contextual --require-order
```

比较器把门禁拆成三层：候选集合与决策字段属于硬门槛；名称、行业、概念等描述字段
单独报告；优先级、最终分和顺序属于排序诊断。只有明确决定新旧读链必须保持相同排序
时才使用 `--require-order`。

默认数据库位置：

```text
.cache/scan_index.sqlite3
```

可以通过 `STOCK_ANALYZER_SCAN_INDEX_DB` 或 `--db` 指定其他位置。

## Rollout Gates

接管候选接口前必须满足：

- 全量索引无未解释的解析失败。
- 同日期、同策略、同池的新旧候选数量一致。
- 候选代码、信号、状态、许可和优先级逐条一致。
- 新查询结果保留前端真正消费的摘要字段。
- 详情请求能通过 manifest 精确定位原始快照。
- 新索引不可用时，API 能明确降级或拒绝，不能静默返回空池。
- 写入新快照后，索引更新具备明确的一致性策略。
- 前端摘要适配不将摘要缺少的字段伪装成完整详情；按摘要记录的精确快照身份加载 JSON 详情。
- 筛选后的后续页使用 SQLite `offset`，失败时整页切回 JSON，不能混并新旧两种读源。

JSON 工作台保持独立回退读链。lite/compact 响应缓存优先用 SQLite manifest revision
生成指纹；索引不可用时回退到快照文件元数据签名，避免缓存优化反过来阻断 JSON 页面。
SQLite 候选 API 对空/部分索引和数据库错误明确返回可重试的 503，不把故障表示为空候选。
文件指纹回退需要遍历快照文件元数据，索引故障期间缓存校验会较慢，但不改变候选数据来源。
定向回归覆盖了默认 lite/compact 页面，而不只覆盖跳过持久缓存的 `compact=0` 路径。

Web 后台扫描现在在任务进入终态前执行两个后处理阶段：先批量索引本任务对应的最新
快照，再尝试发布完整 contextual 排名 revision。阶段结果分别记录在 job
`postprocess.result.index` 与 `postprocess.result.rank_context`。排名依赖未变化时复用
现有 revision；排名物化失败时返回 `indexed_context_failed` 并声明
`fallback=snapshot_local`，不会把已经完成的市场扫描改写为失败。索引阶段本身失败仍
记录为 postprocess 失败，在未来切换读接口时必须视为降级条件。离线脚本直接写快照后，
仍需运行增量 rebuild 与排名物化命令。新 head 发布后会在同一事务内清理该运行身份的
旧 revision，其他交易日和基础候选事实不受影响。

## Validation Record

2026-09-22 使用 20 份真实快照进行小范围验证：

```text
files discovered: 20
files indexed: 20
parse failures: 0
candidate summaries: 15
elapsed: 0.015 seconds
database size after close: 72 KB
```

该结果只验证兼容性，不代表 9 万份快照的全量耗时和最终数据库体积。

同日完成 schema v2 全量构建及最新日逐条核对：

```text
stock snapshot files: 92,300
files indexed: 92,300
parse failures: 0
candidate summaries: 53,726
scan runs: 23
full rebuild: 43.776 seconds
incremental unchanged refresh: 3.673 seconds
database size: 82 MB

2026-09-22 current-strategy source candidates: 4,041
2026-09-22 indexed candidates: 4,041
missing / extra / mismatched: 0 / 0 / 0

50-row cold process query: 0.320 seconds
50-row warm median query: 0.005 seconds
```

加入概念与原因标签索引后，schema v3 再次全量重建并核对：

```text
stock snapshot files: 92,300
files indexed: 92,300
parse failures: 0
candidate summaries: 53,726
concept memberships: 362,882
reason tags: 44,840
scan runs: 23
full rebuild: 59.249 seconds
database size: 121 MB

2026-09-22 current-strategy source candidates: 4,041
2026-09-22 indexed candidates: 4,041
missing / extra / mismatched: 0 / 0 / 0

PRAGMA integrity_check: ok
PRAGMA foreign_key_check violations: 0
50-row pool query median: 0.006 seconds
50-row reason query median: 0.007 seconds
50-row concept query median: 0.008 seconds
```

schema v4 是一次可向前迁移的身份补充：`snapshot_manifest` 与
`candidate_summaries` 新增 `calendar_id`、`calendar_revision` 和
`calendar_evidence_level`。迁移不会猜测旧快照身份；源快照没有这些字段时继续保存
`unknown`。迁移同时把已有候选行的读模型版本规范为 `CandidateSummary` v2，但不改变
候选业务内容。2026-09-23 现有数据库已原位迁移并复核，仍为 full scope，92,300 份快照、
53,726 条候选、0 个解析失败。

schema v5 新增 `rank_context_runs`、`candidate_rank_contexts` 和
`rank_context_heads`。2026-09-23 最新 revision 覆盖 4,041 条候选，完整性为
4,041/4,041；context revision 为内容寻址哈希。在明确选择 `rank_mode=contextual` 的
单日验证中，三池候选集合、决策字段、描述字段、上下文分数和完整顺序全部一致，
4,041 个位置零位移。关闭不参与排名的历史对比后，完整物化本机观测约 6.7 秒；依赖
未变化时复用检查约 1.1 秒；SQLite contextual 首屏本机观测约 0.03 秒。这些是特定
快照、缓存状态与排序模式下的单机观测，不是服务等级承诺。

首次真实请求影子采样显示候选总数一致，但 opportunity 前 120 条只有 30 条重叠。
比较器最初还发现 6 条显式 false 和 706 条显式空列表被错误回退的问题；修正
“字段存在优先”并强制重投影后，三池 4,041 条候选的集合、硬决策字段和描述字段均为
零差异。使用 `snapshot_local` 与旧工作区的动态排序比较时，成员和事实相同但顺序不同：
当时旧工作区在读取时叠加全池板块/概念共振并重算优先级，索引则使用快照内稳定的本地分数。
这是旧排序政策下的历史比较。当前已按 ADR-0002 退役这些类别因子，新政策的 RankContext
需单独重物化和验收，不能直接把旧版 parity 结论当作新政策结果。此前一次单日性能观测中，
旧工作区三池完整读取约 47 至 63 秒，SQLite 约 1.8 至
1.9 秒；这不是本次多日影子比较的受控基准。当时排序权归属未决，SQLite 只能作为摘要读
模型影子运行，不能直接替换现有列表接口；后续范围不一致已在 2026-09-24 真实扫描中定位
并以双 scope 修复，见下方最新验证记录。

2026-09-23 又以默认 `snapshot_local` 对五个历史快照日、三个候选池进行逐页对照，
共 22,085 条候选的集合、决策字段、描述字段和分页均一致，15 组排序均不同。它与上面
`contextual` 的单日等序验证采用了不同排序模式，并不矛盾。详见
[`多日影子比较记录`](../research/scan-candidate-read-shadow-2026-09.md)。

2026-09-24 首次 latest 对照中的 8 条 opportunity、3 条 risk 排名字段差异，根因是 full
snapshot 排名上下文与 latest-fresh 工作区的候选范围不同。拆分上下文 scope 后，9/24 latest
三池 5,118 条候选的完整排序零差异，`plan_ready` 71 条也全序一致；这消除了当前已知的
长尾排序偏差。该结果是旧排序政策下的历史基线，不代表类别因素退役后的现行结果。完整证据与限制见
[`9/24 真实扫描复核`](../research/scan-real-market-validation-2026-09-24.md)。

2026-09-25 依据 accepted ADR-0002 将候选排序收敛到 `stock-structure-macro-only-v1`，
并分别重算 9/24 完整 `snapshot` 与 `latest_fresh` 覆盖：5,134 / 5,131 条，revision 分别为
`sha256:ca895153b42c273043b5334b23b89d4a78f6069bb88b75de500f96d89ee753cd` 和
`sha256:b5fece15d49cf7cb245894238674a8aa2ea173fd1ad706798c3287adfdf2c077`。逐列检查确认行业、
概念和市场加分均为空，市场上下文为空对象。旧日期 revision 若政策版本不匹配，也会由查询层
拒绝并回退 `snapshot_local`。本次只确认实现与读链一致，不比较收益表现，也不宣称新排序预测更好。

2026-09-23 使用真实最新候选进行详情投影冒烟验证：

```text
CandidateDetail status: 200
CandidateDetail payload: 19,387 bytes
CandidateDetail local read: 0.003 seconds
normalized_bars exposed: false
snapshot absolute path exposed: false
```

性能数字是本机生产快照上的一次观测，不是跨机器服务等级承诺。

2026-09-25 将候选详情读模型切换为 opt-in `CandidateDetail` schema v2。真实页面选中
2026-09-24 重庆银行候选，详情 API 通过精确快照身份校验后返回 200；V2 闸门、交易计划、
依据、风险和画像证据均在现有详情面板正常呈现，浏览器无 JS 错误。详情接口失败时只对
当前候选回退原 JSON 详情，定向前端回归和全量 376 项测试通过。

2026-09-26 完成 schema v8 全量重建和默认切换门禁：

```text
strict source snapshots: 103,437
indexed / failed: 103,437 / 0
candidate summaries: 63,683
database size: 160 MB
full rebuild: 112.695 seconds

2026-09-24 source / indexed candidates: 5,134 / 5,134
opportunity / risk / bottom_div: 3,641 / 1,156 / 337
missing / extra / mismatched: 0 / 0 / 0
contextual complete-order comparison: passed for all three pools
snapshot / latest_fresh rank coverage: 5,134 / 5,131

scan planner: about 44.56 seconds -> 0.41 seconds
cache fingerprint: about 1.97 seconds -> 0.04 seconds
warm opportunity query: about 0.09-0.10 seconds
```

schema v8 在 manifest 增加规划元数据和复合索引，并以同一 source-sync 契约约束候选 API、
缓存指纹和扫描计划。候选页由 [ADR-0005](../adr/0005-sqlite-candidate-read-default.md)
批准默认使用 SQLite；JSON 保留为详情事实源和故障回退。
