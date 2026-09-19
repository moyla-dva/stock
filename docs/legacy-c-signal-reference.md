# 旧 C 信号逻辑备用参考

> 更新日期：2026-09-12  
> 状态：历史逻辑备忘，不是当前执行策略  
> 边界：当前项目以 C 信号 V2 为唯一主链。本文只记录旧 C 时代的信号意图、可借鉴经验和融合方式，不能作为恢复 `composite_*` 主链的依据。

## 一、当前使用规则

旧 C 已从当前执行链路中下线：

- `stock_analyzer/strategy.py` 已删除；
- `analysis.prepare_analysis_frame()` 不再生产 `composite_*` 策略列；
- 当前扫描入池由 V2 当前状态决定；
- 当前图面主标记使用 `mark_points_v2`；
- 旧 C/V2 临时切换已下线。

旧 C 只能作为三类素材使用：

- 策略经验：旧逻辑曾经试图捕捉什么结构；
- 样本假设：旧逻辑命中过但 V2 拦截的样本是否存在误杀；
- 规则素材：其中合理部分能否翻译成 V2 facts、permission、Plan Gate 或 Exit Gate。

任何旧逻辑如果要重新进入系统，必须先完成这条翻译链：

```text
旧经验假设
→ V2 facts
→ V2 state
→ permission
→ Plan Gate / Exit Gate
→ 回测或消融验证
→ 再决定是否进入主链
```

## 二、旧 C 信号意图

| 旧信号 | 旧字段/事件 | 原始意图 | V2 中的可用位置 |
|---|---|---|---|
| `C底` | `composite_bottom_divergence` / `bottom_divergence` | MACD 底背离，提示底部观察 | `C研`，只能作为研究观察 |
| `C观` | `composite_confirm` | 底部或弱势后的修复确认 | 可拆成 `C修` 或 `C候`，不能直接入场 |
| `C回` | `composite_pullback` | 趋势未坏时缩量回踩参与 | 可作为 V2 `pullback_setup/pullback_trigger` 的假设来源 |
| `C突` | `composite_breakout` | 价格突破近高或结构上沿 | 可作为 V2 `breakout_setup/breakout_trigger` 的假设来源 |
| `C顶` | `composite_top_divergence` | 顶背离或顶部风险提示 | 进入 V2 risk facts，不直接等同卖出 |
| `C止` | `composite_stop_loss` | 跌破止损或趋势破坏 | 进入 Exit Gate 的 sell 候选 |
| `C盈` | `composite_take_profit` | 有收益后的止盈保护 | 进入 Exit Gate 的 scale_out / profit_protection |
| `C风` | `composite_warning` / `composite_exit` | 风险预警或离场 | 进入 V2 risk_control / exit_gate |

旧 B、新 B、优化 B 也只作为 evidence：它们可以帮助解释“曾经何处有买点痕迹”，但不能直接生成 V2 入场许可。

## 三、旧 C 的主要问题

旧 C 最大的问题不是没有价值，而是职责混在一起：

- 分数容易被误解为交易许可；
- 底背离、修复、突破、风控在图面上权重接近；
- `C观` 容易被当作参与候选，而它本质只是修复观察；
- `C突` 容易在高位突破或 MA250 下方诱多时仍给出强买暗示；
- 旧目标价、止损价、仓位和收益风险比没有形成统一闸门；
- 风险信号没有被清晰拆成观察、减仓、卖出。

这些问题解释了为什么旧 C 不能作为当前主链恢复。

## 四、可以吸收进 V2 的经验

`C底` 的价值：

- 可以保留“左侧开始值得研究”的早期提醒；
- 只能进入 `C研`；
- 后续必须等待结构、触发和计划门。

`C观` 的价值：

- 可以拆成底背离后的修复状态；
- 当前对应 `C修`；
- 合理增强方向是细分修复质量，例如 MACD 柱改善、低点抬高、量能恢复、MA20 重新走平。

`C回` 的价值：

- 旧逻辑里相对更稳的是回踩参与；
- V2 可以吸收“缩量回踩、MA20 附近、风险较低”的经验；
- 但必须保留 MA60、结构止损、目标价和 2R。

