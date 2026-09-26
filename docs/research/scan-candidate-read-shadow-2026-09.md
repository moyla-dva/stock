---
status: exploratory
strategy_version: "2026.09.09.2 / 2026.09.20.1"
data_window: "2026-09-15, 2026-09-17, 2026-09-18, 2026-09-21, 2026-09-22 snapshots; filtered comparison run 2026-09-23 on the 2026-09-22 snapshot"
universe: "Persisted scan snapshot candidates; not a fresh live-universe audit"
entry_model: "not applicable"
data_revision: "Existing indexed snapshots; see per-day strategy version"
evidence_level: "local integration shadow comparison"
supersedes: []
---

# SQLite Candidate Read Shadow Comparison

## Question

Can the SQLite candidate read API replace the existing JSON-backed workspace read without
changing which candidates appear or the decision-relevant candidate fields? This check does
not decide which ranking should own the first screen.

## Method

Ran `scripts/compare_scan_candidate_reads.py` against the local Flask test client, comparing the
JSON-backed `/api/scan_workspace/candidates?lite=1` endpoint with
`/api/scan_index/candidates` for all three pools on five persisted snapshot dates. Every page was
retrieved with a 1,000-item page size until exhaustion. The hard gate checked candidate membership,
decision and descriptive fields, reported counts, filter metadata, offsets, `has_more`, and complete
pagination. No non-empty search, sector, concept, or reason filter was supplied.

The first run exposed a historical API issue: an explicitly selected date still defaulted to the
current strategy version and omitted older-version snapshots. The index endpoint now reads all
strategy versions present on an explicitly selected historical date; an unqualified latest read
continues to default to the current strategy. The comparison was rerun after that change.

## Results

| Snapshot day | Strategy version | Opportunity | Risk | Bottom-divergence | Total |
| --- | --- | ---: | ---: | ---: | ---: |
| 2026-09-15 | `2026.09.09.2` | 2,400 | 2,154 | 774 | 5,328 |
| 2026-09-17 | `2026.09.09.2` | 2,162 | 1,177 | 936 | 4,275 |
| 2026-09-18 | `2026.09.20.1` | 2,288 | 1,047 | 972 | 4,307 |
| 2026-09-21 | `2026.09.20.1` | 2,456 | 785 | 893 | 4,134 |
| 2026-09-22 | `2026.09.20.1` | 2,396 | 929 | 716 | 4,041 |
| **Total** |  | **11,702** | **6,092** | **4,291** | **22,085** |

All 15 date/pool comparisons passed the hard contract gate: candidate membership, decision and
descriptive fields, reported counts, and pagination matched. No missing or extra candidates were
reported. This is good evidence that the current read models can preserve candidate semantics for
these stored snapshots.

Ranking did not match in any of the 15 comparisons. As an illustrative latest-day example, the
workspace and SQLite opportunity lists shared only 2 of their respective top 20 candidates; the
bottom-divergence lists shared 1 of 20. The two orderings therefore cannot be treated as
implementation-equivalent. The difference is expected to reflect distinct scoring ownership and
is a product decision, not a pagination defect.

The run was a correctness-oriented shadow check, not a controlled performance benchmark. Cold and
warm cache state, filesystem behavior, and rank-context materialization were not held constant, so
timings must not be used as a performance claim.

## Historical Contextual-Mode Probe (2026-09-24)

Reran the same five dates and 15 pool/date combinations with `--rank-mode contextual`. All 15
`read_contract_gate_pass` values remained true: membership, fields, counts, filters, and pagination
still matched. However, every explicit historical-date request reported the applied ranking mode as
`snapshot_local`, not `contextual`; consequently the script's overall hard gate was false because
the requested mode was not applied. The reported order metrics therefore do **not** compare
contextual ranking against the workspace order. Historical contextual ranking remains unavailable
for these requests and must not be inferred from this run.

## Non-empty Filter Checks

On 2026-09-23, reran the local comparison against the persisted 2026-09-22 snapshot using non-empty
filters. All eight tested pool/filter combinations passed the hard read-contract gate: no missing or
extra candidates, hard-field or descriptive-field mismatches, count differences, or pagination
differences were found.

| Filter | Pool | Candidates in both reads |
| --- | --- | ---: |
| Sector `计算机、通信和其他电子设备制造业` | Opportunity / Risk / Bottom-divergence | 273 / 104 / 68 |
| Concept `DeepSeek概念` | Opportunity / Risk / Bottom-divergence | 278 / 123 / 119 |
| Search `000576` | Opportunity | 1 |
| Reason `plan_ready` | Opportunity | 68 |

The filtered checks do not change the ranking conclusion: the workspace and SQLite sort orders still
differ for multi-item results. The one-item search result naturally has identical ordering. These
checks use stored snapshots and a local Flask test client; they do not verify provider availability,
fresh-universe membership, or production API failure/degradation behavior. Those remain open gates.

Reproduction examples:

```bash
./venv/bin/python scripts/compare_scan_candidate_reads.py --snapshot-day 2026-09-22 --sector '计算机、通信和其他电子设备制造业' --summary-only
./venv/bin/python scripts/compare_scan_candidate_reads.py --snapshot-day 2026-09-22 --concept 'DeepSeek概念' --summary-only
./venv/bin/python scripts/compare_scan_candidate_reads.py --snapshot-day 2026-09-22 --pool opportunity --query '000576' --summary-only
./venv/bin/python scripts/compare_scan_candidate_reads.py --snapshot-day 2026-09-22 --pool opportunity --reason plan_ready --summary-only
```

## Decision And Limits

- Keep the SQLite candidate API opt-in. Do not switch the production frontend or default ranking.
- Preserve `snapshot_local` and `contextual` as separately named ranking modes; do not silently
  substitute one score for the other.
- Use the two UI prototypes to learn whether users need either ranking, both rankings, or a
  different candidate-first workflow before resolving ADR-0002.
- Continue shadow checks on actual production scan runs over multiple trading days before any read
  cutover. These five selected historical dates do not validate daily universe refresh, new listing
  inclusion, member removal, or live source availability.
- Non-empty sector, concept, search, and reason filters passed on the selected stored 2026-09-22
  snapshot; still add explicit API error/degradation scenarios and compare actual production scans
  across multiple trading days before treating the read contract as production-ready.

## Reproduction

```bash
./venv/bin/python scripts/compare_scan_candidate_reads.py \
  --snapshot-day 2026-09-15 \
  --snapshot-day 2026-09-17 \
  --snapshot-day 2026-09-18 \
  --snapshot-day 2026-09-21 \
  --snapshot-day 2026-09-22 \
  --summary-only
```
