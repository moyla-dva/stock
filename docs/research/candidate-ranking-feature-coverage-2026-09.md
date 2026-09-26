---
status: historical-baseline
strategy_version: "2026.09.20.1"
data_window: "2026-09-24 latest full-market snapshot; source audit run 2026-09-25"
universe: "latest indexed opportunity/risk/bottom_div candidates"
entry_model: "not applicable; feature coverage audit"
data_revision: "2026-09-24 scan snapshots; stock-structure-macro-only-v1 snapshot revision sha256:ca895153b42c273043b5334b23b89d4a78f6069bb88b75de500f96d89ee753cd and latest_fresh revision sha256:b5fece15d49cf7cb245894238674a8aa2ea173fd1ad706798c3287adfdf2c077 materialized 2026-09-25"
evidence_level: "single-date implementation and coverage audit; no return validation"
supersedes: []
---

# CandidateRanking V1 特征覆盖与证据映射

> **时间边界**：本文中的类别分数、市场 boost 与 RankContext revision 是 2026-09-25
> 决策前基线，不代表当前实现。2026-09-25 已采纳
> [ADR-0002](../adr/0002-candidate-ranking-ownership.md)：行业/概念仅用于描述、分布和筛选；
> 板块行情、宽度、类别共振与分桶回放不参与当前排序或许可。下面的单日 Facts 覆盖统计
> 仍可作为结构研究证据，但旧版排序和上下文结果仅供历史对照。

## 目的

在实现 V1 影子排序前，检查当前 Facts 在真实候选中的覆盖度、稀疏度、时效性，以及现有横截面市场分能否区分候选。本文只回答“这些字段现在是什么、覆盖怎样、怎样避免重复计分”，不证明其对未来收益有效，也不修改线上排序。

## 样本与复现边界

- 原始行情快照：`.cache/scan_snapshots/*_20260924.json`，共 5,569 份、1,878,551 根日线 bar、约 348.8 MB。
- 该日 SQLite CandidateSummary：5,134 条，包含 opportunity 3,641、risk 1,156、bottom_div 337。
- 本次在 2026-09-25 按 `stock-structure-macro-only-v1` 重物化后，完整 `snapshot` 覆盖 5,134 条（opportunity 3,641、risk 1,156、bottom_div 337）；`latest_fresh` 覆盖 5,131 条（opportunity 3,640、risk 1,154、bottom_div 337）。相对完整快照仅排除 3 条过期候选（opportunity 000016、risk 002731 和 301139）；两种 scope 的 overlay 均逐条完整。此前报告的 5,118 条计数属于旧 revision，不能用于描述当前覆盖。
- 5,569 份快照中，5,551 份的 `data_date` 为 2026-09-24，另 18 份使用更早数据。全部 `bar_state=closed`，说明 closed 只描述 bar 完成状态，不代表数据日期就是当前扫描日。
- 当日数据来源记录为 `tencent_direct` 3,597、`tencent_via_akshare` 1,937、`tencent_direct+tencent_realtime` 17。来源标签应随 CandidateSummary/RankContext 保留，不应在算法层归并成“实时/正常”而丢掉。
- 本地最新候选数据日为 2026-09-24；这份样本不是 2026-09-25 的全市场结果。该目录中可见的连续全量日快照只有 2026-09-18 至 2026-09-24 的若干日期，远不足以做样本外收益结论。

复现入口：

```sh
sqlite3 .cache/scan_index.sqlite3 \
  "select pool,count(*) from candidate_summaries where snapshot_day='20260924' group by pool;"

sqlite3 .cache/scan_index.sqlite3 \
  "select cs.pool,count(*) from candidate_summaries cs join candidate_rank_contexts rc on rc.candidate_id=cs.id where rc.context_revision='sha256:100790b76dd92c64c14ad20cf439275ad72918546033e153bdeeaa85ec8f4236' group by cs.pool;"

venv/bin/python scripts/audit_candidate_ranking_v1.py --snapshot-day 20260924
```

Facts 覆盖统计由当日快照 `results.<pool>.*.v2_state_model.facts` 只读汇总；交易日龄使用快照自身的 calendar revision，分型年龄从确认可见日 `analysis_date` 算到 as-of 最近交易日。

