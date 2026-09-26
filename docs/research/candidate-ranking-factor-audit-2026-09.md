---
status: historical-baseline
strategy_version: "2026.09.20.1"
data_window: "代码路径审计于 2026-09-25；引用 2026-09-24 最新全市场扫描，不是算法收益样本"
universe: "当前工作树中的 opportunity/risk/bottom_div 候选路径"
entry_model: "not applicable; candidate-ranking factor audit"
data_revision: "代码审计；线上排序质量尚未验证"
evidence_level: "代码路径与字段投影审计；无预测效力结论"
supersedes: []
---

# Candidate Ranking 因子字典与重复计分审计

> **历史基线说明（2026-09-25）**：本文描述的是 ADR-0002 采纳前的实现与问题，公式和
> “当前”字样均指当时被审计的旧工作树，不代表当前代码。现行决策是个股信号/结构与
> 个股宏观许可排序，行业/概念仅作描述；板块指数、宽度、类别共振及分桶回放已退出
> 当前链路。以 [ADR-0002](../adr/0002-candidate-ranking-ownership.md) 与代码为准。

## 2026-09-25 Decision Update

已完成的边界调整：工作区不再组装类别行情/宽度/共振分；旧类别分从读取结果中剔除，
历史 `final_score` 会被个股 `rank_score` 覆盖；priority 只按单股分数与个股状态/宏观许可
计算。SQLite RankContext 仍保留可空兼容列，但当前物化将这些分项置空。此更新并未创建
新的连续结构评分公式，也不代表预测效果已经验证。

## 目的与结论

本记录核对当前候选排序实际消费的字段、事实来源、数据时点与重复路径，为后续算法契约提供基线。它不批准更换生产排序，也不证明任何因子具有收益预测能力。

主要结论：

1. 当前 `v2_priority_score` 是状态/许可优先级、个股粗分、板块/概念共振、环境许可和可选回放收益的混合值，不是纯个股结构分。
2. 扫描排序实际使用的 `setup_score`、`confirm_score` 是 0/1 标记，`risk_score` 是 0–4。Facts 中另有 0–100 的 `v2_scores.structure_score` 与 `trigger_quality`，但扫描排序没有消费它们。
3. 结构/确认/风险以及板块/概念共振在最终分数中存在重复或间接重复计入。
4. SQLite 当前只投影综合优先级及有限上下文分项；不足以解释一个独立、可复现的“结构分 + 市场修正”。
5. 这次只审计和记录，没有修改代码、排序结果或生产读源。

## 当前计算链

### 1. 扫描事件粗分

`scanner.rank_scan_event` 按候选池使用不同公式。opportunity 为：

```text
rank_score = setup*3 + confirm*4 - risk*3 + event_weight
             + win_rate*0.06 + avg_ret
```

但当前 V2 扫描调用显式传入空 `signal_stats`，并跳过逐根历史事件回放，因此新扫描的 `win_rate` 与 `avg_ret` 在这一步为缺失/零影响。Risk 与 bottom_div 使用各自不同的公式。旧快照仍可能保存非空历史统计，不能不区分策略版本直接混比。

来源：[scanner.py](../../stock_analyzer/scanner.py)、[signal_registry.py](../../stock_analyzer/signal_registry.py)

### 2. V2 优先级分

`build_c_signal_v2_priority` 先依据 permission/state 映射到 `trade_ready`、`repair_watch`、`research_watch`、`structure_watch`、`risk_control` 或 `blocked`，再把组别基础值写入同一个数值分。Opportunity 的组别基础值包括 520、500、360、210、180、60、0；Risk 和 bottom_div 各有另一套组别分值。

Opportunity 在基础分之外继续累加：

```text
0.72 * final_score
+ 0.18 * max(sector_score, concept_score)
+ 0.06 * min(sector_score, concept_score)
+ 7 * confirm_score
+ 3 * setup_score
- 12 * risk_score
+ replay_adjustment       # 有回放样本时，限制在 [-8, +8]
+ environment_adjustment  # allowed +30, unknown -30, watch -60, forbidden -140
```

