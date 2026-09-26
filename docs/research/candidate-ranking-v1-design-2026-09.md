---
status: historical-proposal
strategy_version: "2026.09.20.1"
data_window: "设计基于截至 2026-09-25 的代码审计；尚未做 V1 排名收益验证"
universe: "当前 opportunity/risk/bottom_div 候选池"
entry_model: "评估暂用 next_open；排名本身不产生交易指令"
data_revision: "候选因子审计见 candidate-ranking-factor-audit-2026-09.md"
evidence_level: "算法设计草案；非实证有效性结论"
supersedes: []
---

# CandidateRanking V1 设计草案

> 当前实现说明：本草案中的新连续结构分没有被采纳为生产公式，
> `candidate_ranking_v1.py` 仍只做无权重影子特征投影。生产排序边界以
> [ADR-0002](../adr/0002-candidate-ranking-ownership.md) 为准；SQLite 默认读源由
> [ADR-0005](../adr/0005-sqlite-candidate-read-default.md) 后续独立批准。下文保留的是
> 当时的研究设计，不应读成当前上线状态。

## 定位

CandidateRanking V1 是候选优先的研究排序器：决定先看哪些股票、当前处于什么状态，以及排序依据。它不是涨跌预测器、胜率承诺或交易执行器。

本草案落实已讨论的原则：**个股结构为主，市场环境为条件，风险为约束**。V1 保持确定性、可解释和可回放；当前权重不照搬既有混合分，也不训练 ML 模型。

## 计算边界

排序在每个候选池内独立完成：`opportunity`、`bottom_div`、`risk` 不互相争夺同一名次。先排离散状态层级，再排连续分数；高分不能覆盖被阻断的许可或计划状态。

### 1. 数据可用性

每个候选固定决策时点 `as_of`。参与结构和市场计算的输入必须在该时点已经可见。快照记录行情日期、bar 状态、来源、数据 revision 和评分版本。

数据有效性与数据置信度分开表达：

- 已确认收盘、日期匹配、行情输入完整：可正常计算。
- 旧 bar、盘中 bar、关键字段缺失或身份不确定：仍可作为观察资料，但不能标成完整可执行候选；保留具体状态和缺失原因。
- 市场上下文过期或缺失：不伪装成真实的中性观测。有效调整值可按 0 处理，但必须同时返回 `context_status`，让 UI 区分“中性”与“没有数据”。

### 2. 状态层级

建议 opportunity 的机器层级先定义为：

| 层级 | 初步条件 | 列表语义 |
| --- | --- | --- |
| `ready` | 许可为 attack/breakout/pullback allowed，计划 `ready`，行情有效 | 可执行计划候选；仍需用户自行判断 |
| `waiting` | 结构或信号仍有效，正在等待确认/计划输入 | 等待确认，不与 ready 混成同一优先级 |
| `observe` | research/watch/structure-only 状态 | 研究观察 |
| `blocked` | permission forbidden、plan blocked 或关键行情不可用 | 保留原因，默认排在非阻断候选后，不静默删除 |

这是待用现有 permission、plan gate 和 bar 状态映射验证的草案。Risk 池采用独立的风险处理队列；bottom_div 采用“修复观察/待确认/已升级”等自己的状态映射，不套用机会池 ready 语义。精确状态映射在代码实现前必须由测试锁定。

### 3. 个股结构分

`structure_score` 目标范围为 0–100，只使用个股自身截至 `as_of` 的价格、成交量和多周期结构事实。拟拆成互不重复的分项：

| 分项 | 衡量内容 | 不应混入 |
| --- | --- | --- |
| `setup_quality` | 底分型/矩形/突破或回踩结构是否成立、关键价位是否清楚 | 行业热度、permission 组别 |
| `trigger_quality` | 最新 bar 是否有效触发、收盘位置/量价是否支持 | 同一触发事实的多个别名重复计分 |
| `confirmation_quality` | 与 setup 不同源的确认事实 | 再次计入 setup 本身 |
| `freshness` | 结构/触发距 `as_of` 的交易日数，过期结构衰减 | 仅因 80 根窗口内“仍存在”就保持满分 |

第一版先从当前 Facts 提取候选证据，逐项列出计算源、窗口和去重关系，再确定固定、版本化的映射。现有 `v2_scores` 只能作证据输入：双底、矩形、setup、trigger 和 execution-risk 当前有重叠，不能直接照搬其累计命中分。

尚不锁定各分项权重。权重必须在去重、固定特征范围和边界条件明确后，再用影子结果与时间前推样本评估。分数是规则刻度，不代表概率；避免每日 min-max 归一化导致相同结构仅因同池其他股票变化而改变绝对分。

### 4. 市场上下文

将全局市场 regime 和个股相对市场位置拆开：

