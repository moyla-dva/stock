---
status: accepted
decision_date: 2026-09-26
last_verified: 2026-09-26
supersedes: []
---

# ADR-0006: Checksummed Snapshot Cold Archive

## Context

SQLite has replaced directory-wide JSON assembly for candidate lists, but 103,437 immutable JSON
snapshots still occupy about 3.36 GiB and remain the complete detail and reproduction facts. A
retention audit identified 19 older snapshot days, about 1.93 GiB, for archive review. Deleting
them merely because SQLite contains summaries would destroy facts needed by `CandidateDetail` and
historical replay.

## Decision

1. Cold storage uses one ZIP archive per snapshot day. `_manifest.json` records every original
   filename, member path, byte length and SHA-256 checksum together with minimal identity metadata.
2. Archive creation is atomic and verifies every member before success. It copies source files and
   never deletes them.
3. Snapshot reads prefer the active JSON path and fall back to the day archive only when that path
   is absent. Archived bytes must pass size and checksum validation before JSON decoding.
4. SQLite `CandidateDetail` and explicit historical-day replay use this read-through layer.
   Historical day listing is aggregated from the complete SQLite manifest rather than reopening all
   JSON files.
5. Source deletion remains disabled. Current SQLite source reconciliation treats the active source
   directory as the full membership set; removing originals now would invalidate source-sync.

## Consequences

- The archive format, detail reader, historical reader and round-trip verifier can be tested without
  changing production facts.
- A corrupt or incomplete archive fails closed instead of returning an unchecked detail.
- Archive copies consume temporary extra disk until an archive-aware SQLite storage-tier contract
  and reversible removal procedure are implemented.
- The 2026-05-15 real-data pilot archived one 3,819-byte snapshot into a 2,141-byte verified ZIP;
  the source remained in place. This proves the path, not the compression ratio of all days.

## Rollback

Because originals remain authoritative, rollback is removal of the archive copy and restoration of
the previous reader. No SQLite data or source snapshot must be reconstructed for this phase.