Risk 池对风险分采用加分方向，bottom_div 也使用其专属组别基数。JSON 工作区按 `v2_priority_score` 等字段排序；SQLite contextual 使用物化覆盖层中的相同字段，缺覆盖层时回退 `priority_score`，但二者的输入范围和历史 replay 行为并不总相同。

来源：[c_signal_v2.py](../../stock_analyzer/c_signal_v2.py)、[scan_workspace_response.py](../../stock_analyzer/scan_workspace_response.py)、[scan_index_store.py](../../stock_analyzer/scan_index_store.py)

### 3. 行业/概念与行情上下文

行业/概念 resonance 分不是独立的行情强度：它从 opportunity/bottom_div 数量、候选 `rank_score` 均值/最大值、bottom_div 数量和 risk 数量构造。当前行业公式为 `8*signal_count + 0.35*avg_rank + 0.15*max_rank + 2*bottom_div_count - 5*risk_count`；概念公式为 `6*signal_count + 0.32*avg_rank + 0.12*max_rank + 1.5*bottom_div_count - 4*risk_count`，结果均截到 0–100。概念和行业之后分别影响 `final_score`。

Board market boost 当前为 `clip((strength-50)*0.10 + ret_5*0.28 + ret_20*0.06, -8, +10)`；行业和概念分别乘 0.85、0.45 后进入 `final_score`。

机会许可还会读取行业/概念共振、市场指数强度、宽度和风险/机会数量，可能改变候选的优先级组，并额外对总分加减分。因此市场信息既作为连续分值进入排序，也作为许可/环境判断影响状态层级。

需区分两种名为 `structure_score` 的字段：

- `facts.v2_scores.structure_score`：单只股票自己的结构事实分，0–100；目前未接入主排序。
- `market_structure` 中的 `stat.structure_score`：行业/概念概览分，由市场指数、宽度、候选 resonance 和关系质量合成；不是单股结构分。

当时来源包括 [scan_overview.py](../../stock_analyzer/scan_overview.py)、
[market_permission.py](../../stock_analyzer/market_permission.py) 以及现已删除的
`stock_analyzer/scan_resonance_scoring.py`、`stock_analyzer/scan_market_context.py` 和
`stock_analyzer/market_structure.py`。后三者仅作历史实现路径记录，不再提供可点击的当前代码链接。

## 因子字典

| 当前输入/字段 | 语义与量纲 | 排序中的使用 | 审计结论 |
| --- | --- | --- | --- |
| `permission/state` → priority group | 离散许可与观察状态 | 转成大数值组别基础分；宏观/环境条件还可降级 | 本质是状态层级，应与连续质量分分开，避免靠魔法数模拟分层 |
| `setup_score` | 由 `facts.scores.setup` 投影；当前为 0/1 | `rank_score` 与 V2 priority 都使用 | 只是是否有结构候选，不是连续结构质量 |
| `confirm_score` | 由 `facts.scores.confirm` 投影；当前为 0/1 | `rank_score` 与 V2 priority 都使用 | 只是是否观察到触发，不代表确认强度 |
| `risk_score` | Facts 风险分，0–4 | opportunity/bottom_div 扣分，risk 池加分；V2 priority 再次使用 | 相同风险信号重复影响综合分；应优先作为独立风险状态/闸门 |
| `EVENT_WEIGHTS[event]` | 按事件 key 配置的离散先验 | 进入 `rank_score`，之后经 `final_score*0.72` 传入 V2 分 | 保留事件类别信息；要检查与状态组基础分是否在表达相同优先级 |
| `v2_state_model.facts.v2_scores.structure_score` | 单股结构事实，0–100 | 当前未进入 scanner rank 或 CandidateSummary | 可作为新结构分候选输入，但需先检查组成项、稳定性与缺失行为 |
| `v2_state_model.facts.v2_scores.trigger_quality` | 单股触发事实，0–100 | 当前未进入主排序 | 与当前二值 `confirm_score` 含义接近但粒度不同；不能两者并加 |
| `v2_state_model.facts.v2_scores.research_score` | 单股研究/观察事实，0–100 | 当前未进入主排序 | 更像观察队列的描述，不宜未经验证当作可交易强度 |
| `v2_state_model.facts.v2_scores.execution_risk` | 风险事实派生，0–100 | 当前主排序不直接使用 | 与 `risk_score`、risk break/heat 有组成重叠，不能直接再加一个风险扣分 |
| `sector_score` / `concept_score` | 候选池横截面的 signal 数量、候选 rank 均值/最大值及风险计数 | 改 `final_score`，又直接进入 V2 priority | 不是纯市场外生因子；含候选自身分数与候选数量，存在内生性及重复加权 |
| `market_boost` | 行业/概念指数强度与收益形成的有界加成 | 进入 `final_score`，再乘 0.72 进入 V2 priority | 应保留为上下文，但需和广义环境许可区分；明确指数日期、覆盖和陈旧状态 |
| `v2_environment_permission` | MA60/MA250/周线及行业/概念环境判断 | 可改变优先级组，并再加减 30–140 等分 | 是许可/环境约束，不应与市场连续分混成一条轴 |
| `score_confidence.replay_5d_avg_ret` | 共振桶历史 5 日回放统计 | 有任意正样本数时可对 priority 加最多 ±8 | 当前加成不随样本量收缩；小样本也可能得到满幅影响，适合先只展示 |
| `data/bar/profile quality` | 数据新鲜度、来源、覆盖或映射质量 | 主排序未系统纳入；read model 有部分标签字段 | 应作为置信度/可用性单独展示，不应把缺失默认为利空或零质量 |

