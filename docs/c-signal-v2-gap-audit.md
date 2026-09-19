# C 信号 V2 当前差距审计

> 日期：2026-09-07  
> 状态：实现前审计，用于拆解 P1-P5  
> 上游依据：`docs/c-signal-v2-strategy-requirements.md`、`docs/c-signal-v2-design.md`  
> 边界：本文只审计差距和实现影响，不修改策略阈值。

## 1. 审计结论

当前 V2 已经完成三件重要基础工作：

```text
语义映射：旧 C 事件可以映射为 C研/C候/C修/C回/C突/C爆/C风
事实层：可以提取分型、矩形、攻击日、起爆点、威廉时钟等事实
展示层：单股图表可以在旧 C 与 V2 独立图面事件之间切换
```

但 V2 还没有真正成为策略主链。当前仍是：

```text
composite 决定是否入池
composite 决定 setup/confirm/risk
composite_entry 决定交易许可
V2 负责解释、排序和图面补充
```

目标应改为：

```text
V2 事实层
→ V2 状态机
→ V2 许可层
→ V2 交易计划 gate
→ V2 队列/图面
→ composite 仅作对照和兼容
```

核心差距：**当前系统已经有 V2 的外壳和部分事实，但决策权仍在旧 composite。**

## 2. 当前代码链路

### 2.1 单股分析链路

入口：

```text
stock_analyzer/analysis.py
```

当前顺序：

```text
normalize_price_frame
→ add_indicator_columns
→ add_signal_columns
→ add_composite_strategy_columns
→ serializer 输出图表和状态
```

其中：

- `add_indicator_columns()` 计算 MACD、KDJ、ADX、CCI、布林、Williams %R、多空力度、VWAP、背离；
- `add_signal_columns()` 生成旧 B、新 B、优化 B；
- `add_composite_strategy_columns()` 生成当前主策略字段；
- `analysis_frame_to_chart_payload()` 同时输出旧图面点和 V2 图面点。

问题：

- V2 事实层不是主链入口，而是后置解释；
- 收益风险比不在分析链路前置；
- 市场/板块许可没有参与单股状态生成；
- `composite_*` 字段仍是后续大部分判断的事实来源。

### 2.2 扫描候选链路

入口：

```text
stock_analyzer/scanner.py
```

当前 `opportunity` 只扫描：

```text
composite_pullback
composite_breakout
composite_confirm
```

当前 `risk` 只扫描：

```text
composite_warning
composite_stop_loss
composite_take_profit
composite_exit
composite_top_divergence
```

当前 `bottom_div` 只扫描：

```text
composite_bottom_divergence
```

问题：

- V2 的 `C研/C候/C爆/C风` 图面事实不决定入池；
- `C爆` 当前不会独立进入扫描候选；
- `C研/C候` 也没有独立观察池，只能通过旧 bottom_div 或旧候选回填展示；
- V2 优先级影响排序，但不影响“谁能进入名单”。

### 2.3 交易计划链路

入口：

```text
stock_analyzer/trade_plan.py
```

当前交易计划已经具备：

- 止损价；
- 止损距离；
- 2R/3R；
- 账户风险预算；
- 建议股数；
- C突高开、过热、MA20 偏离、量比异常提示。

问题：

- 交易计划在信号之后执行；
- 入池之前没有 plan gate；
- `target_price` 缺失时，收益风险比为 pending，不足以阻止候选入池；
- `C研/C候/C修` 与入场类信号的计划要求没有在扫描层硬隔离。

### 2.4 板块共振链路

入口：

```text
stock_analyzer/scan_overview.py
stock_analyzer/scan_resonance_scoring.py
stock_analyzer/market_structure.py
```

当前板块/概念主要从候选结果中统计：

```text
机会数量
修复观察数量
风险数量
平均 rank
最高 rank
市场广度
板块行情
关系质量
```

然后回写：

```text
sector_score
concept_score
final_score
market_context
```

问题：

- 板块共振仍偏加分项；
- 板块强弱没有作为 `C突/C爆` 升级许可；
- 个股相对板块强弱还没有进入状态机；
- 成交量仍会在单股 confirm 中加分，和“成交量只决定是否关注”的口径不一致。

## 3. 可复用资产

### 3.1 可直接复用

