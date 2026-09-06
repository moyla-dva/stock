# Development Roadmap

## Current Direction

The project is moving toward a local-first A-share mainline decision system. The default user question is:

"What is the market trading now, how mature is the mainline, how should I participate, and which stocks are usable or risky?"

The system combines:

- market mainlines and lifecycle stages
- sector/concept structure as evidence
- stock profile and concept graph relations
- local scan snapshots as candidate validation
- replay calibration and score confidence
- single-stock charts for final confirmation

## Execution Order

1. Project positioning and documentation
   - Done: README now describes the project as an A-share mainline decision system.
   - Done: design/refactor/data docs now treat scanning as validation, not the product goal.
   - Next: keep docs updated whenever product architecture changes materially.

2. Mainline-first page structure
   - Done: default workspace is "今日主线".
   - Done: mainline breakdown and candidate stock views are separate.
   - Done: 今日主线 now opens a dedicated breakdown instead of directly filtering candidates.
   - Done: 主线拆解 explains formation evidence, participation, risk, composition, and representative stocks.
   - Done: opening candidates from a mainline now keeps the full mainline scope, including clustered sector/concept child lines, instead of reducing the line to one raw board filter.
   - Next: keep the first-level UI focused on direction, breakdown, candidates, chart confirmation.

3. Mainline naming and clustering
   - Done: market lines now carry raw board names, user-facing display names, naming evidence, quality labels, and real filter targets separately.
   - Done: related raw sector/concept rows can be grouped into a market mainline cluster without losing the source board/concept.
   - Next: replace the first keyword-based cluster map with a structured concept graph and representative-stock evidence.

4. Stock profile evidence layer
   - Done: scan results now attach `profile_relations` with source, confidence, verification date, and evidence for cached industry/concept labels.
   - Done: profile relations are grouped into 主营行业、事件驱动、市场标签、弱关联, with a user-facing group summary.
   - Done: local verified evidence can be supplied through `.cache/catalog/stock_relation_evidence.json` and merged into scan results.
   - Done: local verified evidence can be queried, upserted, and deleted through `/api/profile_relations/evidence`.
   - Done: candidate detail now exposes a collapsed 画像校准 control for marking a relation as 主营相关、市场标签、事件驱动、弱关联, or 过期观察.
   - Done: market-structure rows now carry relation quality metrics, and mainline cards can show whether a line is 主营确认、事件驱动、市场标签, or weak/expired.
   - Done: market lines and the 主线拆解 panel now expose relation evidence counts for 主营、人工、事件、市场标签、弱关联, and 过期观察, so a mainline can explain whether it is business-supported or only label-supported.
   - Next: build tools to extract these verified evidence rows from company filings, announcements, and manual review.

5. Concept graph layer
   - Model upstream/downstream, same-theme, member-overlap, market-sync, and event-sync relations.
   - Use graph relations to connect different concepts into one mainline.
   - Use graph evidence to support defensive branches and downstream/upstream expansion.
   - Done: 主线拆解 includes a lightweight relation map from the current structured mainline row and a separate profile-relation evidence summary.
   - Done: local concept/sector graph edges now have a dedicated persistence layer in `stock_analyzer/concept_graph.py`, with `member_overlap` derived edges and `/api/concept_graph` query/write/delete APIs.
   - Done: data-source governance now tracks the local concept-graph cache as an explicit source.
   - Current: only `member_overlap` derivation is implemented automatically; upstream/downstream, event-sync, and stronger market-sync evidence still need structured sources.
   - Next: wire graph edges into mainline scoring and naming, so mainline construction reads graph truth directly instead of relying on the temporary keyword bridge.

6. Sector index dimension
   - Add market-level sector/index data instead of deriving sector strength only from selected candidates.
   - Compare candidate strength against the sector's own trend and breadth.

7. Data provider layer
   - Extract providers for stock list, history, concept, sector, and constituent data.
   - Keep scan logic independent from AkShare, AData, Eastmoney, THS, or CNInfo details.

