---
status: exploratory
strategy_version: "2026.09.19.1"
data_window: "Current code paths and publicly available source terms reviewed through 2026-09-23"
universe: "Current A-share application paths; not a legal opinion"
entry_model: "not applicable"
data_revision: "akshare 1.18.94; adata 2.9.5; pytdx 1.72"
evidence_level: primary-source-review
supersedes: []
---

# Upstream Data Terms Audit

## Scope

This is an engineering/source-governance review, not legal advice or a determination
that the present local use is lawful. It maps active repository calls to publicly
available source terms. A public URL, an open-source client, an endpoint that responds,
or a provider's acknowledgement of another data source does not itself establish a
license to cache, transform, display, redistribute, or commercialize the data.

The current documented product posture is a local personal research tool. A hosted,
shared, paid, or execution-facing product is a different distribution/use case and
must pass a separate rights review before data is exposed outside this machine.

## Active Data Paths

| Application use | Repository call / upstream | Evidence reviewed | Engineering disposition |
| --- | --- | --- | --- |
| Daily historical OHLCV | `providers/stock_history.py`: AkShare `stock_zh_a_hist_tx` (Tencent adapter), Tencent direct `proxy.finance.qq.com`; TDX only for unadjusted fallback | Tencent general terms direct users to product-specific terms. No specific public grant for these quote endpoints was located. The direct endpoints are undocumented in this repository as licensed APIs. | **Unresolved, high before distribution.** Do not infer data rights from endpoint accessibility, AkShare MIT, or Tencent's generic webpage terms. Obtain written confirmation for historical bars, local cache, derived chart display, and intended distribution. |
| Realtime quote / merged current-day bar | `providers/stock_quote.py`: `qt.gtimg.cn` | Same Tencent terms gap; no specific quote-feed license or permission statement located for this endpoint. | **Unresolved, high before distribution.** Keep local-only and do not expose a quote relay publicly without permission. |
| Minute K-lines | `providers/stock_history_minute.py`: AkShare `stock_zh_a_minute` (Sina), then TDX fallback | Sina Finance's published user agreement contains a data-use section restricting, absent written permission, certain copying/adoption, off-source display, and robot/spider acquisition. The fit between that agreement and the particular Sina endpoint/wrapper is not adjudicated here. | **Unresolved, high.** This app ingests bars into its own charts, outside the source page. Obtain permission or replace the feed before a public/shared deployment. |
| Current SSE/SZSE lists | `providers/market_reference.py`: AkShare exchange-list functions | SSE/SZSE public site terms cover website materials. SZSE permits non-commercial browsing/download subject to law and its statement, while restricting profit-oriented use without written permission. SSE market-data materials separately describe licensed vendor redistribution; the terms applicable to this project's exact list endpoints were not established. | **Endpoint scope unresolved.** Do not infer that bulk extraction, persistent snapshots, derived display, or downstream sharing is cleared merely because the lists are publicly viewable. Confirm exact endpoint and use before distribution. |
| Current BSE security list | `providers/market_reference.py`: AkShare `stock_info_bj_name_code` | The project retrieves current membership/name/listing fields from an AkShare adapter. BSE's quote-information licensing guide primarily describes market information generated from securities transactions; whether this specific directory/list endpoint is in scope was not established. | **Separate this from quote licensing.** Confirm applicable page/API terms and permitted automated retrieval/cache; do not assume either that the Level-1 license applies or that public visibility clears bulk use. |
| BSE daily/realtime quote bars | `providers/stock_history.py` and `providers/stock_quote.py`: Tencent via AkShare/direct Tencent; `providers/tdx_client.py`: TDX fallback | BSE's official licensed-unit list names Tencent for user queries in the Tencent Select Stock app/mini-program (2026-05-22 to 2027-05-21) and Shenzhen Fortune Trend for TDX products (2026-04-17 to 2027-04-16). The BSE guide requires licensed use. However, the project calls Tencent historical/realtime endpoints and TDX quote servers directly; public records do not establish whether those product licenses cover this independent local application, historical bars, storage, or derived chart display. | **Upstream authorization exists for specified products; this project's scope is unverified.** Do not infer that Tencent/TDX lack licenses, and do not infer that their licenses sublicense this app. Confirm endpoint, product surface, local user, retention, and derived-display scope with the relevant provider/rightsholder before external distribution; disable a path only if it is confirmed outside scope or the user chooses that risk posture. |
| THS concepts and industry data | `providers/concepts.py`, `providers/board_market.py`: AData THS functions and direct THS concept-page requests | AData's code is Apache-2.0 and its README names THS as an upstream. THS's published client license permits explicitly marked free products for personal non-commercial use but forbids copying/distribution and reserves ungranted rights. It does not expressly grant this application permission to scrape or republish the underlying endpoints. | **Unresolved for scraping / derived cache display.** The AData license covers software, not third-party source data. Obtain permission or replace the endpoint before external distribution. |
| Stock profile / sector | `providers/catalog.py`: AkShare `stock_profile_cninfo` (CNINFO) | The official CNINFO portal was identified, but an applicable data-use license for this endpoint was not established in this review. | **Unresolved.** Treat as source-attributed reference data, not redistributable data. Review the endpoint-specific terms before hosting or bulk export. |
| TDX fallback bars / code list | `providers/tdx_client.py` via `pytdx` 1.72 | The client package is separate from the data source. TDX's user agreement restricts access to its software/service data and use of unauthorized third-party tools; the agreement's application to this project's direct public quote-server protocol needs provider confirmation. | **Unresolved, high before distribution.** MIT/open-source status of client code does not license the quote feed. Prefer a documented licensed API. |
| AkShare / AData software | AkShare 1.18.94; installed AData 2.9.5; repository also contains an Apache-2.0 AData source snapshot | AkShare's code license is MIT and AData's source snapshot is Apache-2.0. AkShare separately states that its data is for academic research and reference only. AData lists upstream websites, including THS, but grants no evident upstream data rights in its software license. | **Software licenses do not clear data rights.** The app is described as personal research, not necessarily academic research; the AkShare statement therefore remains a use-purpose question, not an automatic permission. |