无权重特征投影器位于 `stock_analyzer/candidate_ranking_v1.py`，只读批量入口为 `scripts/audit_candidate_ranking_v1.py`，边界测试位于 `tests/test_candidate_ranking_v1.py`。以每份快照中的 calendar revision 从 `.cache/market_metadata.sqlite3` 读取交易日后，投影 2026-09-24 全部 5,134 个候选，得到：

| Pool | V1 shadow tier | 数量 |
| --- | --- | ---: |
| opportunity | `blocked` / `observe` / `waiting` / `ready` | 189 / 3,375 / 6 / 71 |
| risk | `risk_control` | 1,156 |
| bottom_div | `risk_control` / `repair_watch` / `research_watch` / `structure_watch` | 9 / 302 / 23 / 3 |

旧版审计曾把原始扫描快照中的 `v2_environment_permission` 当成工作台最终环境许可，因而将机会池 71 个上下文 `trade_ready` 候选错误列入 waiting，并声称 ready 为 0。旧 RankContext 没有保存精确环境许可；当时只能用 `trade_ready` 作保守推断。当前策略已改为重新计算每股宏观许可，以下旧组别统计仅用于还原该历史审计，不应用于当前决策。

旧版 RankContext 中 market boost 的来源与 as-of 无法从分数反推；这些旧证据仍应标 unknown，不能按新鲜输入使用。当前策略不再生成或物化类别行情上下文；兼容列可空并保留旧 revision 的审计能力。

## 2026-09-25 决策与新旧上下文对照

旧版正式库曾对 `20260924 / 2026.09.20.1 / 20250429 / latest_fresh` 物化 5,131 条上下文，revision 为 `sha256:c9bd772638dfc432a3e172e37ed66e011a486fad91316a9cccfe11792f6498c8`；完整 `snapshot` scope 还保留过 revision `sha256:d25072087c57e7a8d189b7aa0b7200d7fa47cd07fd0ae65396dae97288200510`。两者均已被新政策 supersede，当前查询不再应用旧 revision。

新政策下已分别重算完整快照和新鲜候选：`snapshot` revision 为 `sha256:ca895153b42c273043b5334b23b89d4a78f6069bb88b75de500f96d89ee753cd`（5,134 条），`latest_fresh` revision 为 `sha256:b5fece15d49cf7cb245894238674a8aa2ea173fd1ad706798c3287adfdf2c077`（5,131 条）。数据库检查确认两个新 revision 的 `sector_score`、`concept_score`、`market_boost` 均为 NULL，`market_context_json` 均为空对象。读端还会拒绝策略版本不匹配或含类别因子的覆盖，回退 `snapshot_local`。

`.cache/board_market` 中 24 个缓存文件最新时间仍在 2026-05-11 至 2026-05-13；产品决策是不恢复该缓存刷新，并已从页面治理入口与活跃数据源状态中移除。

决策前代码中另有候选池内生的行业/概念共振分。当前已一并从工作区计算、priority、环境许可、解释展示和新 RankContext 输入中移除；只保留行业/概念名字、候选数量与覆盖统计。

类别因素退役后，应以新 RankContext revision 重新计算 Top-K；旧版“重合 9/10、002204 被 605167 替换”的结果只描述之前单独屏蔽过期指数行情的中间版本，不是最终新政策对照。

复核命令：

```sh
venv/bin/python scripts/materialize_candidate_rank_context.py \
  --db .cache/scan_index.sqlite3 --snapshot-day 20260924 --scope latest_fresh --json
venv/bin/python scripts/audit_candidate_ranking_v1.py \
  --scan-db .cache/scan_index.sqlite3 --snapshot-day 20260924
curl 'http://127.0.0.1:5011/api/scan_index/candidates?scan_type=opportunity&rank_mode=contextual&limit=10'
```

## 观测结果

### Opportunity 池

