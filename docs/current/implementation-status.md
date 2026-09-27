---
status: current
contract_version: 1
last_verified: 2026-09-27
owners: local-user
supersedes: []
---

# Implementation Status

本表区分“基础对象已实现”“生产链已接管”和“仍需真实证据”，避免把底座完成等同于
产品能力已经上线。

| Track | Foundation | Production use | Remaining gate |
| --- | --- | --- | --- |
| 产品角色与术语 | 已完成产品契约和 ADR | 当前页面已统一为“事件研究 / 入场研判 / 信号后跟踪 / 收益保护”语义，有静态契约测试 | 内部机器字段与历史兼容键保留；不以改名改变行为 |
| SQLite 扫描索引 | schema v9、active/archive 存储层对账、规划元数据、增量同步、影子比较器、revision 化排名上下文和 CandidateDetail v2 已完成 | 候选页默认使用 SQLite 摘要与详情；JSON/按日 ZIP 保存完整事实并作为显式或自动故障回退。扫描计划和缓存指纹也优先使用完整 manifest | 继续观察真实运行；内容变化后重建排名上下文，存储层迁移后重新对账 storage revision |
| 行情身份 | `bar_state/source/revision/generated_at/calendar_*` 已进入单票与新快照 | 日线和快照新鲜度主链已消费；2026 日期使用交易所官方证据 | 旧缓存与旧快照来源仍可能 unknown；2025 及更早日历仍为 provider |
| 当前股票池与日线覆盖 | 独立 SQLite 保存按交易日、revision 管理的名单；画像缓存不作为成员事实 | `/api/stock_list` 与生产扫描共用 `CurrentUniverseService`；9/24 全市场扫描名单 revision 与 5,569 个成员审计一致；5,551 个当日收盘 bar、18 个旧数据样本；真实 `fetch_status`/provider attempts 已核对 | 新扫描出现不一致或新的覆盖异常时再核验；“无新 K 线”不等同停牌 |
| 上游数据治理 | 活跃代码路径与公开条款证据已归档；AkShare/AData 软件许可与上游数据来源已区分 | 当前本地研究继续使用腾讯/TDX 等现有数据提供方；不因授权范围未核实而阻塞开发 | 保留来源/新鲜度标签；仅在计划局域网共享、托管、收费或外部数据服务前重新审查使用条款和分发许可 |
| 历史时点股票池 | 独立 SQLite、结构化 coverage；schema v5 有效期身份导入、区间校验、as-of 投影与审计；已有少量身份变更样例 | 不参与当前生产扫描；历史 coverage 仍为 partial | 仅在开展无幸存者偏差的历史研究时继续补全并通过证据/数据许可门槛；不作为当前扫描前置任务 |
| 稳定读模型 | 三种读模型、API 与前端适配已完成；真实成功响应、503 错误恢复和单票页面均已检查 | 候选默认使用 `CandidateSummary/Detail`，`?candidate_source=json` 回退；单票默认使用 `SingleStockAnalysis`，`?single_stock_source=legacy` 回退；信号只沿用既有单票分析计算一次 | 观察两条默认路径的真实使用，并保持回退契约测试 |
| Facts 时间线 | 轻量 event facts、公共前缀增量复用已完成 | 单票和多周期事件缓存已使用 | 首次访问仍按 lookback 建立；必要时再做结构状态机 |
| 运行时边界 | 分时缓存完整性、TDX 重连、工作台单飞缓存和代码输入边界均有回归测试 | 分时写入使用唯一临时文件原子替换；收盘后会拒绝上午未完整缓存；内存工作台缓存有 LRU 与保留期上限 | 实际 TDX 故障切换仍需在上游故障时观测；不把单机测试当成上游 SLA |
| UI 方向 | 两份同数据、同视觉语言原型已完成；按初步反馈完成一轮静态视觉收敛 | 用户已明确选择候选优先；代码输入/回车/分析命令可切入单票图表；候选池切换会记住各池最近查看项，并仅从当前池结果恢复 | 顺序核对路径已补齐；尚无并排比较，也未做多时段人工任务观察。整体视觉收敛按用户后续交互重设计节奏处理，不据此决定前端技术栈 |
| 存储治理 | 只读盘点、按日 ZIP、逐文件 SHA-256、schema v9 存储层对账、详情/显式历史日回读和可逆迁移命令已完成 | 103,437 份逻辑快照与 manifest 完全对账；20260515 单文件试点已移入可恢复隔离区（active 103,436 / archive 1），归档详情与历史日读取通过 | 观察试点后再决定是否逐日继续；另有 18 个旧日期约 1.93 GiB 仍在 active。永久 purge 未实现 |
| 排名证据 | 已有 next-open 事件研究和 revision-aware SQLite 台账 | 已写入 5 个 context revision run、600 条 1/3 日观察；同 revision 重跑幂等 | 5/10 日仍无完整结果，不改生产权重；持续按交易日积累而不伪造未来数据 |
| 文档治理 | `current / ADR / research / archive` 已建立 | 新文档已按权威顺序管理；已修正排名研究文档的失效代码链接 | 根目录旧文档逐份审查，避免一次性搬迁破坏链接 |

## Next Ordered Work

