# 真实全市场扫描与候选读链验收：2026-09-23

## Evidence Scope

- 验收窗口：2026-09-23 20:07 至 21:03（Asia/Shanghai），收盘后强制全市场扫描。
- 策略版本：`2026.09.20.1`；数据窗口起点：`2025-04-29`；读取版本：当前工作树代码。
- 股票池：5,568 只，as-of `2026-09-23`，名单 revision `sha256:5c652812944c95528b1d46cf0a18e155e5f11464df996a60be77f9a0f898c695`。
- 名单来源标记：`akshare-1.18.94:exchange-list-aggregate`；日历证据为交易所官方 revision `sha256:f6d779530213a4548e486694f675a652ef753fa5da726e0d1f16996e16a8b409`。
- Evidence level：工作树代码与运行时任务结果直接验证；单日运营观察，不是统计性结论。

## Scan Result

扫描任务 `262a6ecc72c6` 完成 5,568/5,568，0 个任务失败。自动后处理索引了 5,568 份快照，生成 4,823 个跨池候选摘要；4,823 条排名上下文完整物化。日期和名单审计为 `consistent`，成员数、名单 revision、as-of 和日历 revision 均一致。独立审计输出：`.cache/current_universe_audits/2026-09-23.json`。

行情覆盖汇总：

- 已检查 5,568；当日收盘 bar 5,556；旧数据/无新 bar 12；盘中预览、无数据、最终 provider 错误、部分失败、分析错误均为 0。
- 最终 fetch 状态为 5,567 `available`、1 `cache_hit`。来源计数为 5,248 `tencent_via_akshare`、319 `tencent_direct`、1 `unknown`。
- provider 尝试计数里有 307 次 `tencent_via_akshare:error`；最终数据层错误计数仍为 0。尝试次数不等于失败股票数。
- 12 只最后数据日期落后于 2026-09-23 的股票：301139 元道通信（08-28）、002731 ST萃华（08-31）、000016 *ST康佳A（09-03）、688496 ST清越（09-10）、601238 广汽集团（09-11）、605303 园林股份（09-11）、601059 信达证券（09-14）、601198 东兴证券（09-14）、603400 华之杰（09-14）、300082 奥克股份（09-18）、300585 奥联电子（09-18）、002860 星帅尔（09-21）。只记为旧数据/无新 K 线，不据此判定停牌。
- 唯一 `unknown` 来源候选为 600063 皖维高新：快照的 bar state 是 `closed`，数据日期是 09-23，但来源未知；命中的旧缓存元数据只保留写入时间和最新日期。当前保留 unknown，不推断具体 provider。

本次任务的 `issue_samples` 为空，复查发现原逻辑只按原始 fetch status 采样，无法捕获“fetch 可用但有效分类为 stale”的股票。现已改为按最终分类采样，并在来源 unknown 时保留样本；这次已完成任务不会被回写，需在下一次扫描确认修复效果。

## Retrospective Issue-Sample Replay (2026-09-24)

为避免仅靠等待新交易日验证分类采样，使用 2026-09-23 的 5,568 份逐股快照，将持久化的 `data_date`、`bar_state`、`data_source`、`cache_status` 输入当前 `ScanJobManager._accumulate_data_coverage_unlocked` 重放。重建出 12 条 `stale_or_no_new_bar` 和 1 条 `data_source=unknown`，合计 13 条 `issue_samples`；与当日覆盖统计中的 12 条旧数据/无新 bar、1 条来源未知一致。

这验证了当前代码会从已保存的行情身份字段挑出这两类问题记录，不需要为该逻辑单独等待多个交易日。边界：旧快照没有保存原始 `fetch_status` 或 `fetch_attempts`；回放为调用分类函数而传入 `available` 占位值，生成的尝试列表为空。因此它不证明实际 provider 尝试明细已被正确采集。下一次真实扫描只需针对这一 live-only 部分检查 job 汇总里的实际 fetch/attempt 字段；若结果正常且无新的覆盖异常，不再把“凑满三天”作为固定门槛。

## Read-Path Shadow

扫描完成后用当前工作树代码比较 JSON workspace 与 SQLite 最新读路径。首次比较发现 SQLite 多返回旧数据股票；根因是 workspace 默认路径应用 `is_recent_snapshot`，SQLite latest 查询没有应用。现已在 SQLite 最新列表和默认详情路径复用同一新鲜度判定；显式 `snapshot_day` 历史读取不做此过滤，仍保留原始快照。

修正后的最新视图结果：

| Pool / filter | JSON | SQLite | Contract |
| --- | ---: | ---: | --- |
| opportunity | 3,378 | 3,378 | 成员、决策/描述字段、计数、分页通过 |
| risk | 840 | 840 | 成员、决策/描述字段、计数、分页通过 |
| bottom_div | 595 | 595 | 成员、决策/描述字段、计数、分页通过 |
| opportunity + `plan_ready` | 34 | 34 | 成员和顺序完全一致 |
| risk + `plan_ready` | 0 | 0 | 一致 |
| bottom_div + `plan_ready` | 0 | 0 | 一致 |

最新未过滤读取的 top-20、top-50、top-120 重叠均为 100%；完整顺序并非逐项相同，opportunity 与 risk 各有 2 个排名字段差异，bottom_div 顺序一致。候选排序语义仍未由产品裁决，所以这不批准生产读链切换。

影子输出：`.cache/scan-candidate-shadow-2026-09-23.json`、`.cache/scan-candidate-shadow-plan-ready-2026-09-23.json`。离线测试：`./venv/bin/python -m unittest discover -s tests`，362 tests OK。

## Remaining Gates

1. 下一次真实扫描核对实际 `fetch_status`、provider attempts 与名单 revision；仅在发现不一致或新类别问题时延长多日观察。
2. 完成候选优先与单票优先原型的真实任务体验，再决定排序语义与默认入口。
3. 保持 SQLite 为 opt-in 读路径；排序语义、错误/降级、筛选分页和用户体验仍是切换门槛，历史契约样本与一次必要的 live-only 核验可替代机械等待固定天数。
4. 本机 5009 端口仍运行旧服务，报告的策略版本为 `2026.09.09.2`；本次验收在隔离的当前代码服务上完成。静态原型不依赖 5009；如需对照生产页面，应另启当前工作树版本。

详情见上文“Retrospective Issue-Sample Replay”。
