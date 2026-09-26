# Rejected Core Rewrite Spike

This directory preserves an unintegrated architecture experiment produced during
review. It is not imported by the application, covered by the production test
suite, or part of the current architecture roadmap.

The spike must not be moved back into `stock_analyzer/` without a new design and
parity review. Known blockers include:

- incorrect exchange inference for `920xxx` BSE securities;
- incompatible `date`/`trade_date` DataFrame adapters;
- missing OHLCV and array-shape validation;
- permissive Pydantic models that ignore unknown fields;
- fail-open gate behavior when a rule raises;
- an incomplete state model that cannot represent current risk and exit states;
- no tested two-way adapter for the current V2 facts contract.

The accepted direction remains incremental typing at stable boundaries and
one-fact-family-at-a-time migration, not a parallel replacement engine.
