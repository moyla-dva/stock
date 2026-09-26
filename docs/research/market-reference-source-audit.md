---
status: exploratory
strategy_version: "2026.09.19.1"
data_window: "1990-12-19 to 2026-12-31; universe as of 2026-09-22; source review through 2026-09-23"
universe: "provider-derived A-share snapshot"
entry_model: "not applicable"
data_revision: "calendar sha256:12d66ed; universe sha256:9d94315e; security_reference sha256:a4a80b428fc0f6580590df566776f9ee13c0bb4b15057d6f06d5b40c89a3c075"
evidence_level: production-observation
supersedes: []
---

# Market Reference Source Audit

## Calendar

AkShare 1.18.94 内置新浪交易日序列共 8,797 个 session，覆盖 1990-12-19 至
2026-12-31。该序列与上交所《2026 年部分节假日休市安排》中的中秋、国庆关键
开闭市日抽查一致。来源仍标记为 `provider`，不提升为 authoritative。

官方核对入口：

- https://www.sse.com.cn/disclosure/dealinstruc/closed/list/
- https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml

## Universe

2026-09-22 推导快照共 5,567 个代码：深交所 2,902、上交所主板 1,702、科创板
618、北交所 345。与本地画像缓存 5,525 个代码比较，重叠 5,511，股票池独有 56，
画像缓存独有 14。差异说明画像缓存不是可替代的股票池事实源。

历史推导使用交易所当前列表的上市日期，并结合上交所、深交所终止上市列表。
北交所完整退市历史与历史简称 revision 尚缺，因此该快照标记为 `partial`。

官方列表入口：

- https://www.sse.com.cn/assortment/stock/
- https://star.sse.com.cn/assortment/stock/list/delisting/
- https://www.szse.cn/market/product/stock/list/index.html
- https://www.szse.cn/market/stock/suspend/index.html
- https://www.bse.cn/nq/listedcompany.html

### BSE Membership Exits and Identity Changes

截至 2026-09-23，官方公告可逐条核实到至少两类不能由“退市名单”单独覆盖的退出事件：