| 事实 | 覆盖/分布 | 对排序设计的含义 |
| --- | ---: | --- |
| `v2_scores.structure_score` | 3,641/3,641 有值；均值 70.50，范围 35–100 | 当前机会候选几乎全有较高分；先检查分数构造与入池选择效应，不能把 70 分直接解释成“结构强”。 |
| `v2_scores.trigger_quality` | 均值 3.25，范围 0–95；大于 0 的 350 只（9.6%） | 触发质量稀疏，适合独立排序分项/状态，不应被结构分遮盖。 |
| `confirm_score` | 大于 0 的 202 只（5.5%） | 当前二值确认标记更稀疏；它不是连续确认质量，也不宜与 `trigger_quality` 直接相加。 |
| 最新确认底分型距 as-of | 交易日龄均值 7.00、最大 42；另按日历日均值 9.46 | 分型信号存在明显陈旧风险。以“80 根窗口内仍有最近底分型”给结构分，不能替代按交易日计算的 freshness。 |
| `structure.rectangle.available` | 3,413/3,641（93.7%） | 当前结构分的普遍高覆盖很可能主要由矩形命中贡献；矩形可用不等于临近突破或有新触发。 |
| `fractals.double_bottom_higher_low` | 1,337/3,641（36.7%） | 与“最近底分型”存在从属关系；若两者分别奖励，须验证是否重复计同一结构证据。 |
| `setup.pullback_setup` / `breakout_setup` | 1,459（40.1%）/250（6.9%） | 属于不同形态族，应先保留类别和依据，不能仅凭布尔项相加成命中数。 |
| 最新 bar 上 `attack_day` / `ignition.triggered` | 2（0.05%）/199（5.5%） | 真正当日触发远少于观察型结构候选；至少应把“结构成立”和“最新触发”拆成不同排序层。 |
| `breaks_prev_high` / `prior_breakout` | 881（24.2%）/52（1.4%） | 前者是触发事实，后者是历史 setup 痕迹；时间语义不同，不能同作“当前确认”。 |
| 非零 `risk_break_score` / `risk_heat_score` | 48（1.3%）/226（6.2%） | 结构破坏和短期过热是不同风险，应分别保留原因；总风险分和 execution-risk 派生分含重复项。 |
| 原始快照优先级组 | 3,641 只全部为 `structure_watch` | 这是扫描时的 snapshot-local 值，不代表工作台补入板块/概念上下文后的 RankContext 优先级。 |

进一步拆开 snapshot-local 字段后，机会池组合为：3,375 `structure_only`；189 `forbidden + plan blocked`；71 `pullback_allowed + plan ready`；4 `watch_only + plan waiting`；2 `watch_only` 且无 plan status。原始快照的环境权限全为 `unknown`，但这不是工作台最终值：旧 RankContext 记录的机会池有 71 `trade_ready`、3,561 `structure_watch`。由于旧表未保存逐候选环境权限，不能从 `structure_watch` 反推其具体是 watch、forbidden 还是 unknown。V1 必须分别读取单股许可/计划和物化后的环境上下文。

以上是字段命中率，不是标签的预测表现。尤其 `structure_score` 在入池后的范围有明显选择偏差；不能由这份分布断定它“过高”或应该下调权重。

### 横截面上下文

旧版 `latest_fresh` RankContext 的 opportunity 中：

- `sector_score >= 100` 为 3,399/3,632（93.6%），`concept_score >= 100` 为 3,586/3,632（98.7%）。两者几乎全顶格，横截面排序区分度很弱。
- `market_boost` 只有 1,486/3,632（40.9%）有值；其有值子集均值为 1.96，范围 1.4–3.4。旧表未保存组成 boost 的行业/概念来源与 as-of；NULL 不能解释成中性 0，必须附带 coverage/status。
- 该 RankContext 的工作区配置关闭了 `market_breadth`、`market_universe` 和 replay。因而不能把它称作完整市场环境校正。

结论：在分布、覆盖、数据时点和定义完成修订前，sector/concept resonance 不进入 V1 主排序；`market_boost` 仅作为有明确来源日期、覆盖状态的影子分项。全市场共同 regime 继续作为环境状态/许可，不加为所有股票相同的排序常数。

## V1 特征映射草案

