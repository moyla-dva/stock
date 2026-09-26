---
status: accepted
decision_date: 2026-09-26
last_verified: 2026-09-27
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
5. SQLite schema v9 records a stable logical path plus active/archive physical identity. Source
   reconciliation treats active files and verified archive members as one immutable fact set and
   keeps content revision separate from storage revision.
6. Migration is staged and reversible: dry-run validation, archive registration while active files
   remain authoritative, atomic movement into quarantine, and restore. No purge/delete operation is
   provided.

## Consequences

- The archive format, detail reader, historical reader and round-trip verifier can be tested without
  changing production facts.
- A corrupt or incomplete archive fails closed instead of returning an unchecked detail.
- Archive copies consume temporary extra disk through the registration phase. Reclaiming active
  directory space requires every running reader to support schema v9 before a day enters quarantine.
- The 2026-05-15 real-data pilot archived one 3,819-byte snapshot into a 2,141-byte verified ZIP;
  schema v9 now records its exact ZIP/member/checksum while the source remains active. This proves
  the read and registration path, not the compression ratio of all days or readiness for bulk purge.
- Permanent deletion remains outside this decision. Quarantine retention and any future purge need
  a separate explicit policy and observation period.

## Rollback

Before quarantine, rollback is removal of the archive registration/copy while originals remain
authoritative. After quarantine, `--restore` atomically moves verified files back to the active
directory and reconciles manifest storage identity. No snapshot is reconstructed from SQLite.
