---
status: current
contract_version: 1
last_verified: 2026-09-23
implementation_status: official-2026-calendar-provider-history-and-partial-universe
owners: local-user
supersedes: []
---

# Market Reference Data

## Purpose

交易日历和历史时点股票池属于可版本化参考数据，不从当前日期、工作日规则或
今天的股票列表反推。它们保存在独立的 `.cache/market_metadata.sqlite3`，与行情、
扫描候选索引和策略 facts 分离。它们主要服务于历史时点研究；当前日常扫描使用
当前上市名单，并单独核验各股行情日期与状态，不需要重建北交所 2021 年开市成员。

当前已完成本地导入、版本记录和严格查询接口。生产扫描与 `/api/stock_list` 已通过
`CurrentUniverseService` 使用当前上市名单快照：按有效交易日读取 SQLite 名单 revision，
当日快照缺失时调用当前名单来源、导入并核对 revision；该路径不会用画像缓存拼凑名单。
这只保证“当前扫描有哪些成员”，不保证每只成员当日行情都有新 bar，也不建立完整历史沿革。
当前名单适配器通过 AkShare 函数读取交易所列表；`source=akshare-<version>:exchange-list-aggregate`
记录的是适配器/库版本，不应被解释成数据原始发布方就是 AkShare。成员来源类别会标出
上交所、深交所和北交所路径，但逐个接口 URL 和响应 revision 尚未统一保存。
metadata schema v5 新增有效期证券身份
表、导入器、按日投影与覆盖审计。活动日历以 provider 历史序列为基线，
并用沪、深、北三家交易所发布的 2026 年休市公告覆盖 2026 年；另有一份与
2026-09-22 扫描日对齐的部分历史股票池。日历已经参与日线 `bar_state` 的保守
判定；历史股票池不接管生产扫描。空数据仍必须返回 `unknown` / `available=false`，
不能静默使用猜测值。

## Trading Calendar

每次导入保存来源、证据等级、覆盖起止日、session 数量、导入时间和内容 revision。
schema v3 另外保存按日期生效的证据段及优先级。`session_context(date)` 只返回覆盖该
日期的最高优先级证据，因此可以同时表达“历史为 provider、2026 为交易所官方”，而
不是给整份混合日历贴一个失真的单一标签。
同一 `calendar_id` 可以保留多个 revision，查询只使用显式激活的最新导入。

- 覆盖区间内，没有出现在 sessions 中的日期返回 `false`。
- 覆盖区间外或没有日历时返回 `None`，表示未知，而不是休市。
- 前后交易日查询不会越过已声明的覆盖边界。

示例：

```bash
./venv/bin/python scripts/import_market_metadata.py calendar \
  --input /path/to/xshg_sessions.csv \
  --source exchange-export-20260923 \
  --evidence-level validated
```

CSV 默认读取 `session_date` 列；JSON 可以是日期数组或带 `sessions` 数组的对象。

当前活动日历覆盖 1990-12-19 至 2026-12-31，共 8,797 个 session。1990-2025 日期
仍使用 AkShare 1.18.94 打包的新浪交易日序列，证据等级为 `provider`；2026 日期由
仓库内的 `stock_analyzer/reference_data/official_market_schedules.json` 生成，证据等级为
`exchange-official`。该清单记录了上交所、深交所和北交所 2026 年休市公告 URL。
刷新时会用周一至周五减去公告休市区间生成全年交易日；本次与 provider 的 242 个
2026 session 完全一致。

离线刷新：

```bash
./venv/bin/python scripts/refresh_market_metadata.py calendar
```

## Point-in-time Universe

兼容股票池按 `as_of` 冻结，每个成员保存代码、名称、交易所、上市状态、上市/退市日期
和成员来源。schema v4 为整份导入另外保存结构化 `coverage`、`coverage_status` 与
`warnings`。默认查询要求
精确日期快照；只有调用方显式传入 `allow_previous=True` 才允许回退到更早快照，
且结果会返回 `fallback_used=true` 和真实 `resolved_as_of`。

```bash
./venv/bin/python scripts/import_market_metadata.py universe \
  --input /path/to/universe_20260922.csv \
  --as-of 2026-09-22 \
  --source provider-export-20260922 \
  --evidence-level validated
```

CSV/JSON 成员至少需要 `code`；可选字段为 `name`、`exchange`、
`listing_status`。生产全市场扫描与 `/api/stock_list` 使用在线主名单源的当前名单，
画像缓存不作为股票池。若完整主名单源不可用，这两条路径显式返回可重试错误，不退化成
可能截断的次级名单或静态保底名单。当前名单只回答“现在有哪些股票”，不得作为历史研究
的隐式替代品。

当前扫描资格还要求覆盖报告明确记录 SSE、SZSE、BSE 三所当前名单均可用；任一来源缺失、不可用、部分或状态未知时，不得把不完整快照当作全市场名单。历史退市记录缺口单独影响历史研究资格，不会仅因历史沿革不完整而阻断一份当前名单完整的扫描股票池。

交易所列表聚合刷新：