| 模块 | 可复用内容 | 用法 |
| --- | --- | --- |
| `analysis.py` | 标准化行情和指标计算入口 | 继续作为事实计算前置 |
| `indicators.py` | MACD、KDJ、ADX、布林、Williams %R、多空力度 | 作为事实，不直接给买卖结论 |
| `technical_structures.py` | 威廉时钟、右侧观察、风险语境 | 拆成 V2 状态机的 attention/context |
| `trade_plan.py` | 止损、仓位、2R/3R、执行约束 | 升级为入池前 plan gate |
| `events.py` | V2 图面事件模型 | 拆出事实视图与交易视图 |
| `serializers.py` | `mark_points_v2` 并行输出 | 继续兼容旧前端 |
| `scan_workspace_response.py` | 工作台排序响应层 | 可接入 V2 队列排序 |
| `scan_explainer.py` | 候选解释层 | 用于解释 V2 状态、许可和拦截原因 |

### 3.2 可复用但需降权

| 字段/模块 | 当前用途 | V2 用途 |
| --- | --- | --- |
| `setup_score` | 入场排序核心 | 仅兼容解释 |
| `confirm_score` | 入场排序核心 | 仅说明旧策略确认程度 |
| `risk_score` | 风险拦截和排序 | 可保留为风险事实之一 |
| `composite_pullback_setup` | 回踩准备 | 降为结构 evidence |
| `composite_breakout_setup` | 突破准备 | 降为结构 evidence |
| `volume_ok` | 确认分加分 | 改为 attention 或市场活跃证据 |
| `rank_score/final_score` | 默认候选排序 | 旧策略对照排序 |

### 3.3 不应继续作为主决策的内容

| 内容 | 原因 |
| --- | --- |
| `composite_entry` | 它由旧指标组合决定，不能继续代表 V2 可执行 |
| `composite_confirm` | 容易把修复观察误解成参与候选 |
| 单纯放量确认 | 成交量无法区分建仓和出货 |
| 单纯突破确认 | 未经过收益风险比和结构止损 |
| 统一总分买入排序 | 会绕过状态机和计划 gate |

## 4. 目标字段差距

### 4.1 当前已有字段

```text
v2_signal
v2_signal_name
v2_state
v2_state_label
v2_role
v2_role_label
trade_intent
requires_trade_plan
requires_stop_loss
v2_state_model
v2_priority_group
v2_priority_score
mark_points_v2
c_signal_v2_state
facts.trend/setup/risk/structure/trigger/v2_scores
```

### 4.2 仍需新增字段

```text
v2_queue
v2_queue_label
v2_permission
v2_permission_reasons
v2_block_reasons
v2_attention_score
v2_rr_score
v2_market_permission
v2_structure_id
v2_structure_type
v2_trigger_id
v2_trigger_type
v2_plan_status
v2_plan_required
v2_entry_price
v2_stop_price
v2_target_r2
v2_target_r3
v2_risk_reward_ratio
v2_relative_strength
v2_sector_permission
```

### 4.3 字段迁移原则

```text
旧字段继续输出，保障历史快照和前端兼容
新字段不覆盖旧字段，而是并行输出
默认 UI 读取 V2 字段，旧 C 视角读取旧字段
扫描快照必须记录策略版本和 V2 schema 版本
旧快照可轻量回填语义，但不能伪造缺失的 V2 事实
```

## 5. 关键缺口

### Gap 1：V2 状态机仍依赖 composite

现状：

```text
build_c_signal_v2_state()
→ 读取 composite_entry/composite_exit/composite_risk_score
→ 决定 permission
```

目标：

```text
build_c_signal_v2_state()
→ 读取 V2 facts
→ 读取收益风险比
→ 读取市场/板块许可
→ 读取 plan gate
→ 决定 permission
```

影响文件：

```text
stock_analyzer/c_signal_v2.py
stock_analyzer/c_signal_v2_facts.py
stock_analyzer/market_permission.py
stock_analyzer/trade_plan.py
tests/test_trade_plan.py
tests/test_project_smoke.py
```

风险：

- 若一次性替换，会影响扫描候选和单股状态；
- 应先新增 V2 state v2 schema，不删除旧 state。

### Gap 2：候选入池仍由 composite 决定

现状：

```text
scan_events_for_type()
→ build_composite_signal_events()
→ 只认 composite keys
```

目标：

```text
scan_events_for_type()
→ build_v2_scan_events()
→ 按 V2 queue 入池
```

影响文件：

```text
stock_analyzer/scanner.py
stock_analyzer/events.py
stock_analyzer/scan_snapshot.py
stock_analyzer/scan_workspace_response.py
tests/test_scan_jobs.py
tests/test_scan_workspace.py
```

