---
status: exploratory
strategy_version: "2026.09.20.1"
data_window: "2025-04-29 through 2026-09-24"
universe: "Current provider snapshot as of 2026-09-24"
entry_model: "not applicable; candidate read-path comparison"
data_revision: "universe sha256:6d8baa77137aaa82e01469f0d92ea6529455947d5a7da6633b8e6d98e9b3b985; snapshot rank context sha256:d25072087c57e7a8d189b7aa0b7200d7fa47cd07fd0ae65396dae97288200510; latest_fresh rank context sha256:100790b76dd92c64c14ad20cf439275ad72918546033e153bdeeaa85ec8f4236"
evidence_level: "single live full-market scan plus local shadow comparison"
supersedes: []
---

# 真实全市场扫描与候选读链验收：2026-09-24

## 范围

- 收盘后强制扫描于 2026-09-24 16:05 至 16:58（Asia/Shanghai）执行，任务 `7ce3034a464c`。
- 运行代码：当前工作树；策略 `2026.09.20.1`；前复权日线，起始日期 `2025-04-29`。
- 当前股票池 5,569 只，as-of `2026-09-24`，revision `sha256:6d8baa77137aaa82e01469f0d92ea6529455947d5a7da6633b8e6d98e9b3b985`，来源标记 `akshare-1.18.94:exchange-list-aggregate`。
- 当日交易日历审计为交易日，证据级别 `exchange-official`；股票池和任务审计为 `consistent`，成员数与 revision 完全匹配。
- 证据级别：单个真实全市场扫描和本机影子比较；不是持续运行统计，也不构成候选排序的产品批准。

## 行情覆盖

- 检查 5,569；确认有 2026-09-24 收盘 bar 的 5,551；旧数据/无新 bar 的 18。盘中 preview、无数据、最终 provider 错误、部分失败、缓存陈旧、分析错误均为 0。
- 最终 fetch 结果为 5,552 `available`、17 `cache_hit`。来源计数：3,615 `tencent_direct`、17 `tencent_direct+tencent_realtime`、1,937 `tencent_via_akshare`。
- provider 尝试级别有 307 次 AkShare 错误和 7 次腾讯直连错误；这是重试次数，不是最终失败股票数。扫描最终失败数为 0。
- 18 只旧数据样本保存在任务记录 `.cache/scan_jobs/close_20260924/jobs.json`。旧数据只表示当日 bar 未确认，不推断为停牌；其中一些样本存在行情请求超时。

## SQLite 落盘

- `.cache/scan_index.sqlite3` 中 `20260924:2026.09.20.1:qfq:20250429` 的扫描记录为 5,569 份快照、5,134 条跨池候选摘要，最新数据日期为 `2026-09-24`。
- 快照清单 5,569 条，其中 5,551 条 `data_date=2026-09-24`；索引解析正常。完整快照 contextual rank overlay 覆盖 5,134 条，`latest_fresh` overlay 覆盖 5,118 条，两种 scope 分别持有 revision。
- 独立全市场审计命令：`venv/bin/python scripts/audit_current_universe_scan.py --as-of 2026-09-24 --jobs .cache/scan_jobs/close_20260924/jobs.json`，结果 `consistent`。

## JSON 与 SQLite 影子比较

比较使用当前默认“最新”读路径和 `rank_mode=contextual`，未切换生产客户端。SQLite 新读链耗时为本机单次观察值，不是基准测试。

| Pool / filter | JSON | SQLite | 成员与硬字段 | 描述字段 | 分页/计数 | 顺序 |
| --- | ---: | ---: | --- | --- | --- | --- |
| opportunity | 3,632 | 3,632 | 完全一致 | 完全一致 | 通过 | 修复后全量分数与顺序完全一致 |
| risk | 1,150 | 1,150 | 完全一致 | 完全一致 | 通过 | 修复后全量分数与顺序完全一致 |
| bottom_div | 336 | 336 | 完全一致 | 完全一致 | 通过 | 全量顺序完全一致 |
| opportunity + `plan_ready` | 71 | 71 | 完全一致 | 完全一致 | 通过 | 全量顺序完全一致 |
| risk + `plan_ready` | 0 | 0 | 一致 | 一致 | 通过 | 无结果 |
| bottom_div + `plan_ready` | 0 | 0 | 一致 | 一致 | 通过 | 无结果 |

latest 三池的候选总数、成员、关键决策字段、描述字段、过滤条件、完整分页及全量排序均通过硬契约。`plan_ready` 机会池 71 条的成员和完整顺序也完全一致。

本机 `test_client` 单次耗时观察：opportunity JSON 约 8.8s、SQLite 约 2.3s；`plan_ready` JSON 约 7.3s、SQLite 约 0.9s。由于是顺序单次测量，受缓存和主机状态影响，只用于说明可能的成本方向，不作为性能承诺。

显式传 `snapshot_day=2026-09-24` 而不传 `strategy_version` 时，SQLite API 的 contextual 排序会回退到 `snapshot_local`，并在 `ranking.fallback_reason` 标明 `not_materialized`。本次验收使用生产最新读路径，contextual overlay 正常应用。历史日 contextual 查询需显式限定策略版本，后续应在 API/比较器契约中保持这一点可见。

## 长尾排序差异复核与修复

首次比较中的 8 条 opportunity 和 3 条 risk 排名字段差异，已定位为排名上下文候选范围不一致，而非 SQLite 丢行或排序公式分叉：物化器使用完整快照集合（5,134 条），线上 latest JSON 工作区则先剔除过期快照（5,118 条）。全池排序包含大量相同的舍入分数，少量分数受行业/概念横截面变化影响后，会造成较大的长尾位置位移。

实现已分为两个独立排名 scope：`snapshot` 服务显式历史日查询；`latest_fresh` 精确服务默认最新查询。SQLite 状态检查逐个比较当前候选 ID 与 overlay 覆盖的 ID，候选新鲜度变化导致缺项或越界时会拒绝使用旧上下文。2026-09-24 本机索引重新物化后，`snapshot` 覆盖 5,134/5,134，`latest_fresh` 覆盖 5,118/5,118；latest 三池排名字段差异为 0，完整顺序零位移；`plan_ready` 机会池 71 条也完整顺序零位移。

复核产物位于 `.cache/scan-shadow-contextual-20260924.json` 和
`.cache/scan-shadow-contextual-plan-ready-20260924.json`。重新物化可使用：

```bash
venv/bin/python scripts/materialize_candidate_rank_context.py --snapshot-day 2026-09-24 --scope snapshot
venv/bin/python scripts/materialize_candidate_rank_context.py --snapshot-day 2026-09-24 --scope latest_fresh
```

这是同一真实交易日、同一候选样本上的修复后本机证据，不代表多日稳定性或生产读链已经切换。

复现命令：

```bash
venv/bin/python scripts/compare_scan_candidate_reads.py --rank-mode contextual --summary-only --output .cache/scan-shadow-contextual-20260924.json
venv/bin/python scripts/compare_scan_candidate_reads.py --rank-mode contextual --reason plan_ready --summary-only --output .cache/scan-shadow-contextual-plan-ready-20260924.json
```

## 结论与门槛

SQLite latest 读路径在本次样本上满足三池成员、数据和全量排序契约，并显著降低候选工作台构建耗时；这足以继续影子观察和准备验收，但**不等于批准切换生产**。排序范围差异已修复；切换仍依赖 UI 原型任务对比，以及索引不可用、部分索引和降级体验验收。无需机械等待固定天数；仅在后续真实扫描出现新的覆盖类别或索引不一致时再扩大 live-only 核验。