```bash
./venv/bin/python scripts/refresh_market_metadata.py universe --as-of 2026-09-22
./venv/bin/python scripts/validate_market_metadata.py --as-of 2026-09-22
./venv/bin/python scripts/audit_market_universe.py --as-of 2026-09-22
```

当前 2026-09-22 快照为 5,567 个成员，来源为上交所主板/科创板、深交所 A 股和
北交所当前列表，再结合上交所、深交所终止上市记录推导。北交所历史退出不仅包括
强制退市，也包括转板沪深；已核实的官方退出公告仍只是逐条证据，尚未证明全量覆盖。
此外，北交所存量代码于 2025-10-09 切换为 920 号段，精选层平移公司的官网“上市日期”
是原精选层挂牌日期，不等同于北交所成员起始日期。当前单一 `code + listing_date` 快照
无法表达全部有效期身份沿革。因此 `coverage_status=partial`，不得用于声称无幸存者偏差。
当前 provider 已把早于北交所 2021-11-15 开市日的 BSE 挂牌日期下限钳到开市日；历史
重建中缺少挂牌日期的 BSE 成员会被排除并记录 warning。此修正不补齐转板/退市事件，也
不解决 2025 代码切换前的历史代码映射。

证券级沿革契约见[证券身份与沿革模型](security-reference-model.md)。新模型以
稳定 `security_id` 表示证券，以交易所限定、有效期化的代码别名和独立交易所成员区间
表达代码切换、转板与退市；现有按日快照仍是兼容投影，不会被反推成完整沿革。已建立
五项官方北交所退出样例、两项代码切换，以及观典防务、泰祥股份、翰博高新三项转板
目的市场成员区间的 partial revision，位于
`stock_analyzer/reference_data/bse_membership_sample.json`。导入该样例不会改变现有股票池
快照或生产扫描；它不包含完整北交所/沪深历史成员变更或历史名称。观典防务 SSE 区间已
以官方摘牌日 2026-06-10 结束；泰祥与翰博仅有开始事件，未记录结束日期。样例不宣称完整，
也不应用于无幸存者偏差的研究。

```bash
./venv/bin/python scripts/import_market_metadata.py security-reference \
  --input stock_analyzer/reference_data/bse_membership_sample.json
./venv/bin/python scripts/audit_security_reference.py \
  --dataset-id A_SHARE_HISTORY --as-of 2021-11-22
```

覆盖审计不会把所有缺口等价处理：

- `blocking_gaps` 影响成员资格，当前为 `delisting_history.BSE`（该历史字段名目前也涵盖
  转板等非强制退市成员退出缺口，后续领域模型应改成 exchange-membership history）。
- `informational_gaps` 只影响描述或展示，当前为 `security_name_history.ALL`。
- `governance_gaps` 表示来源许可或使用条款仍需确认，当前为
  `governance.upstream_usage_terms`。

AkShare 1.18.94 的软件许可证为 MIT；AkShare 项目同时声明其接口及相关数据仅供学术研究。
AkShare 在此项目中是若干数据路径的客户端/封装，不是所有行情的原始来源：例如日线 K 线
通过其 `stock_zh_a_hist_tx` 调用腾讯，当前名单通过其函数读取交易所名单，分钟线还有
Sina 路径；强制刷新会直接请求腾讯实时报价。软件许可证不等同于这些上游来源的数据授权。
截至 2026-09-23，已完成公开来源条款与活跃代码路径映射，但尚未确认本地个人研究是否符合
AkShare 所称“学术研究”范围。北交所许可公示列有腾讯自选股和通达信的特定产品授权；本项目
直接使用的腾讯/TDX 接口与独立本地展示是否在许可范围内仍待核实。当前名单目录字段也与
行情数据分开判断。因此不据此认定上游无许可，也不认定许可自动覆盖本项目。治理缺口仍保留；
目前不对外提供数据服务或再分发原始数据。详细核验见
[`上游数据使用条款审查`](../research/upstream-data-terms-audit-2026-09.md)。

当前真实审计中 5,567 个成员的名称、交易所、上市日期和成员来源完整率均为 100%，
且没有上市/退市日期冲突，因此 `current_scan_eligible=true`；但因北交所历史成员退出、
代码沿革未完整建模，`historical_research_eligible=false`。调用方必须消费这两个不同结论，
不能只看成员数量。

需要在自动化任务中强制历史可用时使用：

```bash
./venv/bin/python scripts/audit_market_universe.py \
  --as-of 2026-09-22 \
  --require-historical-ready
```

当前该命令会以状态码 2 退出，这是预期的安全门，不是脚本故障。

## Integration Gates

以下门槛适用于历史时点股票池、历史证券身份，以及任何超出“当前名单”的参考数据
生产用途：

- 明确数据提供方、授权和刷新频率。
- 日历覆盖研究窗口并通过已知节假日抽查；尚未有官方证据段的历史年份不得标为
  `exchange-official`。
- 股票池能解释上市、退市、暂停上市和代码变更口径。
- 证券身份导入必须拒绝同一 revision 内重叠的成员/别名有效区间，并保留逐条来源证据。
- 研究结果记录 calendar、universe 和 security-reference revisions。
- 缺失历史快照时明确拒绝或降级，不能回退到当前股票列表。