| 排名维度 | 候选事实来源 | V1 处理边界 | 必须防止的问题 |
| --- | --- | --- | --- |
| 候选资格/状态 | V2 permission、`trade_plan.status`、bar/date validity、缺失确认 | 先生成 pool 专属的 `ready / waiting / observe / blocked`（名称及映射仍待测试）；许可/计划/data hard block 不能被连续分抵消 | 不把 `structure_watch` 数字优先级误当作可执行等级；风险池、bottom_div 各自定义状态 |
| 结构 setup | `facts.structure.fractals`、rectangle、`facts.setup.*` | 作为形态类别与 setup quality 输入；保留关键价位、质量、可用原因 | 底分型与抬高双底的父子关系；矩形与从同箱体推导的 setup 不能重复记分 |
| 当前触发 | `facts.trigger.*`、`facts.momentum.power_flip`、Williams 交叉、最新 bar 突破 | 只奖励截至 `as_of` 新鲜发生的触发；多个字段若描述同一 bar/同一价格突破，合成一个独立证据族 | 攻击日、起爆点、前高突破、动能翻转相关；累计封顶会抹掉强弱差异 |
| 独立确认 | setup 之后、不同来源或后续时点的确认事实 | 先明确因果顺序与确认定义，再产生独立分项；现有 `confirm_score` 暂不扩展解释 | 同一根 K 线的 setup+trigger 被重复叫作独立确认 |
| Freshness | `facts.latest_date`、分型 `analysis_date`、矩形 `end_date`、trigger 日期、行情 `data_date` | 分别算 setup age、trigger age、data age；按交易日而非日历日衰减，并保存 `as_of` | 以 80 根回看窗口代替新鲜度；停牌/节假日的日历天年龄误惩罚 |
| 风险与执行闸门 | `facts.risk` 的 break/heat、permission、Plan Gate | 独立返回风险等级、原因和阻断条件；作为资格层及同层 tie-break，不重复纳入结构分 | `execution_risk` 已重复组合总风险和 break/heat 子分；高分不能越过止损/许可约束 |
| 市场上下文 | 旧 RankContext 中行业指数、宽度和类别共振字段 | **当前排除**；仅该股票自己的宏观事实可影响许可。未来若重做市场研究，必须走独立实验和新的 ADR，不复活旧字段 | 历史类别分来自候选池内生计数且近乎顶格；行情来源/时点不完整 |
| 数据可信度 | `data_date`、`bar_state`、`data_source`、`data_revision`、交易日历证据 | 输出独立 `data_quality_status` 和缺失理由；过期行情不能伪装成中性 | 本样本 18 份 closed bar 的 `data_date` 已陈旧 |
| Replay/收益证据 | 固定快照后的未来行情、指定 entry model | 仅用于排序验证报告，不进入实时分数 | 以今日数据补历史输入、样本内调权、忽略停牌/涨跌停/缺数 |

## 事实去重与状态映射契约（V1 实现前）

以下是此前 shadow rank 的可测试草案，保留作研究史料；它不表示当前实现或已批准的连续打分方案。

### 原子证据与时间戳