- **全局 regime**：大盘强弱/宽度是共同环境，不作为给全池所有股票同加的常数；用于显示整体风险状态、调整参与限制或 ready 状态门槛。
- **候选相对上下文 `market_adjustment`**：只纳入股票之间有差异的行业相对强度/宽度等，作为结构分的有界修正。概念关系在来源和覆盖质量通过审计前只展示，不进 V1 主排序。
- **许可与风险**：MA60/MA250/周线等个股长周期条件属于该股自己的趋势/许可事实；若是确定性阻断，进入状态层级/plan gate，不同时作为市场加分扣分。

V1 输出 `market_adjustment` 分项和生效值。修正上限暂不预设数字：先量化现有行业上下文在全池分布中的影响，再选一个足以打破近似结构分并列、但不能改变状态层级的范围。全局环境即便改变，也不应让所有候选因同一常数而互换名次。

### 5. 风险与历史证据

- `risk_level`、`risk_breaks`、`risk_heat` 和 `plan_gate` 独立返回；确定性阻断改变 tier，不靠综合分扣到某个魔法数。
- 同一状态层级、近似总分时，可将剩余风险级别作为次级 tie-break；风险原因始终对用户可见。
- Replay、历史胜率、未来收益属于验证证据，不进入 V1 的实时结构分。显示统计时同时显示时间窗、entry model、样本量和覆盖日期。
- 对历史快照只能使用当时已物化的输入。没有当时市场上下文时返回 `snapshot_local`/结构排序，不能拿今天的数据补历史。

## 排序键

每个 pool 使用稳定、确定的排序键：

```text
pool 固定
→ eligibility_tier（ready > waiting > observe > blocked；按 pool 定义）
→ ranking_score = structure_score + bounded_market_adjustment
→ structure_score
→ lower residual risk
→ newer valid event_date
→ code ascending（最终稳定 tie-break）
```

blocked 项保留在池中供研究，但不能靠更大的连续分数越过 ready/waiting 层。底部观察和风险池定义自己的 tier 与排序主项，不能通过共用一套机会分数伪造语义一致。

## 读模型契约草案

### CandidateSummary

分页、筛选和排序所需的轻量字段建议包括：

```text
ranking_version
ranking_as_of
eligibility_tier
eligibility_reasons
structure_score
structure_score_components (compact)
market_adjustment
market_context_status
market_context_as_of
market_context_revision
ranking_score
risk_level
data_quality_status
```

`priority_score` 这类无来源的单值字段只可作为兼容投影，不得成为新公式的唯一事实。SQLite 排序字段和 JSON 回退读取必须引用同一版本的 rank contract。

### CandidateDetail

选中候选后按需读取完整的分项证据：来源 fact、观察日期、窗口、触发/确认理由、风险闸门、市场输入来源与缺失原因。Summary 不复制完整 facts 或完整行业统计。

每个 RankContext revision 需固定候选快照 revision、计算时间、as-of 市场数据 revision、公式版本和覆盖范围。JSON 扫描快照继续作为原始候选事实来源；SQLite 是索引与物化排序读模型。

## 验证门槛

### 代码不变量

1. 同一输入、同一版本得到相同 tier、分项与顺序。
2. 全局 regime 对全池一致时，不通过“统一加常数”改变候选之间的排序。
3. 计划/许可 blocked 不能因分数高越级。
4. 市场输入缺失与真实中性分数可区分；过期上下文不能伪装为当日值。
5. 同一 snapshot/as-of 在 JSON 与 SQLite 路径的成员、tier、排序和分页完全一致。
6. Top-K 调位可输出差异分解，至少区分结构变化、市场修正、tier 变化、tie-break。

### 研究验证

新旧算法先并行影子运行，不改变页面主序。历史与新增每日快照按时间前推评估，使用 next session open 作为参考入场，明确停牌、涨跌停、费用与缺失行情处理。报告 Top 10 的未来 5/10 日超额收益分布、最大不利波动、分组单调性和 rank correlation，并对不同市场 regime 分层观察。

只有当前候选池能够按历史时点还原时，历史结果才可解释为该时点全池排序；否则明确标注 coverage 限制。任何权重试验都记录尝试版本，不从同一历史窗口反复挑最优参数。

## 与当前项目的接线顺序

1. [已完成初稿] 以[特征覆盖与证据映射](candidate-ranking-feature-coverage-2026-09.md)定义无权重资格/证据投影；实现为 `build_candidate_ranking_features_v1`，边界测试通过，未接入生产排序。
2. 增加可复现的只读批量 shadow audit，接入 RankContext 时把数值、来源 as-of、revision 和 freshness 状态分开核验。
3. 观察不同 pool 的 tier 和证据组成；只有明确层内排序目标与证据覆盖后，才提出连续分数/权重方案。
4. 如需物化 shadow 字段，再扩展 SQLite `CandidateRankContext`，带 ranking version 与 as-of provenance，并验证 JSON/SQLite parity。
5. 累积足够的时间前推样本并通过验证后，再讨论候选页默认排序；legacy 排序在得到切换批准前保持不变。

本草案不批准数值权重、不改变生产排序、不切换 SQLite 默认读源，也不删除旧快照、候选池或上下文数据。