8. Persistent task state
   - Persist scan and concept-refresh task records.
   - Make interrupted jobs explicit after service restart.
   - Done: scan jobs persist to local history, restart-interrupted jobs expose recovery hints.

9. Scan history browser
   - Browse historical scan batches.
   - Compare pools across dates.
   - Support replay and review workflows.
   - Done: right-side history tab can replay a snapshot day and show latest-rank deltas.

10. Score explanation
   - Explain final score as individual signal + sector resonance + concept resonance + risk penalties.
   - Keep explanations user-facing and concise.
   - Done: backend explanation includes score confidence from local replay/proxy samples.
   - Done: candidate confidence includes 5-day replay sample count, win rate, average return, and worst path metrics when available.
   - Done: candidate cards and details now show why the system places a stock into 优先跟踪, 修复观察, 风险验证, 支线备选, or 观察.

11. UI density pass
   - Move structure analysis into a stronger dedicated view if the right side becomes crowded.
   - Preserve the fast candidate-to-chart workflow.
   - Done: cache/strategy/concept governance is collapsed by default, with recovery actions still available.
   - Done: market candidate cards are slimmer and expose only the main concept and one-line decision summary.
   - Done: candidate results can switch between candidates, sector structure, and concept structure without leaving the workspace.

12. Cache governance
   - Done: local scan snapshot cache has status and expired/invalid pruning APIs.
   - Done: replaced legacy-strategy snapshots are counted separately and can be cleaned without deleting current snapshots.

13. Data source observability
   - Done: the app exposes one unified data-source status model for history cache, scan snapshots, concepts, profiles, board-market cache, scan jobs, and stock-list provider fallback.
   - Done: advanced settings can synchronize data-source, concept, and scan-cache governance status from one place.
   - Next: use the same status model to drive user-facing recovery prompts when a cache is empty, stale, or provider-only.

14. Real market breadth
   - Done: sector/concept width can use cached constituent histories, not only candidate density.
   - Current meaning: width describes how many local constituent samples are rising and standing above MA20.
   - Next: expand this into dedicated board pages once board constituents are complete enough.

15. Strategy research workspace
   - Done: replay research is separated from calibration in the side panel.
   - Calibration answers "is this score bucket healthy"; research answers "how did this bucket perform after 3/5/10 days".

16. Task queue governance
   - Done: duplicate active scans for the same pool and scope are reused instead of silently queueing another job.
   - Next: add queue-level pause/retry controls only if real usage shows repeated interruptions.

17. Module boundary cleanup
   - Done: scan side views were split from `scanFilters.js` into dedicated structure, calibration, and research view modules.
   - Done: scan workspace state writes were split from rendering into `scanWorkspaceStore.js`.
   - Done: scan workspace snapshot loading was split into `scan_workspace_loader.py`.
   - Done: Flask route bodies were moved into domain handlers under `stock_analyzer/web/`.
   - Done: `scan_workspace.py` now delegates structure enrichment, history comparison, and response shaping to dedicated modules.
   - Next: split scoring internals further only when a new strategy or new market dimension needs it.

18. Feature simplification
   - Done: added `docs/feature-simplification-audit.md` to classify core, supporting, hidden, and deprecation candidates.
   - Current rule: keep the mainline decision path focused; move refresh, replay, calibration, research, and governance into 数据与任务.
   - Next: remove unreachable legacy UI/code only after dependency checks.

19. Mainline quality and decision queue
   - Done: mainline rows expose quality score, quality label, quality reasons, participation mode, risk action, and preferred candidate pool.
   - Done: candidate results are grouped into system decision queues: 优先跟踪, 修复观察, 风险验证, 支线备选, 观察.
   - Done: mainline risk profile now distinguishes 风险可控, 局部分歧, and 风险扩散, with a direct jump into risk validation candidates.
   - Next: tune queue rules against real daily review samples instead of adding more manual sort controls.

20. AI assistance boundary
   - Done: AI is documented as an optional summarization layer, not a decision engine.
   - Rule: AI may summarize structured evidence, normalize events, and propose names, but provider data, graph relations, score/replay results, and candidate pools remain the source of truth.
