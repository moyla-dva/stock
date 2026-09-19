# C 信号 V2 市场重刷复核报告

> 更新日期：2026-09-14  
> 当前数据口径：2026-09-14 收盘后本地快照  
> 当前策略版本：`2026.09.09.2`  
> 使用边界：本文替代 2026-09-11 复核稿，作为后续 P25 候选子状态、双视角图面语义和 P21 旧经验吸收实验的当前依据。

## 1. 数据可用性

本轮已经完成 2026-09-14 收盘数据追加与当前策略快照重建。

| 指标 | 数量 |
|---|---:|
| 2026-09-14 历史缓存 | 5499 |
| 2026-09-14 当前策略快照 | 5499 |
| 旧策略活跃快照 | 0 |
| 快照起始日期 | 2025-04-29 |
| 最新快照日 | 2026-09-14 |
| 最新行情日 | 2026-09-14 |
| 全市场离线重建耗时 | 215.369 秒 |

仍未完成 2026-09-14 数据追加的代码有 26 个：

```text
000004, 000016, 000638, 002731, 002808, 002870, 002898, 300029,
301139, 301390, 600193, 600301, 600421, 600599, 600608, 600636,
600696, 600825, 601238, 603159, 605081, 605303, 688287, 688291,
688496, 920305
```

结论：

- 2026-09-14 当前策略快照可以作为后续分析主口径；
- 旧策略活跃快照已经清零，V2 是唯一主链；
- 上述 26 个代码需要单独补数或确认停牌、退市、接口不可得等原因，不应混入当前主样本结论。

## 2. 当前工作台三池

| 池子 | 数量 | 主信号 | 主队列 |
|---|---:|---|---|
| opportunity | 2389 | `C候 2389` | `structure_watch 2389` |
| risk | 1417 | `C风 881 / C盈 536` | `risk_control 1417` |
| bottom_div | 650 | `C修 636 / C研 14` | `repair_watch 636` |

注意：池子数量是命中结果数，不等于可交易股票数。同一只股票可能不入池，也可能在不同池子出现不同语义。

## 3. Opportunity 池

当前 opportunity 池仍全部是 `C候`，没有直接可执行 `C回 / C突 / C爆`。

| 维度 | 主要分布 |
|---|---|
| V2 信号 | `C候 2389` |
| 状态 | `structure_candidate 1471`、`pullback_setup 615`、`trigger_plan_blocked 258`、`breakout_setup 31`、`trigger_plan_waiting 9`、`trigger_observed 5` |
| 许可 | `structure_only 2117`、`forbidden 258`、`watch_only 14` |
| 队列 | `structure_watch 2389` |
| Plan Gate | `blocked 258`、`waiting 9`、其余无 Plan |

P25-A/P25-B 候选子状态回填后：

| 子状态 | 短标 | 数量 |
|---|---|---:|
| `weak_repair_candidate` | `候?` | 937 |
| `structure_candidate` | `候` | 659 |
| `pullback_setup` | `候` | 491 |
| `reversal_confirmed` | `触` | 272 |
| `strong_repair_watch` | `待触` | 30 |

样本：

```text
688811 有研复材：C候 / structure_candidate / structure_only / structure_watch
688503 聚和材料：C候 / structure_candidate / structure_only / structure_watch
603667 五洲新春：C候 / structure_candidate / structure_only / structure_watch
301683 慧谷新材：C候 / structure_candidate / structure_only / structure_watch
301002 崧盛股份：C候 / structure_candidate / structure_only / structure_watch
```

结论：当前 opportunity 更准确的名字应是“结构观察/候选观察”，不是买入名单。P25-A/P25-B 已经先拆出候选子状态，下一步应把 `待触` 与 `触` 的确认价、失效价和空仓/持仓展示说清楚，再讨论是否放宽入场门槛。

## 4. Risk 池

| 维度 | 主要分布 |
|---|---|
| V2 信号 | `C风 881`、`C盈 536` |
| 状态 | `exit_gate_sell 881`、`scale_out_suggested 536` |
| 许可 | `risk_only 1417` |
| 队列 | `risk_control 1417` |
| Exit Action | `sell 881`、`scale_out 536` |

