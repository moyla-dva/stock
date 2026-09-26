---
status: accepted
decision_date: 2026-09-25
last_verified: 2026-09-26
supersedes: []
---

# ADR-0002: Candidate Ranking Ownership

## Context

候选排序曾混合股票自身的信号/结构、行业与概念候选聚集、板块指数行情、市场宽度、
宏观许可和按行业分桶的回放统计。它们的语义、数据时点和覆盖率不同，却被压入
`final_score` 与 `v2_priority_score`，同时又可能改变环境许可。旧 RankContext 因而难以
说明某只股票为何排在当前位置，也会受过期或缺失的类别行情影响。

产品选择已确认：这是人工判断优先的研究工作台。行业和概念标签有助于浏览候选分布，
但不能代表单只股票的结构质量；板块指数/宽度与候选池内的类别聚集也不构成当前个股
的买入许可证据。

## Decision

1. **个股候选优先级只消费个股级信号、结构、确认、风险和该股自身的宏观许可。**
   `build_c_signal_v2_priority` 以 `rank_score` 为个股分数基底，不读取旧 `final_score`、
   `sector_score`、`concept_score` 或 `market_boost`。
2. **环境许可只看该股的 V2 宏观事实与入场类型。**行业/概念分数、计数、指数行情和
   宽度不能改变许可、候选组别或执行状态。
3. **行业和概念作为描述性维度保留。**候选页仍可按行业/概念筛选、查看候选数量和
   覆盖率；这些字段不生成每股加分，也不生成市场强弱标签。
4. **退役候选共振与类别分桶回放。**在线工作区不再执行板块/概念共振、市场行情加分、
   类别环境许可或按行业/概念分桶的回放校准。旧服务端板块行情 API 返回 `410 Gone`，
   不再抓取或刷新板块行情。
5. **RankContext 继续作为版本化物化层。**它保存重算后的候选优先级、分组与个股宏观
   环境许可；旧 schema 列 `sector_score`、`concept_score`、`market_boost` 保持可空以兼容
   旧数据结构，但旧策略 revision 不再由当前查询应用，新策略不得写入这些因子。策略标识为
   `stock-structure-macro-only-v1`。
6. **显式选择排序模式并校验覆盖。**`snapshot_local` 使用快照内排序字段；兼容 API
   参数 `rank_mode=contextual` 使用完整、匹配当前版本的 RankContext。此处
   `contextual` 是历史 API 名称，不代表行业/概念行情共振；覆盖缺失时明确回退，禁止
   混用旧 revision。
7. **版本职责分开。** `SCAN_STRATEGY_VERSION` 标识扫描生成的信号事实、事件状态与单事件
   Plan Gate 语义；`RANKING_POLICY_VERSION` 标识工作区优先级、队列分组与个股宏观环境许可，
   此类变化通过新政策版本并定向重建 RankContext，不要求重扫原始行情。`RANK_CONTEXT_SCHEMA_VERSION`
   与 `SCAN_SNAPSHOT_SCHEMA_VERSION` 分别标识物化上下文和快照序列化结构。兼容旧快照的
   回填映射修正不改变扫描生成逻辑或序列化结构，因此不单独 bump 扫描策略版本。

本 ADR 只裁决排序所有权，不自动切换默认读源。后续默认读源切换已由
[ADR-0005](0005-sqlite-candidate-read-default.md) 在独立验收后批准；页面视觉与交互重设计
仍不在本 ADR 范围内。

## Consequences

- 同一快照与策略版本的候选分数不再因行业标签数量、板指缓存新旧或概念映射变化而
  漂移；类别行情缓存无需为候选页刷新。
- 宏观许可仍能基于股票自身的 MA60/MA250/周线等事实作出放行、等待或否决。
- 行业/概念仍便于浏览和筛选，但不能解释成板块强势或个股可交易性。
- 新旧 RankContext 排序可能明显不同；变更只说明输入定义不同，不代表预测能力提升。
  应记录新 revision、候选覆盖和 Top-K 对照，并通过时间前推证据另行评估。
- 旧数据库列和离线研究资料为迁移/审计保留；旧行情 API 明确返回 `410 Gone`。不得把
  历史非空分数复用为当前排序因子。
- 旧市场结构计算模块与本地行情缓存仍可能留在仓库/磁盘上；它们没有当前 API 调用链，
  保留不代表功能启用。

## Rejected Alternatives

### Preserve Runtime Re-ranking

在线读取时继续重算会让同一快照因外部缓存和画像变化而重排，且难以复现历史页面。

### Keep Board/Concept Resonance As A Second Ranking Mode

理论上可作为实验视角，但当前机制存在候选池内生性、字段重复计分、近乎顶格、市场
行情陈旧/缺失和覆盖不完整问题。产品已明确其不属于当前工作流；若将来重做，应作为
独立研究实验重新定义输入与验收，不复活旧加分。

### Remove RankContext Entirely

物化覆盖层仍用于持久化工作区重算后的优先级和宏观许可，并校验候选集合与版本完整性；
删除它会让 SQLite contextual 读模型退回无法区分的快照优先级事实。