迁移方式：

```text
第一步：新增 v2_scan 事件，不替换 composite
第二步：工作台返回 v2_queue
第三步：前端默认看 v2_queue，但保留旧池
第四步：样本验证通过后再决定是否让 V2 接管 opportunity
```

### Gap 3：收益风险比没有前置

现状：

```text
交易计划在 /api/analyze 或详情中后置计算
扫描候选不知道 plan 是否通过
```

目标：

```text
入场类 V2 事件生成后立即运行 plan gate
plan_status != ready 时不能进入可执行池
```

影响文件：

```text
stock_analyzer/trade_plan.py
stock_analyzer/scanner.py
stock_analyzer/scan_snapshot.py
stock_analyzer/scan_explainer.py
static/js/scanResultCard.js
static/js/scanSelectionDetail.js
```

风险：

- 目标价来源目前不稳定；
- 若没有目标价，不能简单 blocked 所有候选，否则系统可能没有可执行结果；
- 需要先定义默认目标空间估算：矩形上沿、近高、2R/3R 刻度，而不是主观目标价。

### Gap 4：C爆 是事实，不是可执行

现状：

```text
build_v2_signal_events()
→ attack_day 或 ignition 触发
→ 图面显示 C爆
```

目标：

```text
attack_fact / ignition_fact
→ attack_candidate
→ attack_allowed
→ C爆可执行
```

影响文件：

```text
stock_analyzer/c_signal_v2_facts.py
stock_analyzer/events.py
stock_analyzer/c_signal_v2.py
stock_analyzer/trade_plan.py
static/js/chartMarkers.js
static/js/scanStrategyCompare.js
```

验收：

- 图面事实视图可以显示攻击/起爆事实；
- 交易视图只显示通过 plan gate 的 `C爆`；
- 未通过许可的 `C爆` 文案必须是“触发事实”，不是“强买点”。

### Gap 5：板块共振仍是加分项

现状：

```text
sector_score/concept_score
→ final_score 加权
→ V2 priority 微调
```

目标：

```text
market_permission
sector_permission
concept_relation
relative_strength
→ 许可或降级
```

影响文件：

```text
stock_analyzer/scan_overview.py
stock_analyzer/scan_resonance_scoring.py
stock_analyzer/market_structure.py
stock_analyzer/scan_market_context.py
stock_analyzer/market_permission.py
```

验收：

- 板块强不直接制造买点；
- 板块弱可阻止 `C突/C爆` 升级；
- 个股弱于板块时降级；
- 解释层明确写成“环境许可”，不是“买入加分”。

### Gap 6：图面没有分事实视图与交易视图

现状：

```text
V2 视角显示 mark_points_v2
旧 C 视角显示 mark_points_composite
```

目标：

```text
V2事实视图：显示研究、候选、触发事实、风险事实
V2交易视图：只显示可执行入场、风险处理、失效点
旧C视图：保留原 composite 对照
```

影响文件：

```text
templates/index.html
static/js/chartMarkers.js
static/js/chartView.js
static/js/scanStrategyCompare.js
static/js/signalPanel.js
static/css/app.css
```

验收：

- 默认图面明显更少点；
- `C研/C候` 视觉弱于 `C回/C突/C爆`；
- `C爆` 必须显示 plan 状态；
- 用户能切换事实复盘和交易执行。

## 6. 实现分解

### P1：V2 独立状态机

目标：让 V2 permission 不再以 `composite_entry` 为主。

最小实现：

```text
新增 v2_state_schema_version
新增 build_v2_permission()
新增 permission reason/block reason
保留旧 build_c_signal_v2_state() 输出形状
```

文件：

```text
stock_analyzer/c_signal_v2.py
stock_analyzer/c_signal_v2_facts.py
stock_analyzer/market_permission.py
tests/test_trade_plan.py
tests/test_project_smoke.py
```

验收：

- 旧 C 有入场，但 V2 前置条件不满足时，V2 可显示 watch_only；
- V2 有结构但旧 C 没入场时，V2 可显示 structure_only；
- 风险事实出现时优先 risk_only；
- 所有旧 API 字段不破坏。

### P2：Plan Gate 前置

目标：所有入场类信号先过交易计划资格审查。

最小实现：

```text
新增 evaluate_v2_plan_gate()
输入：entry_type、entry_price、structure_stop、target_reference、context
输出：ready/waiting/blocked + reasons
```

文件：