1. **候选优先关键任务流技术检查已完成**：输入代码、回车、开始/刷新分析会进入单票图表并请求最新行情；候选首页不再启动时悄悄请求默认 `600063`；风险与参与池各自记住最近查看项，支持保留上下文的顺序核对。前端自动化已覆盖代码输入、回车、池切换恢复和快照日隔离；候选页和详情已由用户确认正常。没有新增并排比较 UI。
2. **单票稳定读模型已验收并转默认**：单票页默认使用 schema v2 `SingleStockAnalysis`，映射到现有 K 线图消费结构；单票模型复用同一次行情与信号分析，不二次计算。真实 `600063` 接口返回 345 根 K 线、30 个事件，最新数据为 2026-09-24 收盘、`tencent_direct`、`bar_state=closed`；用户已确认页面正常。`?single_stock_source=legacy` 保留旧接口回退。503 错误路径此前已验证；截至 **2026-09-27，全量 469 项测试通过**。
3. **候选排序与默认读源已落地**：ADR-0002 的个股结构优先排序已经物化；ADR-0005 批准 SQLite 默认读取。103,437 份快照全量对账、9/24 三池 5,134 条候选及完整顺序比较均通过；`?candidate_source=json` 保留回退。
4. **冷归档单日隔离试点已完成，进入观察期**：schema v9 将 active/archive 作为同一逻辑事实集对账，可从 archive-only 重建索引；迁移命令支持 dry-run、register、quarantine 和 restore，没有 purge。2026-09-27 已停止旧进程 5009/5011，保留 5012；20260515 唯一快照已移入可恢复隔离区，完整审计及归档详情/历史读取通过。接下来观察该日读链，不扩展到其他日期。
5. **revision-aware 证据台账已建立，继续积累样本**：已写入 9/18-9/24 的 5 个 context revision run 和 600 条 1/3 日观察；同 revision 重跑保持 5/600，未重复膘胀。5/10 日仍无结果，9/24 候选仍为 0 结果。当前没有可信的排名单调性，不改生产权重。
6. **渐进整理旧文档，UI 重设计继续暂缓**：逐份核实根目录旧文档与链接，按 `current / ADR / research / archive` 归位。明确新交互方向前继续维护原生 JS，不先迁移框架。

2026-09-23 的五个历史快照日、三个候选池影子比较已完成，结果和限制记录在
[`scan-candidate-read-shadow-2026-09.md`](../research/scan-candidate-read-shadow-2026-09.md)。
这不是连续真实交易日观察，也不构成读链切换批准。

2026-09-23 首次真实全市场扫描、覆盖诊断和最新读链影子验收记录在
[`scan-real-market-validation-2026-09-23.md`](../research/scan-real-market-validation-2026-09-23.md)。

2026-09-24 真实收盘扫描、覆盖审计、SQLite 落盘和 latest/`plan_ready` 读链影子比较记录在
[`scan-real-market-validation-2026-09-24.md`](../research/scan-real-market-validation-2026-09-24.md)。

**条件触发、当前不排队**：现有腾讯/TDX 等接口继续作为本地研究的数据提供方；上游条款已归档，只有计划局域网共享、托管、收费或开放外部数据服务时才按具体产品范围重审。只有要做无幸存者偏差的历史研究时，才继续补齐历史时点股票池。只有首次单票性能仍是实际瓶颈时，才把 facts 推进为可序列化状态机。自动化交易属于独立产品阶段，届时需另建执行意图、风控、订单与成交边界，不属于当前 SQLite/候选读链任务。

当前候选优先技术路径以及 SQLite 摘要/详情默认读链已补齐；JSON 继续作为完整快照事实源和故障回退。9/24 真实扫描已核对实际 provider attempts 和名单 revision；其中 18 只只有旧数据，不能由此推断停牌。

离线失败契约已通过索引 API 定向测试：空索引/部分索引返回明确的可重试错误；SQLite 指纹故障时 JSON 工作台回退到文件指纹，仍可读取候选。最新读链的陈旧行情与长尾排序范围差异均已修正；2026-09-27 全量 469 项测试通过。

2026-09-27 存储治理推进记录：SQLite schema v9 的 active 与 checksum archive 共同参与
source-sync。旧进程 5009/5011 已停止，5012 保持运行；20260515 的唯一快照已由 active 移入
quarantine，归档 tier 为 1、active tier 为 0，逻辑总数仍为 103,437。全库审计 `global_parity=true`，
storage revision 匹配；归档 CandidateDetail 与 SQLite 历史日列表均读取成功。其余 18 个旧日期未移动，
当前进入单日试点观察期。本次只做运维迁移和文档同步，最近一次全量测试基线仍为 466 项。

2026-09-27 低优先级读链加固：RankContext 物化现在只接纳明确匹配当前 `strategy_version` 的候选，缺版本与旧版本行均不再进入当前上下文。CandidateDetail 的 SQLite 失败按错误契约分流：`candidate_not_found` 仍尝试精确 JSON 详情兜底；明确不可重试错误不再重复请求；网络/明确可重试错误保留兜底。扫描任务轮询对明确不可重试错误及非 429 的 4xx 不再退避重试；其余网络/未知错误仍受次数上限约束。新增 3 项回归测试；全量 **469 tests OK**。

## Rejected Parallel Core Spike

2026-09-26 外部审查产生的 `stock_analyzer/core/` 并行重写未接入任何生产链或测试，且存在北交所代码归属、日期适配、OHLCV 校验和闸门 fail-open 等契约问题。该代码已从生产包移至
[`prototypes/rejected-core-spike/`](../../prototypes/rejected-core-spike/README.md)，不引入其 Pydantic/cachetools 运行时依赖。现行方向是在稳定读模型和事实族边界逐步强类型化，不建第二套平行交易引擎。