样本：

```text
688655 迅捷兴：C盈 / scale_out_suggested / risk_only / risk_control
300852 四会富仕：C盈 / scale_out_suggested / risk_only / risk_control
600127 金健米业：C盈 / scale_out_suggested / risk_only / risk_control
920045 蘅东光：C盈 / scale_out_suggested / risk_only / risk_control
603421 鼎信通讯：C盈 / scale_out_suggested / risk_only / risk_control
```

结论：风险池已经由 Exit Gate 接管，但图面展示仍要区分用户是否持仓。空仓视角不应把 `sell / scale_out` 直接翻译成 `卖 / 减`。

## 5. Bottom Div / C修 池

| 维度 | 主要分布 |
|---|---|
| V2 信号 | `C修 636`、`C研 14` |
| 状态 | `repair_setup 636`、`research_bottom 8`、`exit_gate_sell 4`、`structure_candidate 1`、`idle 1` |
| 许可 | `watch_only 644`、`risk_only 4`、`structure_only 1`、`forbidden 1` |
| 队列 | `repair_watch 636`、`research_watch 8`、`risk_control 4`、`structure_watch 1`、`blocked 1` |

样本：

```text
688592 司南导航：C修 / repair_setup / watch_only / repair_watch
688323 瑞华泰：C修 / repair_setup / watch_only / repair_watch
605358 立昂微：C修 / repair_setup / watch_only / repair_watch
600549 厦门钨业：C修 / repair_setup / watch_only / repair_watch
300014 亿纬锂能：C修 / repair_setup / watch_only / repair_watch
```

结论：`C修` 是 V2 原生修复观察，不是旧 C 信号恢复；它不能直接生成入场计划，也不需要止损价。

## 6. 2026-09-11 至 2026-09-14 复盘结论

上周五 2026-09-11 按严格 V2 口径没有 `trade_ready / plan_ready` 买点。

如果错误地把 2026-09-11 的 `C候` 当成买点，至 2026-09-14 收盘表现如下：

| 指标 | `C候` 样本 | 全市场基准 |
|---|---:|---:|
| 可评估样本 | 2369 | 5496 |
| 收盘平均收益 | +0.189% | +0.509% |
| 胜率 | 48.92% | 56.08% |
| 收盘上涨数 | 1159 | 3082 |
| 收平数 | 102 | 200 |
| 收跌数 | 1108 | 2214 |

结论：

- 严格 V2 在 2026-09-11 没有给出买点，这一点是合理的；
- `C候` 作为整体买入条件表现弱于全市场，不能整体放宽；
- 少数强反包样本存在价值，但应提炼为 `strong_repair_watch / 待触`，而不是让所有 `C候` 升级。

## 7. 当前问题判断

本轮数据暴露出四个优先问题：

1. `C候` 语义过宽，普通结构候选、回踩蓄势、破位修复、强修复待触发混在一起。
2. 空仓视角和持仓视角混用的问题已完成第一阶段修正：单股图面默认空仓视角，持仓动作只在持仓视角展示。
3. 强反包样本有价值，但不能从结果倒推前一日买点，必须形成次日确认/盘中触发条件。
4. 全市场重刷耗时 215 秒，离线重建可接受，但后续若要日常高频重刷，需要做增量索引或分层缓存。

## 8. 后续需求排序

1. `P21-A`：已完成。旧 C 可解释经验已进入 `facts.legacy_experience`，只作为素材，不授予交易许可。
2. `P21-B`：已完成第一轮。`2026-09-11 -> 2026-09-14` 消融显示旧 C 素材整体区分度不足，不能恢复为主链加权。
3. `P21-C`：已完成第一轮滚动消融。旧 C 素材覆盖过宽，不恢复入场加权；`strong_repair_watch / weak_repair_candidate` 仍保持观察态。
4. `P21-D/P25-E`：继续验证 `待触 -> 触 -> 买` 的真实样本转化率，重点看次日确认价是否改善表现。
5. `P26`：全市场重刷性能优化，优先研究快照级增量索引、按池增量更新和强反包样本缓存。
