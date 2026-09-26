---
status: current
contract_version: 1
last_verified: 2026-09-23
implementation_status: importer-projection-and-audit-available
owners: local-user
supersedes: []
---

# Security Reference Model

## Purpose

Represent which listed instrument a record refers to independently from the code,
name, or exchange currently used to identify it. The rationale and choices are in
[ADR-0003](../adr/0003-effective-dated-security-identity.md).

## Identity Rules

- `security_id` identifies one listed share-class instrument, not its issuer.
- Never generate or recover `security_id` by treating a current code or name as
  permanent identity.
- A code is scoped by exchange and effective interval. Resolve it using
  `(exchange, code, as_of, reference_revision)`.
- Exchange membership is a separate interval. A transfer closes one membership
  interval and opens another; it does not itself assert that the instrument was
  delisted.
- Use `[valid_from, valid_to)` intervals. The start is inclusive, the end is
  exclusive, and null `valid_to` means no end is recorded.
- A null end is only usable through the evidence coverage end. It does not prove
  membership after the revision's declared coverage.
- Conflicting or insufficient evidence stays unresolved and blocks historical
  eligibility; do not guess continuity from similar names or codes.

## SQLite v5 Foundation

The independent reference revision consists of:

| Table | Fact |
| --- | --- |
| `security_reference_imports` / `security_reference_heads` | Immutable import metadata, coverage and selected revision per dataset |
| `security_entities` | Stable instrument identifiers within a revision |
| `security_aliases` | Exchange-qualified code intervals |
| `security_names` | Effective-dated display names |
| `exchange_memberships` | Effective-dated membership and entry/exit reason |
| `security_reference_evidence` | Publisher, document, URL, dates, evidence level and optional content hash |

Every fact references the import revision; interval starts and ends cite evidence
independently, because a code change or membership exit commonly has a different
source from the opening event. The document's `coverage` object must include
`coverage_start` and `coverage_end`; nested coverage entries describe known gaps
and their impact.

The importer validates identifiers, evidence references, date ordering, interval
overlaps, and that every code alias sits within a matching exchange-membership
interval. The coverage audit additionally detects alias gaps across membership
periods. A point-in-time query is only available inside the declared coverage
window; it returns unresolved aliases and missing names explicitly.

Import either a normalized JSON document or a directory containing `manifest.json`,
`securities.csv`, `evidence.csv`, `aliases.csv`, and `memberships.csv`; `names.csv` is
optional. JSON is the canonical format and each CSV must use the model's field names.

## Compatibility and Status

Schema v5 is additive. `universe_members` stays the existing snapshot format and
continues to serve current reports; scanning and quote lookup do not read the new
tables. No rows are automatically synthesized from existing code-based snapshots.

The official exchange evidence sample is stored at
`stock_analyzer/reference_data/bse_membership_sample.json`. It contains five
verified BSE exit intervals, two BSE old/new code transitions, and three verified
BSE-to-SSE/SZSE destination intervals. It is explicitly `partial`; it is not a
complete exchange history and does not include a full historical security-name
series. Historical research must not be described as
survivor-bias-free until the full universe and evidence coverage are independently
established.

The evidence sample distinguishes opening-day new offerings from Select Layer
carryovers: Guangdao High-Tech is recorded as a new public offering based on its
BSE-hosted listing notice, rather than inferred from the later code-mapping page.

```bash
./venv/bin/python scripts/import_market_metadata.py security-reference \
  --input stock_analyzer/reference_data/bse_membership_sample.json
./venv/bin/python scripts/audit_security_reference.py \
  --dataset-id A_SHARE_HISTORY --as-of 2021-11-22
```