| 原子证据族 | Canonical 输入 | 归并/计分规则 | 事实可知时间 |
| --- | --- | --- | --- |
| `pivot_structure` | `facts.structure.fractals.latest_bottom`、`double_bottom_higher_low` | 最近底分型是基础证据；抬高双底是同一 pivot 家族的强化形态，不把底分型与双底当两份独立事件累加。若没有可用最新底分型，双底标记不单独成立。 | 采用 `latest_bottom.analysis_date`，不采用 pivot 中心日期 `latest_bottom.date`；前者反映两侧确认完成、信息真正可见的日期。 |
| `active_range` | `facts.structure.active_rectangle` | 只读取活动短线/波段矩形一次，使用 `quality_score`、宽度、位置与触边信息；不对 `facts.structure.rectangle` 这个同一对象别名重复计分。`macro_rectangle` 是背景，不作为短线 setup 重复加分。 | 矩形是滚动窗口重算的当前状态；`end_date` 通常只是窗口最后一根 bar，不等于矩形形成日，不能直接当 setup 年龄。 |
| `setup_family` | `facts.setup.breakout_setup`、`pullback_setup`、`bear_trap_recovery` | 按形态族分类。突破准备依赖活动矩形/前高与当前价，回踩准备依赖 MA20、近期高点和矩形下沿；同一来源已计入 active range 时，不再把布尔 setup 当作独立固定奖励。破底翻恢复按独立形态标签保留。 | 当前状态由 `facts.latest_date` 上的价格重算；只在最新 bar 条件仍成立时视为 active。 |
| `entry_trigger` | `facts.trigger.attack_day`、`ignition.triggered`、`facts.setup.breakout_trigger`、`pullback_trigger`、`bear_trap_recovery.breakout_after_recovery` | 同一 bar、同一价位突破的别名归并为一个 entry event；攻击日与 ignition 同时出现时保留类型/强度，不相加成两次触发。回踩确认是不同 trigger family。`prior_breakout` 是持续状态，不等同于今日发生的新 trigger。 | 当前触发统一记为 `facts.latest_date`；历史延续型字段必须先新增真实首次触发日期，不能借用当前日期假装新鲜。 |
| `momentum_confirmation` | `facts.momentum.power_flip`、`williams_r_power_cross`、最新 Williams 多方交叉 | 作为一个相关动能证据族，不因多个 oscillator 字段同 bar 同向而重复累计。动能只确认价格结构，不独立创建入场许可。 | 各字段所依据的最新 bar 日期；缺少逐字段日期时只作为当前快照态，不声称是独立的后续确认。 |
| `volume_confirmation` | `facts.trigger.volume_expand`、`range_expansion` | 作为量价确认族；可解释触发质量，但不能把同一根扩量 bar 的多个量价 flag 当独立 setup。 | `facts.latest_date`。 |
| `risk_break` | `facts.risk.risk_break_score`、`break_reasons`、`exit_gate` | 以破位严重度/明确离场事实表达。矩形下破和近 N 日新低可能由同一次下跌共同触发；应按风险级别归并，不把计数机械映射成两次独立风险。 | 对应风险条件首次出现的 bar 日期；当前 Facts 未逐项输出日期时，shadow 先保存 as-of，不推断更早时间。 |
| `risk_heat` | `facts.risk.risk_heat_score`、`heat_reasons` | 热度内近 3 日涨幅与距 MA20 偏离当前取最大级别；保留原因，不再把总 `risk_score` 与 break/heat 子分重复扣分。 | 最新 bar 日期；heat 是当前状态，不等于可永久保留的事件。 |
| `market_relative_context` | 旧 RankContext 的行业相对强度或宽度 | 当前实现不消费、不入分、不影响许可；保留列只为旧 revision 读取。任何未来重做都须作为独立实验重新决策。 | 历史输入来源/日期不完整；不得从旧加分反推来源。 |

现有 `facts.scores.confirm` 的实际定义是 `trigger_observed`（攻击日、ignition 或破底翻突破等），不等同于“setup 之后的独立确认”；`v2_scores.trigger_quality` 又包含动能、Williams 和历史突破字段。V1 将这两个旧字段保留为兼容/解释字段，不把它们直接合并为一个 `confirmation_quality`。若要建真正的后续确认分，必须有可证明晚于 setup/trigger 的事实与时间戳。

### Freshness 与数据状态

所有年龄以快照的 `as_of` 为截止点、按相应历史交易日历的**交易日序号差**计算，并同时记录 calendar id/revision/evidence level：

- 行情新鲜度：用 snapshot `data_date` 对照 `as_of` 前最近应有交易日；`bar_state=closed` 不能代替日期新鲜度。有效但滞后的行情保留为 `stale`，不得进入 ready；日期/身份不明为 `unknown`，不得伪装成 0 日。
- 分型新鲜度：用确认可见日 `analysis_date` 计算；没有该日期时为 unknown，不使用 pivot 中心日回填。
- setup/trigger 新鲜度：当前重算的 setup 可标记为 as-of active；延续型历史事件要先提供真实 occurrence date。活动矩形滚动窗口的 `end_date` 不作为形成日。
- 若对应历史 calendar 不可恢复，则 freshness 为 unknown。不得用当前日历重算历史快照，也不得以日历天数替代交易日造成停牌/长假偏差。

