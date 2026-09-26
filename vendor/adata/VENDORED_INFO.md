# AData Vendored Source

- Upstream: https://github.com/1nchaos/adata
- Snapshot commit: b14f4e57b2175302f18b6eaf934f7dff9207a141
- License: Apache-2.0, preserved in `LICENSE`
- Local modifications: none

This directory is a source snapshot used as a runtime fallback. `stock_analyzer.providers.adata_loader`
first imports `adata` from the active Python environment, then adds this directory to `sys.path`
and retries only when the package is missing. `adata` is not currently declared in `requirements.txt`,
so a clean environment uses this vendored snapshot. Keep the snapshot/license and loader behavior
in sync if the dependency strategy changes.