## Key Findings

1. **There is no single “AkShare data license” that covers the project.** AkShare is an adapter on several routes. Daily bars are attributed to Tencent; minute bars to Sina; some universe/profile/concept paths point to exchanges, CNINFO, THS, or AData. Each underlying source needs its own analysis.
2. **BSE is a scope-verification issue, not evidence that Tencent/TDX are unlicensed.** BSE publicly lists Tencent and TDX as licensed units for named products and periods. That is affirmative evidence of their authorization in those scopes; it does not by itself show whether their underlying endpoints can be consumed by this separate application or whether downstream rights pass through.
3. **Sina minute data and THS scraping deserve replacement/permission decisions before external use.** Their public terms do not supply a clear affirmative grant for this app's off-source ingestion and display.
4. **Local, private, non-commercial use is narrower than publishing data, but is not blanket clearance.** BSE's guide uses broad language for use by institutions and individuals, while its public vendor list confirms authorized product surfaces. The interaction between those terms and this project's local, direct-endpoint use is unresolved; neither “definitely prohibited” nor “automatically covered” is established here.
5. **Do not store raw provider error bodies or credentials in data-quality logs.** Existing new scan diagnostics store provider/status/error type only; keep that constraint if more source tracing is added.

## Decisions and Gates

- **Current local development:** keep using the existing Tencent/TDX endpoints as research data providers; this source-governance review is not a prerequisite for local architecture or feature work, and no runtime block is added. Preserve source and freshness labels. This engineering posture is not a legal finding about endpoint terms; revisit the review if data is exposed outside this local tool.
- **Before a LAN/public/shared release:** review the then-current terms for Tencent daily/realtime feeds, Sina minute bars, TDX fallback, THS/AData concept data, CNINFO profile data, and BSE market data. Confirm allowed user count, refresh rate, retention, derived indicators/signals, attribution, and redistribution; obtain written clarification where the published scope is ambiguous.
- **Before paid use or automated trading:** replace unresolved feeds with documented licensed APIs or obtain the corresponding agreements; record the agreement, licensee, permitted display surface, retention, and expiry in a durable source registry.
- **Do not treat this review as clearance:** the only defensible current status is `unresolved` for the feed permissions above; terms and endpoint behavior may change.

## Sources

- [Tencent service terms](https://www.tencent.com/zh-cn/term-of-service/) (specific product terms are separate) and [Tencent legal statement](https://www.tencent.com/legal-statement/)
- [SSE legal statement](https://www.sse.com.cn/home/legal/)
- [SSE market-data products and redistribution](https://english.sse.com.cn/markets/dataservice/products/)
- [SZSE legal statement](https://www.szse.cn/application/laws/)
- [BSE domestic market-data licensing guide](https://www.bse.cn/application/guide.html)
- [BSE licensed units (includes named Tencent and TDX products)](https://www.bse.cn/application/Licensing_unit.html)
- [SZSE trading information provisions](https://www.szse.cn/disclosure/notice/general/t20060515_499577.html)
- [Sina Finance user agreement](https://finance.sina.com.cn/roll/2021-05-12/doc-ikmxzfmm2033220.shtml)
- [THS financial-information service license](https://news.10jqka.com.cn/clientinfo/protocol.html)
- [AkShare repository / MIT license and data statement](https://github.com/akfamily/akshare)
- [AData repository](https://github.com/1nchaos/adata)
- [TDX user agreement](https://www.tdx.com.cn/about/yhxy/index.html?tabindex=0)
- [CNINFO official portal](https://www.cninfo.com.cn/)