当前项目快照有 `calendar_id`、`calendar_revision`、`calendar_evidence_level` 字段，但覆盖与历史可复现性仍需验证；实施时必须证明同一个 as-of 使用的是快照当时的日历修订。

### Pool 专属资格层级

资格层先于连续分数。以下规则是 V1 shadow 的初稿，按 pool 保留语义；不是把所有 pool 混到一个全局队列：

| Pool | 状态 | 条件优先级 |
| --- | --- | --- |
| `opportunity` | `ready` | 行情有效且当前；V2 permission 属于 `attack/breakout/pullback_allowed`；Plan Gate 为 `ready`；环境许可明确 `allowed`。四者必须同时成立。 |
| `opportunity` | `waiting` | 未被明确禁止，但 trigger/plan 仍 waiting，或环境 permission 为 `watch/unknown`；保留缺失/待确认原因。环境 unknown 不等于 allowed。 |
| `opportunity` | `observe` | `structure_only`、纯研究/修复观察，或无当前 trigger 的候选。结构质量分只在观察层内排序，不能越级。 |
| `opportunity` | `blocked` | 明确 permission forbidden、Plan Gate blocked，或行情身份/必需 OHLC 无效。可展示但不能因结构高分升层。 |
| `risk` | `risk_control` | permission `risk_only` 或 V2 role 为 risk；风险破位/退出紧迫度优先，同层再按风险新鲜度排序。 |
| `risk` | `observe` / `blocked` | watch-only 风险观察保留观察语义；无效行情 blocked。不得仅因进入 risk pool 就把观察事件冒充风险处置。 |
| `bottom_div` | `repair_watch` / `research_watch` / `structure_watch` | 依次保留修复、研究、普通结构观察的 V2 语义；risk_only 仍进独立 `risk_control` 子层。 |
| `bottom_div` | `entry_ready` / `waiting` / `blocked` | 若未来同一候选满足完整 permission + Plan Gate + 环境 + 数据条件，可显示升级状态，但仍留在 bottom_div 的独立池；waiting/blocked 按相同闸门原因标注。 |

`watch/unknown` 与显式 `forbidden/blocked` 必须区分：前者暂不具备 ready 证据，通常留在 waiting 或 observe；后者是明确阻断。对于 context/data unknown，shadow 需保留字段级 reason，不能静默落入某个看似正常的分数。

## 接下来的工程任务

1. **已完成**：以新政策版本重物化 2026-09-24 的 `snapshot` 与 `latest_fresh` RankContext；覆盖完整、旧因子列为空，旧策略 revision 由读端拒绝。
2. 用只读批量审计对其他快照日期复跑，记录成员、tier、原始特征和上下文覆盖；旧 RankContext 缺失的来源/时点必须保持 unknown，且未来时点标为 `future`。
3. 在不写生产分数的前提下，产出候选层级与证据组成报表；由真实 Top-K 调位问题反推是否需要连续分数，暂不挑权重。
4. 积累多周同版本且当时可见的快照/上下文后，才做时间前推收益验证；当前截面不足以选择权重或声称 Top-K 更好。

## 结论边界

此数据窗口支持的研究结论仍是：机会池内“结构候选”很宽，“近期触发”相对稀疏；分型、矩形、setup、trigger 与风险事实必须区分来源和时效。`candidate_ranking_v1.py` 仍是无权重资格/证据投影。行业/概念不再是当前排序或许可因子；旧 RankContext 的类别 provenance 不可追溯。尚无新的连续结构评分和多周样本外收益证据，因此新政策的排序变化只可做实现与可解释性核验，不可宣称预测能力提高。

与[因子重复计分审计](candidate-ranking-factor-audit-2026-09.md)和[CandidateRanking V1 设计草案](candidate-ranking-v1-design-2026-09.md)共同阅读。当前产品决策已由 ADR-0002 固化；本文其余 V1 特征映射仍是研究材料，不会自动恢复行业/概念排序或许可。
