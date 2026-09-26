---
status: exploratory
strategy_version: "2026.09.19.1"
data_window: "BSE opening 2021-11-15 to 2026-09-23; SSE/SZSE source discovery through 2026-09-23"
universe: "A-share exchange membership and security identity events"
entry_model: "not applicable"
data_revision: "security_reference sha256:a4a80b428fc0f6580590df566776f9ee13c0bb4b15057d6f06d5b40c89a3c075"
evidence_level: exploratory
supersedes: []
---

# Security Reference Event Sources

## Scope

This inventory defines the evidence needed to rebuild effective-dated exchange membership,
code aliases, and display names. It does not claim complete historical coverage. The current
interval importer remains the materialized read model; source events must be retained and
reconciled before a dataset can move beyond `partial`.

## Official Source Inventory

| Fact or event | Primary evidence | Required extraction | Known limitation |
| --- | --- | --- | --- |
| BSE opening cohort, 2021-11-15 | [BSE opening information](https://www.bse.cn/company/introduce.html), per-issuer BSE listing notices, and a dated official opening roster if recoverable | Every opening instrument, exchange code, share class, opening effective date, and carryover-vs-new-issue classification | Per-issuer official records can establish individual starts; the [BSE listing notice for Guangdao High-Tech](https://www.bse.cn/disclosure/2021/2021-11-10/1636545494_353932.pdf) proves one new-issue example. A government-hosted contemporary [Beijing Daily report](https://www.beijing.gov.cn/fuwu/lqfw/gggs/202111/t20211113_2536285.html) gives the denominator (81 total: 71 Select Layer carryovers + 10 new listings) and names the ten IPOs, but is not the complete primary roster. |
| Listing start / transfer-in | Exchange listing notice: [SSE announcements](https://www.sse.com.cn/assortment/stock/list/info/announcement/) or [SZSE company notices](https://www.szse.cn/disclosure/notice/company/index.html); BSE notices searchable through its [related-announcement page](https://www.bse.cn/products/neeq_listed_companies/related_announcement.html) | Exchange, code, instrument identity, first trading/member date, source event ID | Announcement publication date can differ from the effective listing date; extract the latter from the notice. |
| Transfer-out | BSE termination/transfer notice paired with destination-exchange listing notice | Source exchange end and destination exchange start as two separately evidenced boundaries | A transfer notice alone does not establish the destination start date. |
| BSE termination / delisting | BSE termination decision and the notice specifying the delisting/termination effective date; [BSE disclosure search](https://www.bse.cn/disclosure/) | Membership end date, terminal reason, last-trading date when separately stated | Suspension, risk warning, or absence from today's list is not a membership end. |
| SSE delisting | [SSE delisted-company list](https://star.sse.com.cn/assortment/stock/list/delisting/) and the corresponding SSE delisting/termination notice | Membership end boundary and official code/name at the event | A list page may be current-state or rolling; verify historical coverage and date semantics before treating it as complete. |
| SZSE delisting / suspension | [SZSE stock suspension/termination page](https://www.szse.cn/market/stock/suspend/index.html) plus the corresponding termination notice | Distinguish temporary suspension from membership termination; capture effective end | The page combines status concepts; suspension must never be normalized as delisting. |
| BSE old/new code alias | [BSE code mapping](https://www.bse.cn/service/code_mapping.html) plus [2025 code-cutover notice](https://www.bse.cn/important_news/200026735.html) | Old code, new code, same instrument ID, effective cutover date, source | The mapping page's “listing date” may be the earlier Select Layer date, not BSE membership start. Snapshot the page; it has no declared revision history. |
| Name change | Exchange-hosted issuer announcement with the name-change effective date; BSE procedure is described in its [name-change guidance](https://www.bse.cn/uploads/6/file/public/202504/20250426144919_3g1xl9i4ms.pdf) | Separate issuer legal name from exchange display name; capture each effective date independently | A company announcement date is not necessarily the security display-name effective date. Current name lists cannot reconstruct old names. |
| Current reconciliation roster | [BSE current stock list](https://www.bse.cn/nq/listedcompany.html), [SSE stock list](https://www.sse.com.cn/assortment/stock/list/), [SZSE stock list](https://www.szse.cn/market/product/stock/list/index.html) | Dated observation, normalized instrument/code set, source response hash | These are dynamic current lists, not historical snapshots. They validate a present-day cross-section but cannot establish why or when a missing member exited. |

The BSE [transaction-support data interface specification](https://www.bse.cn/uploads/6/file/public/202209/20220902201701_kas8vw9r25.pdf)
describes `GSyymmdd.nnn` as announcement summaries for listed, delisted, and other
companies. The specification does not identify it as a complete point-in-time membership
snapshot and does not state how far back those files remain available.

## Opening Cohort Evidence

The BSE's official introduction confirms the opening date, while the government-hosted
contemporary report establishes an 81-company cross-check and enumerates the ten new IPOs:
大地电气、汉鑫科技、中设咨询、志晟信息、中寰股份、广道高新、同心传动、晶赛科技、
科达自控、恒合股份. Treat this report as secondary evidence for the count, not as the source
of the membership rows. The BSE-hosted Guangdao listing notice independently establishes that
one opening-day name was a new public offering rather than a Select Layer carryover; it is a
useful per-instrument pattern, not a complete roster. The remaining names need an official dated
Select Layer roster or individually checkable official records that establish each company's
opening membership and whether it was carried over or newly listed.

The current BSE old/new code mapping is also not a substitute: it records stocks present at the
2025 code cutover, includes later listings, and cannot represent members that left before that
cutover. It can establish aliases when paired with the universal cutover notice, but cannot
initialize the 2021 cohort.

## Event Normalization Contract

Each extracted event should preserve at least:

- `event_id`, `event_type`, `security_id`, `exchange`, and the code/name before and after.
- `effective_date` separately from `document_date` and `accessed_at`.
- `source_url`, publisher, document title, evidence level, and a content hash when the source
  artifact can be retained lawfully.
- Explicit `boundary_role`: `membership_start`, `membership_end`, `alias_start`,
  `alias_end`, or `name_start` / `name_end`.
- `identity_resolution`: verified, ambiguous, or unresolved. Similar issuer names alone do
  not establish share-class continuity.

Membership is materialized as `[valid_from, valid_to)`. An end event closes membership at
its effective date. A transfer creates a source-market end and a destination-market start;
the two intervals need not be adjacent. A start without a verified end is right-censored
at the dataset `coverage_end`, not evidence of permanent or post-coverage membership.
Issuer legal names and exchange display names must not be conflated.

## Coverage and Acceptance Gates

1. Recover and freeze an evidenced BSE opening cohort. Without it, the BSE historical member
   count cannot be initialized reliably.
2. Enumerate BSE listing entries and exits, including transfer-outs, forced delistings,
   voluntary terminations where applicable, and the 2025 code cutover.
3. Pair each transfer-out with its destination exchange start; resolve instrument identity
   from explicit transfer language, not a fuzzy name/code match.
4. Build independent interval timelines for SSE and SZSE, including historical exits and
   code/name changes. Do not let current-list presence backfill unknown historical events.
5. Reconcile the materialized universe against dated official rosters at opening, year-end,
   major code-cutover dates, and the latest available observation. Report unmatched additions,
   exits, duplicate identities, alias gaps, and unresolved intervals separately.
6. Preserve raw evidence references and immutable import revisions; only a complete, reviewed
   event inventory can change the coverage declaration. The current production scans and
   historical studies remain disconnected from this partial dataset.

## Current State and Next Work

The current seed records five BSE exits, two old/new BSE code transitions, and three verified
transfer destinations. Its SQLite projection has five securities, ten aliases, eight exchange
membership intervals, fourteen evidence rows, and no interval or foreign-key errors. Its overall
coverage is still `partial`; name history is absent and historical research eligibility remains
false. See [the source audit](market-reference-source-audit.md) for the sample and revision.

The BSE related-announcement interface visibly offers code/name, keyword, date, and category
filters, so it is useful as a discovery tool. This review could not verify exhaustive pagination,
a repeatable bulk export, or a declared date-complete archive; a filterable search page is not
itself proof of complete coverage. The next data task is to test those properties and locate the
official 71-company opening-eve roster. If neither is available, record the irreducible coverage
gap and do not synthesize missing membership events from a current list.