| Event | BSE membership end | Evidence |
| --- | --- | --- |
| 观典防务转板至上交所 | 2022-04-26 | [BSE termination/transfer notice](https://www.bse.cn/disclosure/2022/2022-04-25/1650875588_282390.pdf), which also records its 2021-11-15 identity conversion to BSE |
| 泰祥股份转板至深交所 | 2022-07-18 | [BSE termination/transfer notice](https://www.bse.cn/disclosure/2022/2022-07-15/1657874128_515467.pdf), which also records its 2021-11-15 identity conversion to BSE |
| 翰博高新转板至深交所 | 2022-07-25 | [BSE termination/transfer notice](https://www.bse.cn/disclosure/2022/2022-07-22/1658483683_879987.pdf), which also records its 2021-11-15 identity conversion to BSE |
| 广道数字强制终止上市 | 2026-01-05 | [BSE delisting notice](https://www.bse.cn/disclosure/2025/2025-12-31/8690dbac1d5c42db98e9c7388e562129.pdf) |
| 南京云创强制终止上市 | 2026-07-30 | [BSE termination decision](https://www.bse.cn/disclosure/select_stop/200028455.html), [issuer delisting notice](https://www.bse.cn/disclosure/2026/2026-07-29/8a64d7d9ca1641609307b4f2aa5fecaf.pdf) |

这五项是已找到并核实的退出样例，不等于已证明覆盖完整。北交所官网提供公告检索和
新旧代码对照表，但本次未发现带版本、覆盖区间和完整性声明的全部历史成员/退出清单。
因此不能用“当前列表 + 退市名单”重建历史 BSE 股票池；转板到沪深的公司也必须作为
BSE 成员退出事件处理。

身份时间还需要单独建模：北交所于 2025-10-09 为存量股票启用 920 代码；官网新旧代码
对照表也明确，精选层平移公司的“上市日期”是其原精选层挂牌日期，并非北交所成员起始日。
例如广道数字 `839680 -> 920680`、南京云创 `835305 -> 920305`。因此公司/证券身份、
交易所成员区间、有效期代码不能压成单个 `code + listing_date` 字段。

五项退出样例和广道数字、南京云创的新旧代码区间现已写入
`stock_analyzer/reference_data/bse_membership_sample.json`。这些记录使用不含股票代码的
opaque `security_id`，并分别引用成员/别名区间起止证据。它们只证明对应样例，不构成完整的
BSE 成员清单；revision 必须保持 `partial`。

本次复核修正了广道高新的开市入场原因：北交所官方上市公告书显示代码 839680 于
2021-11-15 上市，是公开发行新股，不是精选层平移；它属于开市首日十只新股。对应
membership 起点改引该上市公告书，`entry_reason` 改为 `bse_new_public_offering`。
云创数据的起点另补北交所托管的 2022 年年报作为逐只来源；观典、泰祥、翰博的官方
转板公告均直接叙述了 2021-11-15 身份转换。样本现有 14 条证据记录，五项 BSE 退出、
两项代码切换和三项目的市场区间的数量不变。

#### Verified Transfer Destinations

三个跨市场转登记案例的目的市场边界另有交易所上市公告支持：

| Instrument | Destination interval | Evidence |
| --- | --- | --- |
| 观典防务，688287 | SSE `[2022-05-25, 2026-06-10)` | [SSE listing notice](https://www.sse.com.cn/disclosure/announcement/listing/c/c_20220523_5702466.shtml), [SSE delisting notice](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20260608_10821090.shtml) |
| 泰祥股份，301192 | SZSE `[2022-08-11, open)` | [SZSE listing notice](https://www.szse.cn/disclosure/notice/company/t20220810_595301.html) |
| 翰博高新，301321 | SZSE `[2022-08-18, open)` | [SZSE transfer listing prospectus](https://disc.static.szse.cn/download/disc/disk03/finalpage/2022-08-17/51fce967-293a-490b-916b-60c40783b28f.PDF) |

观典防务的 SSE 区间依据上交所 2026-06-08 摘牌公告，于 2026-06-10 摘牌日结束。泰祥和
翰博的样例只有经交易所公告确认的起点，`open` 仅表示本 revision 未记录结束事件，并由
`coverage_end` 截断投影；它不是对之后持续上市的证明。三个目的市场区间使用原 `security_id`
延续证券身份，因为对应北交所终止公告明确为跨市场转登记。沪深市场其余成员历史、名称和
事件仍缺，整体 coverage 继续为 `partial`。

#### Full-History Source Availability

本轮再次检查北交所官方数据入口：[股票列表](https://www.bse.cn/nq/listedcompany.html)
是可搜索的动态页面，未提供可引用的历史 revision、明确覆盖起止日期或完整性声明；
[新旧代码对照表](https://www.bse.cn/service/code_mapping.html)列出 920 号段切换映射，
并明确一部分“上市日期”沿用原精选层挂牌日，但它不是成员变更事件表，无法表示转板、
退市及其有效日期。官网近期上市信息也只是新增事件，不能与当前列表拼接成完整历史。
北交所公开的[交易支持平台数据接口规范](https://www.bse.cn/uploads/6/file/public/202209/20220902201701_kas8vw9r25.pdf)
将 `GSyymmdd.nnn` 描述为挂牌/上市公司、两网公司及退市公司的“信息公告摘要”文件，
而非带覆盖声明的全量成员快照；规范本身也没有说明历史文件的可获取范围。

同期[北京日报报道（由北京市政府门户转载）](https://www.beijing.gov.cn/fuwu/lqfw/gggs/202111/t20211113_2536285.html)
给出开市首日 81 家、71 家精选层平移加 10 家新上市的数量，并列出十家新上市公司；这
只能用于总数交叉检查，不能替代完整的官方成员名册。[北交所相关公告检索页](https://www.bse.cn/products/neeq_listed_companies/related_announcement.html)
提供证券代码/简称、关键字、日期和分类筛选，可定位单项公告；但本次没有验证结果分页是否穷尽、是否
存在可重复的批量导出，也没有找到档案覆盖范围声明。检索入口可用不等于历史事件集完整。
当前仍未找到一份可直接导入并据以宣称完整的北交所历史成员文件。下一步应验证官方历史
公告搜索/归档的完整性和导出能力，找到开市前 71 家精选层成员的可复核名册，并把事件清单
与官方当前名录、退市/转板公告独立对账；在此完成前不提升覆盖等级，也不从当前代码表外推
历史成员。
事件级来源、规范化字段和验收门槛详见
[证券沿革事件来源清单](security-reference-event-sources.md)。

### Upstream Use Terms

项目锁定的本地 AkShare 版本为 1.18.94，已核对其包元数据的代码许可证为 MIT。需区分
调用库与原始数据上游：

| Data path | Client/adapter in this repo | Upstream represented by current code |
| --- | --- | --- |
| 日线历史 K 线 | `ak.stock_zh_a_hist_tx` | Tencent; empty/stale response triggers a direct Tencent K-line request |
| 强制刷新的当日实时 bar | `requests` in `providers/stock_quote.py` | Tencent quote endpoint |
| 当前交易所名单 | AkShare functions in `providers/market_reference.py` | SSE/SZSE/BSE list paths; per-call URL/revision is not yet stored |
| 本地交易日历基线 | AkShare packaged `calendar.json` | Sina calendar bundled by AkShare; 2026 is overlaid with exchange-official notices |
| 分钟线 | `ak.stock_zh_a_minute` | Sina, with TDX fallback |

因此先前若把“日线来自 AkShare”当作数据来源表述是不准确的：AkShare 在日线主路径中是
客户端封装，代码把该来源标记为 `tencent_via_akshare`；直接腾讯路径标记为
`tencent_direct`。AkShare 项目关于接口/相关数据用途的声明仍需记录，但代码 MIT 许可证
不自动授予 Tencent、交易所、Sina、THS 或其他底层站点数据的抓取、缓存、展示、再分发及
商业使用权。本项目尚未逐上游审查这些条款。

结论：库代码许可证已核对；截至 2026-09-23，已完成一次公开来源条款与活跃代码路径映射，
但尚未取得各接口的书面许可，也未裁定本地个人研究是否符合 AkShare 的“学术研究”声明。
北交所已将腾讯自选股和通达信列为特定产品的行情许可单位；但本项目直接调用的腾讯/TDX
接口及独立本地展示是否落在其许可范围内仍待确认。北交所当前名单字段是否属于行情许可对象
也需与日线/实时报价分开核实。因此既不能据此认定上游无许可，也不能认定许可自动覆盖本项目。
当前不对外提供数据服务或再分发原始数据，也不把这些来源视为已通过商业/公开部署审查。
这是一项工程治理记录，不构成法律意见。详细状态见
[`上游数据使用条款审查`](upstream-data-terms-audit-2026-09.md)。

来源：

- [AkShare repository and MIT license](https://github.com/akfamily/akshare)
- [AkShare project overview and data-use statement](https://github.com/akfamily/akshare/blob/main/docs/introduction.md)
- [BSE historical code mapping](https://www.bse.cn/service/code_mapping.html)
- [BSE notice for existing-stock code cutover](https://www.bse.cn/important_news/200026735.html)
- [BSE establishment and opening date](https://www.bse.cn/company/introduce.html)

## Decision

- provider 日历可以用于保守 bar 状态判断，并随分析结果记录 revision。
- 部分历史股票池只用于发现数据差异和继续建设，不接管历史事件研究或生产扫描。
- 已定义有效期证券代码别名和交易所成员区间，并导入经核对的官方退出样例；
  在全量完整性核验前仍保留 `partial`，不接管历史事件研究或生产扫描。
- 在补齐全市场成员变更、代码变更和历史名称前，不宣称已消除幸存者偏差。