Facts 具体生成位置：[c_signal_v2_facts.py](../../stock_analyzer/c_signal_v2_facts.py)；状态模型对外投影位置：[c_signal_v2.py](../../stock_analyzer/c_signal_v2.py)。

### Facts 内部 0–100 分的组成与重叠

现有丰富分是累计命中分后截到 100，并非由独立样本校准出的概率或质量等级：

- `structure_score`：最近确认底分型 +25、双底抬高 +35、矩形可用 +30、突破/回踩 setup +10。双底抬高必然使用最近底分型中的两个底，因此前两项可能重复奖励同一组结构证据；矩形与由矩形/前高派生的 setup 也可能重叠。
- `trigger_quality`：严格攻击日 +30、归一化动能翻转 +20、Williams 强力穿越 +15、起爆点 +30、当日 Williams 多方穿越 +15、前高突破 +15。攻击日与起爆点可在同一根 K 线上同时触发；动能翻转与 Williams 条件也可能相关，前高突破与 setup/trigger 共用价格事实。多个命中叠加后再封顶，存在相关特征重复加分和高分封顶丢失区分度。
- `research_score`：时钟状态、近期背离、阴包阳创新低和 setup 线索累计；其中 setup、背离与结构/触发分重复，语义更接近研究观察强度，不应并入可执行结构质量。
- `execution_risk`：当前为 `risk_score*18 + risk_break_score*8 + risk_heat_score*6` 后封顶；而 `risk_score` 本身就是 break 与 heat 子分相加后的 0–4 合成值，因此总分再次包含了两个子分，风险重复计入。

时效性也不一致：攻击/动能/setup 多数检查最新 bar；分型从最近 80 根结构窗口内找最近最多三个确认分型，确认本身有两根右侧 bar 的延迟，但 `structure_score` 命中最近底分型后没有按其距当前 bar 的年龄衰减。进入新连续评分前，应先明确“最近”在候选排序里允许多旧，并对过期结构降权或不计分。

## 已确认的重复路径与接线缺口

### 重复计分

对当前新 opportunity 扫描，在无 market/context 修正且 `signal_stats={}` 时，`rank_score` 已含 setup、confirm、risk；V2 priority 又在 `0.72 * final_score` 之外单独加入 setup、confirm、risk。按当前系数，单个二值 setup 的直接贡献约为 5.16，confirm 约为 9.88，risk 每增加 1 点约扣 14.16（不计组别变化和上下文）。这些数字是公式影响路径，不表示统计重要性。

行业/概念 resonance 从 `rank_score` 汇总，进入 `final_score` 后又直接作为 `sector_score` / `concept_score` 项加入 priority；它会间接重复反映候选信号强度。环境许可又基于相关共振/市场字段产生组别和分值变化。

### 丰富事实分尚未接入

