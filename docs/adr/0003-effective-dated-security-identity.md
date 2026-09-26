---
status: accepted
decision_date: 2026-09-23
last_verified: 2026-09-23
supersedes: []
---

# ADR-0003: Effective-Dated Security Identity

## Context

`universe_members` stores point-in-time snapshots keyed by date and code. It cannot
express a code change, an exchange transfer, repeated exchange membership, or the
difference between a security leaving one exchange and being delisted entirely.
The problem is visible in BSE history: selected-layer companies were carried over,
codes moved to the 920 prefix on 2025-10-09, and some securities later transferred
to Shanghai or Shenzhen. A current roster plus a listing date cannot reconstruct
those intervals.

## Decision

Model a listed share-class instrument with a stable internal `security_id`. It is
not an issuer identifier and must never be derived from the current ticker or name.
An identity is only merged across codes or exchanges when source evidence supports
continuity of the same instrument; otherwise keep the relationship unresolved.

Keep four kinds of facts separate:

1. `security_entities`: stable instrument identity within an immutable reference
   revision.
2. `security_aliases`: exchange-qualified `(exchange, code)` identifiers with
   effective intervals. A code alone is not globally unique and is not an identity.
3. `exchange_memberships`: intervals for a security's membership on each exchange.
   A transfer out is not equivalent to delisting, and a new exchange membership
   is recorded independently.
4. `security_names`: effective-dated display names. Missing name history is an
   informational gap, not evidence that membership is absent.

All intervals use `[valid_from, valid_to)`: start is inclusive, end is exclusive,
and a null end means no end is recorded in that revision. For a date to be treated
as active, it must also fall inside the declared evidence coverage; an open interval
must not imply completeness beyond that coverage.

Each fact references evidence in the same immutable import revision. Evidence
records retain publisher, title, source URL, document date, access time, evidence
level, and an optional source-content SHA-256. Import coverage and warnings remain
explicit. Range overlap and alias uniqueness are import-validation responsibilities;
they cannot be inferred from a successful SQL insert.

The existing `universe_members` snapshots remain a compatibility/materialized read
model. This change does not alter scan or quote lookup behavior. No historical
identity is backfilled from ticker resemblance or current provider output. The
first observed BSE transfer/exit examples are evidence samples, not proof of full
coverage.

## Consequences

- Metadata schema v5 adds revisioned tables for security identities, aliases,
  names, exchange-membership intervals, and source evidence.
- The tables are an inert foundation until import, overlap validation, as-of
  projection, and coverage reporting are implemented.
- Existing snapshots and current scan eligibility remain unchanged. Historical
  research stays blocked while relevant exchange intervals or aliases are missing.
- A point-in-time universe projection must join membership, exchange-qualified
  alias, and (when available) effective name under one reference revision.

## Evidence Anchors

- BSE announced the 920-prefix code change effective 2025-10-09 in its
  [official notice](https://www.bse.cn/important_news/200026735.html).
- BSE's [official code mapping](https://www.bse.cn/service/code_mapping.html)
  explains that carried-over companies' displayed listing dates can refer to the
  former select layer rather than the start of BSE membership.
- Individually checked membership exits include [观典防务](https://www.bse.cn/disclosure/2022/2022-04-25/1650875588_282390.pdf),
  [泰祥股份](https://www.bse.cn/disclosure/2022/2022-07-15/1657874128_515467.pdf),
  [翰博高新](https://www.bse.cn/disclosure/2022/2022-07-22/1658483683_879987.pdf),
  [广道数字](https://www.bse.cn/disclosure/2025/2025-12-31/8690dbac1d5c42db98e9c7388e562129.pdf),
  and [南京云创](https://www.bse.cn/disclosure/2026/2026-07-29/8a64d7d9ca1641609307b4f2aa5fecaf.pdf).
  These examples are not a complete event inventory.
