---
status: current
contract_version: 1
last_verified: 2026-09-23
owners: local-user
supersedes: []
---

# Market Data Identity

## Purpose

行情序列在提供器、缓存、指标计算、单票 API 和扫描快照之间传递时，必须保留可追溯身份，不再只传递无来源的 DataFrame。

当前身份保存在 DataFrame `attrs.market_data_identity`，并由 serializer 输出为 `data_identity`。

## Fields

| Field | Meaning |
| --- | --- |
| `data_source` | 生成主要价格序列的实际来源 |
| `bar_state` | 末根 K 线是 `closed`、`preview`、`mixed` 或 `unknown` |
| `data_revision` | 对归一化 OHLCV 内容的 SHA-256 |
| `generated_at` | 本次分析请求的北京时间 |
| `cache_status` | `hit`、`miss`、`bypass` 或 `realtime_merge` |
| `cache_written_at` | 本地缓存文件的写入时间，不等于本次生成时间 |
| `calendar_id` | 本次 bar 状态判断使用的市场日历身份 |
| `calendar_revision` | 活动日历内容 revision |
| `calendar_evidence_level` | 末根 bar 日期实际使用的日历证据；2026 为 `exchange-official`，更早历史目前为 `provider` |

## Source Values

当前日线链路可产生：

```text
tencent_via_akshare
tencent_direct
tdx
<history_source>+tencent_realtime
tencent_realtime
unknown
```

这里的 `data_source` 同时编码“上游”和“接入适配器”，不是只表示 Python 库名：
`tencent_via_akshare` 表示**腾讯行情经 AkShare 的 `stock_zh_a_hist_tx` 封装取得**，
不表示 K 线由 AkShare 自己产生；`tencent_direct` 表示直接请求腾讯 K 线接口。
强制刷新时还可能把腾讯实时报价 bar 合并到历史序列，身份记为
`<history_source>+tencent_realtime`。日线空/落后时会尝试腾讯直连；无复权模式下才有
TDX 最终兜底。

旧缓存在写入时没有记录上游来源，读取后必须保持 `unknown`。不能根据文件名、当前默认提供器或是否命中缓存倒推历史来源。

## Bar State

当前日线使用保守规则：

- 末根日期早于北京当日：`closed`。
- 日历确认北京当日为交易日，且时间早于 15:10：`preview`。
- 日历确认北京当日为交易日，且已过 15:10：`closed`。
- 日历确认北京当日休市但数据源返回当日 bar：`unknown`，且不写入日线缓存。
- 末根日期晚于当日或无法解析：`unknown`。

该规则只判断末根 K 线的形成状态，不等于交易所日历。

## Propagation

```text
StockHistoryProvider
-> fetch_stock_history / cache metadata
-> normalize_price_frame
-> prepare_analysis_frame
-> analysis_frame_to_chart_payload
-> SingleStockAnalysis
-> build_scan_snapshot
-> CandidateSummary
```

新生成的扫描快照会写入 `bar_state`、`data_source`、`data_revision`、`generated_at`
和 `calendar_*`。快照新鲜度判断也使用同一活动日历：确认休市日不会强求当日 bar，
确认交易日 15:10 后则要求数据覆盖当日。旧快照保持 `unknown`，需通过正常重扫生成
新身份，不批量猜测回填。

## Known Gap

2026 年已由沪、深、北交易所年度休市公告提供官方证据，但交易所没有在当前公开页面
提供覆盖全部历史年份的统一机器数据集，因此历史部分仍保留 provider 身份。该日历能
改善 bar 状态判定，但不能单独证明扫描日完整性：

- 日历不可用或覆盖范围外时才降级使用原有周末规则，并保持 revision `unknown`。
- 不用当天是否有 K 线反向推断市场日历。
- 历史股票池仍为 `partial`，生产扫描链尚未消费，因此不能据此声称历史研究已经
  消除幸存者偏差。