`C突` 的价值：

- 旧逻辑能捕捉右侧突破，但容易追高；
- V2 可以吸收突破位识别、前高突破和矩形上沿突破；
- 必须由 MA250、周线 MACD、追高距离、过热、上方阻力和 Plan Gate 拦截。

`C盈/C风` 的价值：

- 旧逻辑提示风险和收益保护方向是有用的；
- V2 应继续把它们拆成 `observe / scale_out / sell`；
- 真正 S 点只由 Exit Gate 生成。

## 五、后续融合原则

后续不是把旧指标叠回去，而是逐条问：

```text
这个旧信号到底回答了哪个问题？
它是事实、状态、许可、计划，还是风控？
它是否可证伪？
它是否存在未来函数或追高偏差？
它能否用 V2 facts 表达？
```

只有能回答清楚这些问题的旧经验，才值得进入 P21 融合实验。

优先融合顺序：

1. `C回` 旧经验中的低风险回踩条件；
2. `C观` 中能提高 `C修` 质量的右侧修复条件；
3. `C突` 中对突破位识别有帮助、但不会绕过 Plan Gate 的条件；
4. `C盈/C风` 中可用于 Exit Gate 分级的收益保护与离场经验；
5. 旧 B 点只作为辅助证据，暂不进入主链。

## 六、P21 第一阶段落地

P21 第一阶段只做“事实层吸收”，不做许可放行。

已落地字段：

- `facts.legacy_experience.source = legacy_experience_p21`；
- `facts.legacy_experience.grants_permission = false`；
- `legacy_low_risk_pullback`：旧 B/优化 B 回踩命中，作为 `C回` 质量研究素材；
- `legacy_bottom_repair_hint`：旧底背离或 B 点痕迹命中，作为 `C研/C修/C候` 解释素材；
- `legacy_risk_hint`：旧 S/风险提示命中，作为 Exit Gate 分级研究素材。

显示规则：

- 工作台事实层可以显示“旧C...素材”；
- 该素材不改变扫描入池、V2 state、环境许可、Plan Gate 或 Exit Gate；
- 后续若要升级为 gate 规则，必须补充样本消融和验收测试。

## 七、P21-B 第一轮消融结论

样本窗口：`2026-09-11 -> 2026-09-14`。

结论：

- 旧 C 素材整体命中 `5473/5499`，几乎覆盖全市场，不能作为入场区分器；
- `legacy_low_risk_pullback`：233 个样本，平均收益 `+0.007%`，胜率 `44.64%`，弱于全市场；
- `legacy_bottom_repair_hint`：2706 个样本，平均收益 `+0.343%`，胜率 `51.96%`，弱于全市场；
- `legacy_risk_hint`：5338 个样本，平均收益和全市场接近，口径过宽；
- 当前不能把旧 C 素材恢复为入场加分或独立过滤；
- 后续仅保留三类用途：解释、样本分组、Exit Gate 提前性研究。

报告文件：

```text
docs/c-signal-v2-legacy-experience-ablation.md
```

## 八、P21-C 滚动消融结论

滚动窗口：

- `2026-09-09 -> 2026-09-10`
- `2026-09-10 -> 2026-09-11`
- `2026-09-11 -> 2026-09-14`

结论：

- 旧 C 素材整体 `14477` 个样本，加权平均收益 `-0.907%`，略好于全市场 `-0.979%`，但覆盖过宽；
- `legacy_low_risk_pullback` 滚动胜率 `25.42%`，不支持恢复为 `C回` 加分；
- `legacy_bottom_repair_hint` 只能作为修复解释和样本分组；
- `legacy_risk_hint` 命中过宽，不能做独立过滤器；
- V2 子状态 `strong_repair_watch / weak_repair_candidate` 相对抗跌，但滚动收益仍为负，不能升级为买点；
- 后续重点改为验证“次日确认价是否触发”，而不是继续叠加旧 C 字段。

报告文件：

```text
docs/c-signal-v2-legacy-experience-rollup.md
```