```text
stock_analyzer/trade_plan.py
stock_analyzer/c_signal_v2.py
stock_analyzer/scanner.py
tests/test_trade_plan.py
tests/test_scan_jobs.py
```

验收：

- 无止损价 blocked；
- 止损距离过宽 blocked；
- 低于 2R blocked；
- 目标空间 pending 时最多 watch_only，不进可执行池。

### P3：V2 扫描事件和队列

目标：V2 能独立决定研究池、结构池、可执行池、风险池。

最小实现：

```text
build_v2_scan_events()
v2_queue = research / structure / executable / risk
scan_type 兼容旧池
候选结果新增 v2_entry_source
```

文件：

```text
stock_analyzer/events.py
stock_analyzer/scanner.py
stock_analyzer/scan_snapshot.py
stock_analyzer/scan_workspace_response.py
tests/test_scan_workspace.py
tests/test_scan_jobs.py
```

验收：

- `C研` 进入研究观察，不进入可执行；
- `C候/C修` 进入结构观察；
- 只有 plan ready 的 `C回/C突/C爆` 进入可执行；
- `C风` 进入风险处理。

### P4：板块许可

目标：把板块/市场从排序加分改成升级许可。

最小实现：

```text
market_permission = forbidden/watch/allowed
sector_permission = forbidden/watch/allowed
relative_strength = strong/neutral/weak
permission_context 写入 v2_state_model
```

文件：

```text
stock_analyzer/market_permission.py
stock_analyzer/scan_market_context.py
stock_analyzer/scan_resonance_scoring.py
stock_analyzer/market_structure.py
tests/test_market_breadth.py
tests/test_scan_workspace.py
```

验收：

- 弱板块可阻止 trigger 升级；
- 强板块不跳过个股结构；
- 解释文案体现“许可/降级”，不是“推荐买入”。

### P5：前端事实/交易双视图

目标：减少满屏点位和语义误解。

最小实现：

```text
V2 事实
V2 交易
旧 C
```

文件：

```text
templates/index.html
static/js/chartMarkers.js
static/js/chartView.js
static/js/scanStrategyCompare.js
static/js/signalPanel.js
static/css/app.css
```

验收：

- 默认打开为 V2 交易视图；
- 可切换到 V2 事实视图复盘；
- `C研/C候` 不显示成强买点；
- `C爆` 未 ready 时不能使用入场视觉。

## 7. 测试计划

### 单元测试

需要覆盖：

- V2 状态机状态迁移；
- `C爆事实` 与 `C爆可执行` 分离；
- plan gate 对止损、2R、目标空间的拦截；
- 风险优先覆盖机会；
- 旧快照回填不伪造 V2 facts。

### 回放测试

需要分桶：

```text
C回
C突
C爆事实
C爆可执行
C修
C研
C风
```

观察：

- 样本数；
- 5 日胜率；
- 5 日均值；
- 最差收益；
- 次日开盘口径；
- 高开、MA20 偏离、量比、过热分桶。

### UI 验证

需要检查：

- 单股页面三视图切换；
- 候选池 V2 queue；
- 移动端标签不重叠；
- 默认视图点位数量是否下降；
- 旧 C 对照是否仍能解释差异。

## 8. 风险和决策点

### 风险 1：V2 过严导致没有候选

处理：

- 先分池，不直接替换旧 opportunity；
- `research/structure` 保持可见；
- 可执行池宁缺毋滥。

### 风险 2：收益风险比目标价来源不稳

处理：

- 优先用结构上沿、矩形上沿、近高作为参考；
- 没有目标空间时 pending，不主观预测；
- pending 不进入可执行池。

### 风险 3：板块许可数据质量不稳定

处理：

- 数据缺失时不直接 forbidden，先标记 unlinked；
- 只有明确弱势或风险扩散才降级；
- 关系质量弱的概念不能强行加权。

### 风险 4：用户误读 `C爆`

处理：

- 立即拆文案：`C爆事实` 与 `C爆可执行`；
- 图面默认不把未 ready 的 `C爆` 画成强入场；
- 候选卡必须展示 plan 状态。

## 9. 建议下一步

下一步不要直接大改 `strategy.py`。建议先做 P1 的最小实现：

```text
新增 V2 独立 permission contract
保留旧 composite 兼容
让单股页面出现“旧 C 可交易但 V2 不允许”的真实差异
```

这一步完成后，再做 plan gate 前置。否则如果先改扫描池，很容易把旧 composite 的问题复制到 V2 里。