Facts 已生成 0–100 的单股结构、触发、研究和 execution-risk 分，但 `latest_scan_score_summary` 消费的是 `facts.scores` 里的 0/1 setup/confirm 与 0–4 risk。SQLite `CandidateSummary` 当前投影综合 priority、final、confirm、risk 等字段，没有独立存储这些丰富分项。因此这不是权重微调问题，而是读模型当前没有新算法需要的稳定分项契约。

### 回放与读源范围

当前实时工作台因前向收益不可得而不做 replay；历史工作区可做 replay 并把 5 日均值加到 priority。排名上下文物化器明确以 `include_replay=False` 构建，并关闭 market universe/breadth 富化。因此历史 JSON 动态排序、快照本地分和 SQLite contextual overlay 必须分别记录其输入范围，不能统称为同一“当前综合分”。

### CandidateSummary 置信度投影

`score_confidence` 及其 label 是工作区富化阶段生成的 replay 置信度摘要，而 `CandidateSummary.from_snapshot` 读取的是持久快照字段；新扫描快照通常不会持久化这个工作区富化对象，因此摘要里的置信度字段通常为空。若某份快照确实存入对象，当前数值转换也会拒绝将对象转为 float。与此同时字段名 `profile_quality_*` 与实际 replay 置信度语义不一致。它不参与当前排序，但新算法若要展示数据/模型置信度，应另建明确字段和契约，不应沿用这个映射。

来源：[candidate_read_model.py](../../stock_analyzer/candidate_read_model.py)、[scan_rank_context_materializer.py](../../stock_analyzer/scan_rank_context_materializer.py)、[scan_confidence.py](../../stock_analyzer/scan_confidence.py)

## 算法契约建议

当前阶段建议仅采纳以下边界，不在本审计中锁定具体权重：

1. **先状态分层，再层内排序**：可执行/等待确认/观察/风险处理是离散语义，不能只编码成相差数百的浮点分数。
2. **单股结构分只由单股、当时可见的价格结构事实生成**；现有二值 setup/confirm 不足以直接充当连续质量分。`v2_scores` 只能作为候选证据源，需先去重、处理信号年龄和封顶，再定义稳定的连续特征。
3. **大盘 regime 不作为给全体候选同加的常数**；它不会改变横截面顺序。用它做环境状态/参与约束。层内市场修正只用候选之间有差异的相对行业/宽度信息，并设边界。
4. **风险、数据质量、样本置信度分栏呈现**。计划/许可闸门不能由高分抵消；概念关系低质量时只解释，不进主分。
5. **回放统计先退出主排序，作为独立证据展示**，直到明确样本量收缩、时间窗口、数据版本和样本外验证方式。
6. 每条排名保存 `score_version`、`as_of`、输入分项、市场上下文日期/修订、缺失原因；历史日期只用当时保存的输入。

## 后续工作顺序

1. 产品层确认队列名称和可执行/观察的排序优先级；算法层确认“结构质量”的业务定义。
2. 把 Facts 的 0–100 分降为“可用证据”，先处理上文列出的重复命中、过期分型和封顶饱和；不先引入新特征。
3. 定义可复现的 `CandidateRankingV1`：离散状态层级、去重后的单股结构分、候选相对市场修正、风险/数据置信度和确定性 tie-break。
4. 扩展 CandidateSummary/RankContext 的 SQLite 与 API 字段；同时保留 JSON 快照作为事实源，并确保两种读源使用同一版本。
5. 影子运行新旧排序，解释 Top-K 调位原因；用按时间前推的样本评估 5/10 日结果。现有单日读链 parity 只能证明实现一致，不能证明排序有效。
6. 通过后再更新页面分项解释并切换默认；旧排序只作为有限回退期保留。

## 限制

- 本文是静态代码路径审计，不是策略回测，也未重新扫描全部历史数据。
- 2026-09-24 的 latest 全市场 JSON/SQLite 全序一致记录见[真实扫描验收](scan-real-market-validation-2026-09-24.md)，只证明该样本下两条读链实现对齐。
- 当前工作区已有大量未提交更改；审计按磁盘上的当前代码读取，没有回滚或改写现有代码。
