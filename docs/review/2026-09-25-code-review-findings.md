---
status: working-document
doc_type: code-review-handoff
created: 2026-09-25
last_verified: 2026-09-25
review_scope: 全部未提交改动（91 个修改/删除文件 + 51 个新增未跟踪文件）
test_baseline: ./venv/bin/python -m unittest discover -s tests → 402 tests OK（本机含 node，实测 19.5s）
purpose: 供其他 agent 逐条独立复核。每条给出位置、证据、复核要点与验证状态；复核者只需对每条给出「确认 / 推翻（附证据）/ 行号漂移修正」。
not_a_contract: 本文件是临时工作文档，不是 docs/current/ 契约；修复完成后应归档或删除。
---

# 代码审查 Findings 交接文档（2026-09-25）

## 审查方法与可信度说明

- 后端核心（app.py、web/scan_api.py、web/stock_api.py、events.py、signal_registry.py、v2_facts_timeline.py、c_signal_v2_facts.py 新增段、normalizer、versioning、serializers、multi_timeframe、trade_plan、providers/stock_history.py 的 direct 列布局、data_fetcher 的 merge 段）由主审逐行阅读。
- 其余分区（前端、测试、扫描索引、市场元数据、读模型/排序、扫描工作区、数据层其余部分、信号/扫描核心）由 8 个并行逐行审查分区覆盖。
- **所有 P0 与 P1 均经主审亲手复核关键代码**；个别标注「代理报告」的子步骤（见各条验证状态）建议复核时重点重查。
- 全局一致性检查已做：`scan_market_context` / `scan_resonance_scoring` / `strategy.py` / `scripts/scan_batch*` 删除后全仓 grep 零残留引用。

严重级定义：P0=数据损坏/安全；P1=错误的许可语义、契约失效或必现功能缺陷；P2=很可能出错或健壮性缺口；P3=打磨。

---

## P0（1 条）

### P0-1 force_refresh 实时行情合并清零历史成交量并污染缓存

- **位置**：`stock_analyzer/data_fetcher.py:536-548`（merge 点）→ `stock_analyzer/providers/stock_quote.py:99-113`（`merge_quote_bar`）→ `stock_analyzer/normalizer.py:38-50`（列清洗）
- **触发链**（主审逐文件验证）：
  1. akshare 落后于目标日时走腾讯直连，帧列布局为 `[date, open, close, high, low, amount]`，**无 volume 列**，amount 实为成交量（`providers/stock_history.py:107` 附近 `frame.columns = [...]`）；
  2. `merge_quote_bar` 用 `pd.concat([frame, quote], sort=False)` 追加 quote bar（含 `volume` 列），合并帧历史行 volume=NaN；
  3. `normalizer.py:38` 分支条件 `"volume" not in df.columns` 不成立 → **跳过** amount→volume 改名；`normalizer.py:45` `df = df[PRICE_COLUMNS]` **丢弃 amount 列**；`normalizer.py:50` `fillna(0)` → **全部历史成交量 = 0**；
  4. `_should_write_history_cache` 在 15:10 后放行（`data_fetcher.py:292-293`），脏帧写入 canonical 日线缓存。
- **放大器**：前端 `static/js/app.js:303` `var forceRefresh = options.forceRefresh !== false;` 使回车/「开始分析」/切页初始分析全部带 `refresh=1` → P0 触发路径是单股页默认路径。
- **复核要点**：
  - `sed -n '100,112p' stock_analyzer/providers/stock_history.py` 确认 direct 帧列布局无 volume；
  - `sed -n '95,113p' stock_analyzer/providers/stock_quote.py` 确认 concat 行为；
  - `sed -n '36,54p' stock_analyzer/normalizer.py` 确认改名跳过与丢列顺序；
  - 复现：构造 `[date,open,close,high,low,amount]` 帧 + 一个带 volume 的 quote bar，走 `merge_quote_bar` + `normalize_price_frame`，断言历史行 volume 是否全为 0。
- **建议修复方向**：merge 前将 quote bar 归一到 canonical OHLCV（volume 单位与历史帧一致），或 direct 帧在 provider 层先补 volume 列；同时评估 `_should_write_history_cache` 对合并帧加 schema 完整性校验。
- **验证状态**：主审已验证 1-3 步与列布局；第 4 步（15:10 放行写缓存）为主审读码确认，建议复核时实际跑一次带 mock 的写入断言。

---

## P1（7 条）

### P1-1 `build_c_signal_v2_state_from_result` 的 is_breakout 集合漏 `v2_breakout`；保留 legacy `composite_breakout`

- **位置**：`stock_analyzer/c_signal_v2.py:1015`
  ```python
  is_breakout = signal_key in {"composite_breakout", "v2_bear_trap_recovery"}
  ```
- **触发路径**：`scan_snapshot.py:344-345` 在快照 result 缺 `v2_state_model` 时调用该函数回填。`signal_key="v2_breakout"`（当前 signal_registry.py opportunity 池合法 key）会得到 `state="entry_pullback"`、`permission="pullback_allowed"`；`market_permission._v2_state_entry_type` 据此把 entry_type 判成 `pullback`，宏观闸门按 MA60 回踩规则而非 MA250/周线突破规则判定。
- **兼容性说明**：`composite_breakout` 虽是旧 key，但 legacy 快照回填仍依赖其突破语义，不应在本修复中删除；见本文件第三轮对账。
- **复核要点**：`sed -n '1005,1030p' stock_analyzer/c_signal_v2.py`；`sed -n '340,352p' stock_analyzer/scan_snapshot.py`；确认 `tests/test_project_smoke.py` 只有 `composite_breakout` 用例、无 `v2_breakout` 用例（这是测试没抓到的原因）。
- **建议修复**：只将 `v2_breakout` 加入突破集合，保留 `composite_breakout` 和 `v2_bear_trap_recovery`；补 `v2_breakout` 与 legacy `composite_breakout` 回填用例。
- **验证状态**：主审已亲手验证代码与回填路径。

### P1-2 排序/许可策略变化与快照版本职责未明确（代码事实已确认，版本策略待决策）

- **位置**：`stock_analyzer/versioning.py:6`（`SCAN_STRATEGY_VERSION = "2026.09.20.1"`，本次 diff 未改动）；`stock_analyzer/scan_snapshot.py:205-210`（`is_current_strategy_snapshot` 严格相等判断）
- **语义变更内容**（本次 diff 内）：`c_signal_v2.py build_c_signal_v2_priority` 删除 sector_score/concept_score/replay 项；`market_permission.py` 删除概念/板块许可层；versioning 的 LABEL/NOTES 已改写。ADR-0002 决策日期 2026-09-25。
- **当前证据**：本批调整了排序公式及环境许可职责，但没有 bump `SCAN_STRATEGY_VERSION`。工作台响应链会在 `scan_workspace_response.py:47` 重算优先级/环境；`scan_snapshot.py:375-376` 仅对缺少 `v2_priority_score` 的快照补算。内嵌 `v2_state_model.permission` 仍被沿用，需确认本批是否改变其推导语义。新增 `bar_state/data_source/calendar_*` 等身份字段在旧快照中缺失，会令相关审计信息为 unknown。
- **版本边界**：SQLite RankContext 有独立 `RANKING_POLICY_VERSION`（`scan_rank_context.py:9`）。若 bump `SCAN_STRATEGY_VERSION`，既有快照会被整体标为 legacy；排序政策、扫描事实和数据身份/schema 的版本职责应分开评估，不能默认要求全量重扫。
- **复核要点**：确认工作台统一重算与 SQLite RankContext 的版本守卫；查明 `v2_state_model.permission` 推导语义是否改变；抽查旧快照身份字段缺失对审计/查询的实际影响；评估 bump scan strategy 与单独 bump ranking policy 的行为差异。
- **建议处置**：先明确版本职责，再决定是否 bump `SCAN_STRATEGY_VERSION`。如需 bump，制定旧快照 legacy 标记和派生索引定向回填方案；不把版本号变更自动等同于全量重扫。
- **验证状态**：代码事实已确认（五轮闭环）——版本号未变、工作台经 `apply_c_signal_v2_priority` 无条件重算排序/环境（`scan_workspace_response.py:47` → `c_signal_v2.py:1282-1286`）、`scan_snapshot.py:375-376` 仅缺分回填、内嵌 `v2_state_model.permission` 沿用且本批未改其推导语义，均已逐行核实（见第四轮终审第 3 条）。**待决策**：版本治理方案（是否 bump `SCAN_STRATEGY_VERSION`、重刷范围、与 `RANKING_POLICY_VERSION`/快照身份版本的职责划分）。

### P1-3 quote bar volume 单位（手）与 akshare 历史链路（股）相差 100 倍

- **位置**：`stock_analyzer/providers/stock_quote.py:62-80`（`volume = _number(fields[6])`，腾讯报价成交量单位为手，未 ×100）；`stock_analyzer/data_fetcher.py:538` 合并点
- **对照**：分区代理核对过 venv 内安装版 akshare `stock_zh_a_hist_tx` 源码含 `volume * 100` → 股。
- **后果**：即使历史帧来自 akshare 主路径（有规范 volume 列），合并日的量也比历史小 100 倍——放量日被判成极端缩量，影响量能类指标。
- **复核要点**：`python -c "import akshare, inspect; from akshare.stock_feature import stock_hist_tx; print(inspect.getsource(stock_hist_tx))" | grep -n "volume"` 核实 ×100；确认腾讯 qt.gtimg 报错字段 6 的单位口径（可用任一股票实时接口对照分时成交量）。
- **建议修复**：与 P0-1 同点修复——merge 前统一单位。
- **验证状态**：quote 字段与合并点主审已验证；akshare ×100 与腾讯「手」口径为代理核对 venv 源码，建议复核者重跑该命令确认。

### P1-4 BSE 拉取失败不阻塞，缺北交所的截断名单可进入生产扫描

- **位置**：`stock_analyzer/providers/market_reference.py:278-283`（BSE 子源无 `required=True`，对比上方 SZSE 块有）；`stock_analyzer/market_metadata_store.py:1655-1662`（`structural_valid` 不检查 coverage 缺口）；`stock_analyzer/current_universe.py:102-117`（`_read_eligible_snapshot` 只看 `current_scan_eligible`）
- **契约冲突**：`docs/current/market-reference-data.md:87-89` 明文「完整主名单源不可用时显式返回可重试错误，不退化成可能截断的次级名单」。
- **放大器**：`CurrentUniverseService` 每交易日至多刷新一次 → 早晨一次 BSE 网络抖动固化全天截断名单；`audit_current_universe_scan` 只对比 job 与快照一致性，不感知截断，仍报 consistent。
- **复核要点**：`sed -n '268,285p' stock_analyzer/providers/market_reference.py` 对比 SZSE/BSE 两块的 required 标志；`sed -n '1650,1670p' stock_analyzer/market_metadata_store.py` 确认 `current_scan_eligible`（structural_valid）不含 blocking_gaps 条件；确认 BSE 缺失时 coverage 会标 "unavailable" 但不影响 eligible。
- **建议修复**：BSE 标 `required=True`，或 `structural_valid` 加「SSE/SZSE/BSE 三所 coverage 不得为 unavailable」条件。
- **验证状态**：主审已亲手验证三处代码。

### P1-5 universe 覆盖审计的不完整状态集合缺 partial/unknown，historical 安全门可被穿透

- **位置**：`stock_analyzer/market_metadata_store.py:1643-1645`（universe 路径 `if status not in {"missing", "unavailable", "unreviewed"}: continue`）对比 `:296-318`（security-reference 路径的 `_coverage_gaps` 用 `{"missing","unavailable","unreviewed","partial","unknown"}`）
- **后果**：universe coverage 中 impact=membership 的组件若为 "partial"/"unknown"，不进 blocking_gaps → `historical_research_eligible` 可为 true → `scripts/audit_market_universe.py --require-historical-ready`（退出码 2 的安全门）失效。当前 provider 只产出 missing/unavailable，但 `import_market_metadata.py universe` 将输入文件 coverage JSON 原样入库，手工导入即可触发。
- **复核要点**：对比两处集合字面量；确认 `historical_research_eligible` 只检查 blocking_gaps（`:1663-1667`）；用一份含 `"status": "partial"` coverage 的 universe JSON 走 import → audit 复现。
- **建议修复**：两处合一为单一 `_coverage_gaps` 实现，集合取并集。
- **验证状态**：代理报告（引了两处代码原文），主审未逐行重读 ：1643 上下文，复核时确认即可。

### P1-6 scan_index v5→v6 迁移裸 ALTER 非幂等；首次初始化存在并发竞态

- **位置**：`stock_analyzer/scan_index_store.py:424-433`（`_migrate_v5_to_v6` 直接 `ALTER TABLE ... ADD COLUMN` ×2）；对比 `:262-270`（v1→v2）与 `:348-361`（v3→v4）都有 `PRAGMA table_info` 幂等检查；`:227-257`（`initialize()` 读 user_version 与迁移之间无 BEGIN IMMEDIATE/应用锁）
- **后果 A**：第一条 ALTER 提交后、`PRAGMA user_version=6` 写入前进程中断 → 重启后重跑迁移抛 `duplicate column name`，**每次初始化都失败**，索引库永久打不开（索引本身可弃可重建，故定 P1 而非 P0）。
- **后果 B**：Flask 多线程下两个并发首次初始化都通过列检查，后执行 ALTER 的一方崩溃；busy_timeout 解决不了 check-then-ALTER 竞态。
- **复核要点**：`sed -n '240,262p' stock_analyzer/scan_index_store.py`（迁移链）与 `sed -n '418,436p'`（v6 迁移体）；对照 v1→v2/v3→v4 的幂等写法；确认迁移是否在显式事务内（Python sqlite3 legacy 模式下 DDL 会隐式提交）。
- **建议修复**：v6 补 `table_info` 检查；`initialize()` 全程 `BEGIN IMMEDIATE` 或应用级锁。
- **验证状态**：主审已亲手验证 v6 无幂等检查及迁移链上下文。

### P1-7 历史快照 + SQLite opt-in 读链：contextual 排序因参数失配必然回退

- **位置**：`stock_analyzer/web/scan_api.py:461-467`（带 `snapshot_day` 且未显式传 `strategy_version` 时 `strategy_filter=None`）；`stock_analyzer/scan_index_store.py:1638` 附近（contextual 状态查询用 `strategy_version=str(strategy_version or "")` → 空串匹配不到任何物化行 → `available=False, reason="not_materialized"`）；`static/js/scanReadModelAdapter.js:129`（硬编码 `rank_mode=contextual` 不传 strategy_version）与 `:319-321`（`context_applied=false` 直接 throw）
- **后果**：开 `?candidate_source=sqlite` 后点击任何历史快照日必然失败并整体回退 JSON，状态栏显示「SQLite 读取不可用」，`fallback_reason` 误报 `not_materialized`（真实原因是查询端与物化端版本参数约定不一致：物化端用 `SCAN_STRATEGY_VERSION` 发布 snapshot scope）。
- **复核要点**：`sed -n '458,470p' stock_analyzer/web/scan_api.py`；grep `_rank_context_status_for_connection` 的 strategy_version 传参；`sed -n '125,135p'` 与 `sed -n '315,325p' static/js/scanReadModelAdapter.js`；确认物化端 `materialize_workspace_rank_context` 发布用的版本值（`app.py:176-186`）。
- **建议修复**：查询端 strategy_filter 为 None 时回填 `SCAN_STRATEGY_VERSION`（与 latest 模式一致），或前端透传物化版本。
- **验证状态**：scan_api 端逻辑主审读码确认；scan_index_store 与 JS 侧行号为分区代理提供，复核时对照行号。

---

## P2（18 条，按主题分组）

### 缓存与正确性

| ID | 位置 | 问题 | 复核要点 | 验证状态 |
|---|---|---|---|---|
| P2-1 | `stock_analyzer/events.py:432-440` | 事件缓存指纹只含行数+首行+末行哈希+总和，中间行对称变化会误命中返回过期事件 | 与 `v2_facts_timeline.py:42-50` 的逐行哈希实现对比；构造两行互换用例 | 主审读码确认 |
| P2-2 | `stock_analyzer/web/scan_api.py:386-414` vs `:192-219` | lite 工作台与 /candidates 共享同一缓存键但 factory 参数不同（`include_history_comparison=False` 仅 candidates 传），历史快照模式下先到者决定缓存内容 | 键参数逐项对比 `scan_workspace_cache.py` 的 key 组装；确认 include_history_comparison 仅在 snapshot_day 非空时生效（`scan_workspace.py:56`） | 主审验证 |
| P2-3 | `stock_analyzer/candidate_read_model.py:172` | `int(snapshot.get("version") or 0)` 裸转，损坏快照可使 `index_snapshot_files` 中断并令 completion hook 的 postprocess 标 failed；job 主状态仍为 completed，已提交批次可能已部分入索引 | per-pool 循环是否在文件级 try 内（`scan_index_store.py:1062-1072`）；索引批次提交点（`:477-506`）；`app.py:173` 的 hook 调用范围 | 已复核：后处理失败成立；“job 被标 failed/全部快照未索引”不成立或未证实 |
| P2-4 | `stock_analyzer/candidate_read_model.py:31-39` | `_number` 不拦 NaN/Inf/bool；NaN 绑定 SQLite 变 NULL 静默排序到队尾 | 对比 `candidate_ranking_v1.py:41-48` 的 isfinite；实测 `sqlite3` 绑定 NaN 行为 | 代理报告（含实测） |
| P2-5 | `stock_analyzer/scan_rank_context.py:26-27` | 版本守卫 `if result_strategy and ...` 对缺失版本反向放行 | 当前唯一调用链 `scan_workspace_loader.py:196` 恒写 `or "legacy"`，故未爆；新调用点风险 | 代理报告 |
| P2-6 | `stock_analyzer/candidate_reasons.py:86-87,149` | 未知 reason 从「全通过」反转为「全过滤」，与前端 `scanFilters.js:188`（return true）不一致 | 对比新旧实现（git diff）；前后端行为差异 | 代理报告 |
| P2-7 | `stock_analyzer/providers/stock_history.py:205-211` | direct 按年拉取单年失败时用残缺帧整体替换 akshare 完整帧，缺年可入库 | `:79-86` 单年异常仅 continue；替换点无缺口检测 | 代理报告 |
| P2-8 | `stock_analyzer/data_fetcher.py:336-341,362-366,533-535` | stale 诊断死代码（命中即 return None，后续 diagnostics.update 不可达）→ `stale_cache_count` 统计失真；连带无日历数据时工作日节假日盘后每请求全量拉取 | `sed -n '330,370p'`；`_current_day_cache_is_stale` 的 `session_status is None and weekday>=5` 分支（`:260,290`） | 代理报告 |
| P2-9 | `stock_analyzer/data_fetcher.py:518-548` | 运行时合并无 qfq/跳变护栏；docs/data-operations.md:105 的校验只在离线 append 脚本（`scripts/append_daily_quotes_to_history_cache.py:122-144`） | 对照文档措辞与运行时路径；确认文档是否需要补边界声明 | 代理报告 |

### 性能

| ID | 位置 | 问题 | 复核要点 | 验证状态 |
|---|---|---|---|---|
| P2-10 | `stock_analyzer/scan_workspace_persistent_cache.py:267` | `_prune_response_cache` 每次写缓存全目录 glob+stat；一次 lite miss 写 3 文件 = 3 次全扫 | `sed -n '180,200p'` 与调用点；建议节流（模块级时间戳） | 主审验证 |
| P2-11 | `stock_analyzer/web/scan_api.py:276-292` | 每个 detail 请求 O(全市场) 重建 profile relation cache，实际只用一个 code | `build_profile_relation_cache`（profile_relations.py:408-424）的成本；`_direct_candidate_detail_payload` 调用频次 | 代理报告 |
| P2-12 | `stock_analyzer/web/scan_api.py:241-252` | 为各池建立 compact 缓存时会反复遍历 workspace 的 pool 元数据；每次只 compact 一个 active pool 的结果，结果列表不会按 `pools² × results` 重复 compact | `compact_workspace_response`（`scan_workspace_response.py:419-435`）及各池缓存写入循环；优先量化元数据遍历成本 | 复杂度原结论已撤回；低优先级待量化 |
| P2-13 | `stock_analyzer/current_universe.py:119-133` | 单例锁内执行公网请求（消费者串行阻塞）；`_resolve_session`/`_read_eligible_snapshot` 在 try 外裸抛，绕过 503 retryable 通道 | `web/stock_api.py:39-43` 只映射 StockUniverseUnavailable；锁内 loader 调用链 | 代理报告 |

### 前端

| ID | 位置 | 问题 | 复核要点 | 验证状态 |
|---|---|---|---|---|
| P2-14 | `static/js/scanJobs.js:323-338` | 轮询 catch 缺少 stale-request 守卫：旧任务 A 的在途请求若在新任务 B 已设为 active 后失败，会落入失败分支并清空 B 的状态 | 对照成功路径 `:305` 的守卫；`scanMarket` 的 `clearScanJobPoll()` 不会取消已发出的请求 | 独立复核确认；前次“已失效”判断有误，第三轮已纠正 |
| P2-15 | `static/js/api.js:161-162`、`scanJobs.js:234-235` | `readSourceOverride='json'` 全会话粘滞无重置路径，索引恢复后 opt-in 读链不再尝试 | 全仓 grep 该变量赋值点，确认无置空路径 | 代理报告 |
| P2-16 | `static/js/api.js:219-226` | SQLite 详情 404/409 被吞成重量级 JSON 全量重查；`scanJobs.js:324` 忽略 `err.retryable` | `buildHttpError`（api.js:30-58）已解析 retryable；后端 404/409 语义 | 代理报告 |
| P2-17 | `static/js/app.js:303` | `forceRefresh !== false` 使回车/开始分析/切页初始分析全部带 refresh=1，缓存对单股分析失效（与 P0-1 触发路径重叠） | `app.js:241,275,283,401` 各调用点；implementation-status.md「请求最新行情」确认产品意图 | 主审验证（行为变更属产品决策，需确认是否保留） |
| P2-18 | `tests/test_frontend_analysis_store.py:12-14,17-22` | 32 个 node 测试无 node 时静默 skip；`subprocess.run` 无 timeout 可挂死套件 | `shutil.which("node")` 分支；建议 CI 断言 node 存在 + timeout=30 | 代理报告（本机复跑 402 OK 含 node） |

### 测试守护死代码（P2 附加）

| ID | 位置 | 问题 |
|---|---|---|
| P2-19 | `tests/test_market_breadth.py` 全文件、`tests/test_scan_workspace.py:778`、`tests/test_project_smoke.py:2904` | 约 5 个测试守护生产代码零引用的死模块（market_breadth.py、resonance_calibration.py、board_market_refresh.py）；grep 确认无 import。删模块或删测试二选一 |
| P2-20 | `tests/test_scan_workspace.py:286`、`tests/test_project_smoke.py:3192-3194` | 断言 `include_market_universe/include_market_breadth` 透传，但 `build_workspace_structure` 函数体已不使用这些参数——契约在测、实现已架空 |

---

## P3（打磨级，14 条摘选）

| ID | 位置 | 问题 |
|---|---|---|
| P3-1 | 多文件（providers/concepts.py:128、catalog_concepts.py:79/125、catalog_cache.py:38/58/84/100、concept_graph.py:263、market_boards.py:125、profile_relations.py:135 等） | 运营可见错误从 print 降为 LOGGER.debug，app.py 只配 INFO → 降级链失败默认不可见；建议 warning 级 |
| P3-2 | `stock_analyzer/scan_confidence.py:9-14` | 置信度两档且与样本量脱钩；replay_5d_* 字段保留但全 0/None（假数据形状） |
| P3-3 | `stock_analyzer/market_permission.py:137-158` | bottom_div 候选宏观通过时 `v2_environment_effect="allow"` 与「不授予入场许可」语义摩擦（effective_permission 确为 watch_only，结论成立） |
| P3-4 | `stock_analyzer/events.py`（SIGNAL_DEFINITIONS / c_signal_v2_contracts.py V2_SIGNAL_CONTRACTS / signal_registry.py） | 三处契约无一致性校验器；`v2_bear_trap_recovery` order=15 与 v2_breakout 重复，`(date, order)` 并列时叠放不稳 |
| P3-5 | `stock_analyzer/scan_index_store.py:127-134,610-635,860-913` | 缺 `(snapshot_day, strategy_version, start_key)` 复合索引，contextual 热路径多次全扫 5.4 万行；`:450-507` 增量索引只增不减，删除快照残留 manifest；`:1489-1501` 两 rank 模式 code tie-break 方向相反；`:1390` LIKE 未转义 %/_ |
| P3-6 | `stock_analyzer/single_stock_read_model.py:76-83,28` | 默认单票入口 `from_payload` 不防 payload 非 Mapping（外层有 503 兜底）；`_data_revision` 的 json.dumps 无 default=str |
| P3-7 | `stock_analyzer/candidate_ranking_v1.py:155-167,185-197` | environment_forbidden 提前 return 丢弃已收集 reasons（与「风险原因始终可见」设计要求冲突）；`:375-376` `list(字符串)` 拆单字符风险 |
| P3-8 | `stock_analyzer/scan_workspace_structure.py`、`scan_workspace.py`、`web/scan_api.py` | **已修复（2026-09-26，批次 5）**：移除结构构建和工作区收集中的无效参数、透传与 `include_replay` 缓存维度；HTTP 查询仍可携带该历史参数，但回放保持 disabled。保留仍会进入响应元数据的 `replay_entry_model`。 |
| P3-9 | `stock_analyzer/scan_overview.py`、`scan_resonance.py`、`scan_workspace_persistent_cache.py` | **已修复（2026-09-26，批次 5）**：删除无消费者的市场宽度计算链与 facade，以及失去调用者的 `_directory_stat`；候选分布统计仍由 `scan_overview` 的活跃函数提供。 |
| P3-10 | `static/js/scanSelectionDetail.js:539`、`static/js/scanExplain.js:33-52`、`static/js/app.js:1`、`static/js/scanSelection.js:26` | sector_risk_count 永远 '-'；composite_* 死分支；signalMode='composite' 旧命名 |
| P3-11 | `stock_analyzer/scan_jobs.py` | **已复核并修复（2026-09-26，批次 7）**：取消路径会收录取消检查时已完成但尚未处理的 future；历史保留策略不再驱逐活动任务。完成钩子仍在 job 生命周期内同步执行并先于 completed 终态，失败单独记录在 postprocess，不认定为缺陷。 |
| P3-12 | `stock_analyzer/data_fetcher.py` | **已复核并修复（2026-09-26，批次 6）**：`generated_at` 按当前契约表示本次分析请求时间，缓存持久化时间单独记录在 `cache_written_at`，原 finding 此部分撤回；CSV 与 sidecar 虽分别原子替换但不是成对事务，新写缓存现带 `cache_payload_revision`，读取时校验内容与 sidecar 一致，旧缓存无该字段仍兼容；移除未使用的 `market_symbol_for_tx` 再导入，并将测试改为从 provider 所属模块导入。 |
| P3-13 | `stock_analyzer/v2_facts_timeline.py:47-50` | 列重命名（值不变）不触发前缀失效——hash_pandas_object 不含列名；同文件 mix-builder 隐式契约（full facts 与 event facts 在事件消费键上等价）无测试守护，建议补等价性测试 |
| P3-14 | `stock_analyzer/scan_workspace_history_compare.py:14-15,57-64,111-124` | **已修复（2026-09-26，批次 4）**：历史比较参考日池与当前工作台统一按 `strategy_status`、重算后的 `v2_priority_score` 排序；原问题为参考日使用 `final_score`/`rank_score`、当前列表使用 `v2_priority_score`，导致 `rank_delta` 口径不一致。新增两种分数顺序相反的回归用例。 |

## 文档层 findings（供文档复核 agent）

| ID | 位置 | 问题 |
|---|---|---|
| D-1 | `docs/current/implementation-status.md:30,49`（378 tests）、`AGENT_SYNC.md` 末段（266 tests） | 测试计数漂移，实际 402；三处应随收口统一 |
| D-2 | `docs/current/market-reference-data.md:87-89` vs P1-4 | 文档承诺「完整主名单源不可用→显式可重试错误」，BSE 子源实现不满足 |
| D-3 | `docs/data-operations.md:105`（qfq 漂移护栏） | 护栏只存在于离线 append 脚本；运行时 force_refresh 合并路径无校验（P2-9），建议补边界声明 |
| D-4 | `tests/test_market_permission.py`（原 `tests/test_scan_market_context.py`） | **已修复（2026-09-26，批次 4）**：测试文件改为与当前测试主题一致的名称；全仓代码引用已核对。 |
| D-5 | `docs/data-operations.md` 新增 Market Reference 一节 | **已撤回：原结论错误。**`docs/README.md` 已收录 `market-reference-data.md` 与 `data-operations.md`，无需重复加索引 |

## 已核对无问题项（复核 agent 不必重查）

- 全局残留：`scan_market_context` / `scan_resonance_scoring` / `strategy.py` / 退役脚本删除后全仓 grep 零残留引用（主审验证）。
- XSS：static/js 全量 grep，innerHTML 仅用于清空，动态数据全 textContent，ECharts tooltip 经 `escapeChartTooltipHtml` 转义（前端分区逐文件验证）。
- reason alias 前后端一致：`scanFilters.js:42-46` 与 `signal_registry.py:80-92` 逐项一致；14 个 reason tag 与 `candidate_reasons.py:10-25` 一致。
- 单票读模型字段映射：`singleStockReadModelAdapter.js` 与 `SingleStockAnalysis.from_payload` 逐字段核对一致（含 k_data 四元组顺序、schema_version=2）。
- `signal_registry` 单源：全仓无第二处硬编码三池/权重；`v2_bear_trap_recovery` 在定义/契约/权重/发射/许可五环节闭环（信号分区逐环节验证）。
- `market_permission` 重写：sector/concept 降 not_used，宏观判定唯一实现 `evaluate_macro_entry_blocks`；bottom_div 的 `effective_permission=watch_only` 结论成立（入场确实被拦）。
- 缓存写路径：`write_cached_history` tmp+replace、pid+uuid 命名正确；`_json_safe` 拦 NaN/Infinity；`compact_workspace_response` 新建 pool dict，lite 截断不污染缓存（主审验证）。
- `v2_facts_timeline` 前缀复用边界正确（`idx < common_length` 与 facts@idx 依赖行 0..idx 对齐）（信号分区验证）。
- 事件 facts profile 覆盖事件层全部读取键（主审逐键对照 events.py 的 facts.get 清单）。
- completion hook 异常兜底（`scan_jobs.py:433-453`）、`_json_key`/fingerprint 结构、409 revision 校验、sqlite-scan-index.md 文档与实现一致（索引分区验证）。

## 复核建议流程

1. 每条 P0/P1 独立复核：先按「复核要点」的命令读码，再判断结论是否成立；行号如有漂移以当前工作区为准并回填修正。
2. P2/P3 抽查即可；本轮重点复核 P2-3 的索引部分提交边界、P2-14 的过期轮询竞态，以及 P1-2 的版本职责与旧快照影响。
3. 复现类验证（P0-1、P1-5）建议写临时脚本在 /tmp 运行，不要在工作区落盘。
4. 复核产出格式建议：`[ID] 确认/推翻/部分成立 — 证据(file:line) — 补充说明`。
5. 全部复核完成后本文件应更新验证状态列，随后按修复批次消费；修复后删除或移入 docs/archive/。

---

## 独立复核结果（2026-09-25）

本节是对上述 findings 的独立代码复核与最小复现实验，不覆盖或改写代理原结论。复核时工作区测试基线为 **402 tests OK**（`./venv/bin/python -m unittest discover -s tests`，全程离线）。本次只更新 review 文档，没有修改生产代码。

### P0 / P1 复核

| ID | 结论 | 复核证据与修订 |
|---|---|---|
| P0-1 | 确认 | 历史帧只有 `amount` 成交量列，腾讯行情 bar 使用 `volume`；合并后历史行的 `volume` 为 NaN，归一化会把它填成 0。缓存写入路径可能将此结果持久化。问题成立，影响历史成交量及依赖它的分析。 |
| P1-1 | 确认，修复建议需收窄 | `build_c_signal_v2_state_from_result` 将 `composite_breakout` 和 `v2_bear_trap_recovery` 识别为突破，却漏掉 `v2_breakout`；最小调用复现得到 `entry_pullback`/`pullback_allowed`。建议补 `v2_breakout`，但保留 `composite_breakout`：`legacy_c_signal_adapter.py` 仍承担历史快照兼容，不能仅凭当前排序路径不可达就删除兼容键。 |
| P1-2 | 部分成立，版本治理方案待复核 | 工作台在 `scan_workspace_response.py:47` 对加载结果重新计算当前优先级/环境；`scan_snapshot.py:375-376` 仅在快照缺少 `v2_priority_score` 时回填，不能描述为每次都会重算。旧 state permission 仍来自快照，需确认本次变更是否改变其推导语义。旧快照缺少新加的数据身份字段会使对应统计呈 unknown。排名策略已有独立版本；若 bump `SCAN_STRATEGY_VERSION`，旧快照会整体标记 legacy，因此应评估单独版本化排名政策/快照身份字段，避免无必要全量重扫。 |
| P1-3 | 确认 | 腾讯行情接口原始成交量与历史成交量单位不一致，且行情 bar 未换算。用 2026-09-24 的 600000 报价核对，`amount / (close * volume) ≈ 100`，支持原始值以“手”表示、规范值应按股票类别转换为“股”的判断。与下方新增历史成交量单位问题是同一类 provider 边界缺陷，应统一治理。 |
| P1-4 | 确认 | mock SSE/SZSE 名单可用、BSE 返回空名单时，整体结果仍可标记 `current_scan_eligible=true`。必需交易所名单缺失不应静默放行全市场扫描。 |
| P1-5 | 确认 | 临时 SQLite 复现：外层覆盖状态为 `complete`，内部 BSE membership 为 `partial` 时，导入结果仍标记当前扫描及历史研究均可用，且没有 blocking gap。覆盖状态聚合应纳入 `partial`/`unknown`。 |
| P1-6 | 确认，建议降为 P2 | 模拟迁移中 ALTER 已成功但 `user_version` 未推进，再次执行迁移会因重复列失败。缺陷真实，但受中断迁移触发且索引可重建，破坏性低于一般 P1 数据正确性问题；需补幂等迁移或列存在检查，并调整优先级。 |
| P1-7 | 确认，建议降为 P2 | 本地历史候选 API 不带 `strategy_version` 时返回 `context_applied=false`、`fallback_reason=not_materialized`；显式传当前版本可成功。前端当前会退回 JSON，因此属于 SQLite 历史读取降级，不是页面完全不可用。 |

### 新增发现：腾讯历史成交量单位未规范化

除了 P0-1 的历史/实时合并列名不一致，历史直连接口自身也有单位风险：腾讯历史数据 raw field 5 被 `stock_history.py` 标为 `amount`，随后 `normalize_price_frame` 仅把 `amount` 重命名为 `volume`，没有单位换算。对普通股票，该接口字段按“手”返回，而项目其余分析使用“股”；AkShare 对同一腾讯字段按股票类别乘以 100（科创板等类别另行处理）。因此直接历史数据路径即使没有发生 P0-1 合并，也可能把成交量低估约 100 倍。建议在 provider 边界明确字段名称和单位，并按证券类别转为统一单位；不要在通用 normalizer 中对所有来源无条件乘 100。

涉及位置：`stock_analyzer/providers/stock_history.py`、`stock_analyzer/providers/stock_quote.py`、`stock_analyzer/normalizer.py`、`stock_analyzer/data_fetcher.py`。该发现与 P0-1/P1-3 同属成交量契约问题，但触发路径不同，修复后应分别覆盖纯历史、纯实时、历史加实时合并三类输入。

### P2 复核与优先级修订

| ID | 结论 | 说明 |
|---|---|---|
| P2-1、P2-2、P2-4 | 确认 | 分别是事件指纹存在碰撞可能、同缓存键对应不同 factory 语义、数值读模型允许 NaN/Infinity。建议补针对性测试。 |
| P2-3 | 部分成立 | 非法快照版本可使索引/后处理失败；completion hook 会把 `postprocess.status` 标为 failed，扫描 job 本身仍是 completed。索引按批提交，异常后可能部分完成，不能断言该 job 的快照全部未进索引。 |
| P2-5 | 潜在风险，当前路径有保护 | 快照加载器会回退到 `legacy` 策略版本，尚未复现当前调用链因此误分组；保留防御性验证即可，不应按已发生故障描述。 |
| P2-6、P2-7、P2-8、P2-9、P2-10、P2-11、P2-13、P2-16 | 基本确认 | 代码路径支持原报告。P2-9 属于运行时数据源/复权口径条件触发的风险，建议先明确哪些 provider 会走该路径再定修复范围。 |
| P2-12 | 部分成立，复杂度表述夸大 | `scan_api.py:241-252` 为各池写 compact 缓存时重复遍历 pool 元数据；每个池的候选结果只在其对应缓存构建中 compact。更准确的量级是元数据遍历约 `O(P²)`、结果处理约 `O(ΣRᵢ)`，而非 `O(P² × results)`；建议量化后再决定优化。 |
| P2-14 | 确认；前次复核判断错误 | 相等判断仅保护 catch 内的重试分支；旧任务请求在新任务 ID 已写入后失败时，条件为假并继续执行清理分支，可能清空新任务。应在 catch 开头先判断 `activeScanJobId !== polledJobId` 并直接 return。 |
| P2-15 | 代码行为确认，产品语义待定 | `readSourceOverride='json'` 会在会话内保持；这是故障后的降级记忆，可能是有意的 circuit breaker。应明确恢复/重试入口，不宜直接定性为缺陷。 |
| P2-17 | 非缺陷，属产品行为 | 默认 force refresh 与“进入单股分析时获取最新行情”的既定需求一致。其代价是缓存命中率下降，应监控耗时和上游请求量，而非简单移除刷新。 |
| P2-18 | 测试/CI 改进项 | 本机 Node 可用且测试通过；缺少 Node 时跳过与 subprocess timeout 是 CI 韧性问题，不是线上运行时缺陷。 |
| P2-19、P2-20 | 清理/契约治理 | 更适合作为死代码与失效参数清理，不应与数据正确性问题同优先级。 |

### 文档层复核

| ID | 结论 | 说明 |
|---|---|---|
| D-1 | 确认 | `implementation-status.md` 与 `AGENT_SYNC.md` 的测试计数落后于本次实测 402；更新时应统一口径并注明测试命令。 |
| D-2 | 确认 | Market Reference 文档承诺名单源缺失时显式阻断，但 BSE 子源缺失仍可放行，文档和实现不一致。 |
| D-3 | 建议澄清边界 | qfq/跳变护栏针对离线 append 脚本；应明确在线 force-refresh 合并不受该护栏保护，避免读者误以为在线路径同样有校验。 |
| D-4 | 确认，低优先级 | 测试文件名与其中的新版许可边界测试主题不匹配，属于维护性问题。 |
| D-5 | 已撤回/已覆盖 | `docs/README.md` 已将 `docs/current/market-reference-data.md` 和 `docs/data-operations.md` 列入 Current Contracts 索引；无需再重复增加索引项。 |

### 复核后建议的处理顺序

1. 先统一腾讯 provider 的成交量字段名与单位，并修复历史/实时合并造成的 NaN→0；增加三类输入回归测试。
2. 修复股票池覆盖状态：任一必需交易所名单不可用或覆盖状态为 `partial`/`unknown` 时阻断当前扫描/历史研究资格。
3. 补 `v2_breakout` 状态映射，同时保留 legacy `composite_breakout` 兼容；明确扫描事实版本和排名策略版本的职责。
4. 让 SQLite 历史候选读取正确携带/解析策略版本，并为迁移增加幂等性；将这两项按降级后的 P2 排入。
5. 对确认的 P2 做定向测试和量化，再安排缓存、读模型、前端降级及清理工作；P2-14 保留为有效问题，P2-17 按既定产品行为处理。

---

## 主审对复核结论的对账（2026-09-25，第三轮）

主审对复核节的每条修改/推翻结论重新做了代码验证。结论：**复核大部分成立并采纳**，但有 1 条推翻错误（P2-14 必须恢复为有效 finding）、3 条采纳时需附带精确度修正、1 条"新增发现"实为存量问题。

### 推翻复核者结论（1 条）

| ID | 复核者结论 | 主审对账 | 结论 |
|---|---|---|---|
| P2-14 | 「catch 已有 `activeScanJobId === polledJobId` 守卫，旧任务失败不会清空新任务状态」→ 标记已过期 | **守卫方向看反了**。该等式只出现在**重试条件**里（scanJobs.js:323）：当 `activeScanJobId !== polledJobId`（旧任务 A 在途时用户已启动 B）条件恰好为假，控制流**直接掉进失败分支**——`var failedJobId = activeScanJobId`（此时已是 B 的 id）、`activeScanJobId = null`、`setScanStatus('任务状态失败')`。catch 后续（:345-375）没有任何补救守卫；B 自己的在途轮询返回时被成功路径守卫（:305）拦截 return，B 从此无人轮询。复核者把「重试分支有守卫」误读成了「整个 catch 有守卫」 | **原 P2-14 成立，恢复为有效 P2**。修复：catch 开头加 `if (activeScanJobId !== polledJobId) return;`（在进入重试/失败分支之前） |

### 采纳并附精确度修正（3 条）

| ID | 复核者结论 | 主审对账 |
|---|---|---|
| P1-1 修复建议收窄 | 保留 `composite_breakout` 兼容 | **采纳**。已验证 `legacy_c_signal_adapter.py:33-44` 的 `LEGACY_C_SIGNAL_CONTRACTS["composite_breakout"]` 带 `requires_trade_plan=True`，legacy 快照经 `scan_snapshot.py:343-345` 回填时会真实进入 is_breakout 分支——删掉它会把 legacy 突破快照误判为回踩。修复收窄为：**只补 `v2_breakout`，保留 `composite_breakout`**。注意两个 key 语义有差别：legacy 契约的 `v2_state="entry_breakout"`，而 `v2_breakout` 走的是 registry 契约，两者都应落到 `entry_breakout/breakout_allowed`。 |
| P1-2 降为部分成立 | 「当前工作区会重新计算优先级/环境」 | **采纳降级并修正机制**。`scan_snapshot.py:375-376` 只在快照缺 `v2_priority_score` 时回填；工作台正常响应链在 `scan_workspace_response.py:47` 对池结果重新计算当前优先级/环境，排序公式变化会在该路径生效。`v2_permission_model.permission` 仍源自快照（缺失时才回填），需确认本批是否改变其推导语义。新加的数据身份字段在旧快照中缺失，会使相关审计呈 unknown。版本治理仍需决策：排名策略已有独立 `RANKING_POLICY_VERSION`；若 bump `SCAN_STRATEGY_VERSION`，所有旧快照会标为 legacy，故不应把 bump 自动等同于全量重扫，需与排名策略版本/快照身份版本的职责一起复核。 |
| P2-3 表述修正 | job 本身仍 completed | **采纳**。异常只落 `postprocess.status="failed"`，job 主状态保持 completed。索引按批提交，异常可能发生在部分文件已提交之后，因此影响是索引完整性不确定；修复损坏快照后重跑 postprocess/index，不能笼统说所有快照均未索引。 |

### 对「新增发现：腾讯历史成交量单位未规范化」的定位修正

问题真实（已复核 `git show HEAD` 确认 `_fetch_tx_history_direct` 的 `["date","open","close","high","low","amount"]` 列布局在 HEAD 即存在），但**不是本批回归，是存量缺陷**：direct 历史路径的 amount（手）被 normalizer 无换算改名 volume，与 akshare 主路径（股）并存即单位不一致。区别于本批新增的 `merge_quote_bar`（stock_quote.py 为本批新文件）——**P0-1 是本批回归，direct 历史单位问题是存量**，修复时合并处理但定性不同。采纳其修复约束：在 provider 边界按证券类别换算，不要在通用 normalizer 里无条件 ×100。

### 其余复核结论

直接采纳，无需修正：

- P1-6 降 P2（索引可重建，破坏面有限）、P1-7 降 P2（opt-in 功能降级而非不可用，但 `fallback_reason` 误导性表述应一并修）。
- P2-12 复杂度修正：每次 `compact_workspace_response` 只 compact 一个 active 池的结果；各池缓存写入合计候选处理量约 `O(ΣRᵢ)`，pool 元数据遍历约 `O(P²)`。原 `O(P² × results)` 表述撤回，优化优先级待量化。
- P2-15（circuit breaker 语义待定）、P2-17（产品行为确认，P0-1 修复后 refresh=1 的上游压力自然缓解）、P2-18（CI 韧性）、P2-19/P2-20（清理项降级）。
- D-5 推翻成立：`docs/README.md:23,29` 确已收录 market-reference-data.md 与 data-operations.md，原条目错误，撤回。
- P1-3 的实盘核对（600000 于 2026-09-24 `amount/(close*volume)≈100`）与 P1-4/P1-5 的最小复现，均强化了原结论。

### 对账后的最终修复清单（替代复核节第 5 条）

| 批次 | 内容 |
|---|---|
| 1（数据正确性） | P0-1 + P1-3 + 存量 direct 历史单位：provider 边界统一成交量字段名与单位（按证券类别换算），merge 前归一到 canonical OHLCV，`_should_write_history_cache` 加 schema 校验；三类输入（纯历史/纯实时/合并）回归测试 |
| 2（许可与名单/版本治理） | P1-1 只补 `v2_breakout`（保留 `composite_breakout`）+ 回填用例；P1-4 BSE 阻断；P1-5 coverage 集合并集；P1-2 明确 scan facts、ranking policy、数据身份/schema 版本职责后再决定是否 bump `SCAN_STRATEGY_VERSION`；若 bump，评估旧快照 legacy 标记及派生索引的定向回填，不默认全量重扫 |
| 3（P2，按对账后清单） | P2-1（强指纹）、P2-2（缓存键并入参）、P2-3（索引同步单条容错）、P2-4（NaN 拦截）、P2-6（未知 reason 口径统一）、P2-7（direct 残缺帧不整体替换）、P2-8（stale 死代码）、**P2-14（恢复，catch 加 stale 守卫）**、P2-15（给 override 加恢复入口）、P2-18（node timeout + CI 断言）；P1-6/P1-7 幂等迁移与版本回填随批处理 |
| 4（治理） | D-1 测试计数统一 402；D-3 文档补在线路径边界声明；P3-14 历史比较口径统一；P2-19/P2-20、其余 P3 清理项按惯例批次 |

### 第二轮留下的四个待复核点（✅ 已全部关闭，结论见下方「第四轮：主审终审确认」）

> 状态更新：以下四点已由主审第四轮逐条验证关闭。其中 P2-14 为「复核争议已解决、代码缺陷待修复」，其余三项为复核结论确认。原文保留作为复核历史：

1. P2-14：旧任务的在途 poll 失败时，`catch` 是否会清除已切换的新任务；建议验证 stale guard 的正确位置。
2. P2-3：损坏快照触发 `CandidateSummary.from_snapshot` 异常后，索引批次提交与 postprocess 状态的实际结果；避免断言全量成功或全量失败。
3. P1-2：工作台排序重算、SQLite `RANKING_POLICY_VERSION`、`SCAN_STRATEGY_VERSION` 与快照身份/schema 字段的职责边界，以及是否需要版本 bump/回填。
4. P2-12：按实际缓存写入循环分别估算 pool 元数据遍历与候选结果 compact 的复杂度，并判断是否值得优化。

---

## 第四轮：主审终审确认（2026-09-25）

以上 4 个待复核点已全部由主审逐条验证，**分歧收敛，无遗留争议**。本节各项的「关闭」均指**复核争议闭环**，不代表对应代码缺陷已修复：

1. **P2-14 — 复核争议已解决，代码缺陷待修复（修复方案维持）**。`static/js/scanJobs.js:323-345` 逐行确认：相等判断仅保护重试分支；任务切换后旧请求失败会落入清理分支清空新任务状态。修复位置确认为 catch 开头（进入重试/失败分支之前）加 `if (activeScanJobId !== polledJobId) return;`。复核者在第二轮已接受此结论。
2. **P2-3 — 关闭，采纳「部分完成」表述**。`scan_index_store.py` 的 `index_snapshot_files` 按批 `commit()`（`position % batch_size == 0`），异常发生在部分批次提交之后时索引呈**部分完成**状态；`scan_jobs.py:440-453` 仅置 `postprocess.status="failed"`，job 主状态保持 completed。修复口径：单条候选容错 + 修复损坏快照后重跑 postprocess/index。
3. **P1-2 — 关闭，机制链已完整厘清**。本轮验证结果：
   - `scan_snapshot.py:375-376` **确实有条件**（`not output.get("v2_priority_score")` 才回填），主审第三轮「每次重算」的说法据此修正。该回填位于 `scan_result_from_snapshot`，此转换函数被**多个读链共享**——工作台加载（`scan_workspace_loader.py:175`）、单股检查复用（`scan_service.py:101,158`）、历史列表（`scan_history.py:158`）、历史比较（`scan_workspace_history_compare.py:52`）——并非只服务详情路径（复核者第五轮指出，已核实采纳）；
   - 工作台路径的**无条件重算点**在 `scan_workspace_response.py:47`（`trim_workspace_pools` → `apply_c_signal_v2_priority`），且 `c_signal_v2.py:1282-1286` 的 `apply_c_signal_v2_priority` 对每个池结果无条件 `update(build_c_signal_v2_priority(result))`——排序公式与环境许可在每次工作台构建时都用当前代码重算；
   - 旧快照的真实残余影响收敛为两点：内嵌 `v2_state_model.permission` 作为优先级 group/permission 基准（推导语义本批未变，风险有限）+ 缺失身份字段使 data_quality/coverage 呈 unknown；
   - **版本治理结论**：`sort_scan_results` 以 `strategy_status == "current"` 为第一排序键（`scan_workspace_response.py:30-38`），若直接 bump `SCAN_STRATEGY_VERSION` 而不重扫，全部存量快照会翻转为 legacy 并整体排在当前结果之后（页面出现大量「旧策略」标记）。因此采纳复核者方案：先厘清 scan facts 版本、`RANKING_POLICY_VERSION`、快照身份/schema 字段版本三者职责，再决定是否 bump 与重刷范围，不默认全量重扫。
4. **P2-12 — 关闭，采纳精化复杂度**。每次 `compact_workspace_response` 只 compact 一个 active 池的 results（非 active 池置空列表），N 次调用合计元数据遍历 O(P²)、候选结果处理 O(ΣRᵢ)；P=3 时绝对开销可忽略，优化决定留待 profiler 量化。

**最终状态**：1 P0 + 7 P1（其中 P1-6/P1-7 降 P2、P1-2 降为部分成立+治理决策）+ P2 清单（P2-14 恢复有效、P2-12 降级为量化后决定、P2-15/P2-17 转产品语义）+ D 清单（D-5 撤回）。所有条目已经过「主审 → 复核 agent → 主审对账 → 复核 agent 回填 → 主审终审」五轮闭环，可按「对账后的最终修复清单」四批次直接派发修复；修复完成后本文件移入 `docs/archive/`。

---

## 第六轮：共享转换器消费端对账与新增 P3-14（2026-09-25）

复核者对主审第五轮回复中的推论「不重算的链（历史列表、历史比较、单股复用）会直接使用旧快照内嵌分数」提出按消费端拆分的修正。主审逐点验证，**复核者拆分成立，原推论过度概括，撤回**：

| 消费端 | 验证结果 |
|---|---|
| 历史列表 `scan_history.py:158-160` | **不消费分数**——`scan_result_from_snapshot` 仅用于判断候选是否存在并累加 `pool_counts`，「历史列表直接使用旧分数」不成立 |
| 历史比较 `scan_workspace_history_compare.py:14-15,56-64,111-124` | **确实排序，但口径不同**：参考日池按 `rank_value`（`final_score`，回退 `rank_score`）排序，工作台当前列表按 `v2_priority_score` 排序（`scan_workspace_response.py:28`）；`rank_delta = index - latest_rank` 跨口径比较。**登记为新 finding P3-14**（已加入 P3 表） |
| 单股检查复用 `scan_service.py:100-107` | **返回旧字段 ≠ 用于排序/决策**：复用路径把快照转换结果附带 profile 后原样返回（`scan_source="cache"`），分数只随载荷携带；任务统计只消费状态类别，不做排序决策 |

对文档的更正：第四轮第 3 点的「该行只服务直读快照的详情路径」已在第五轮修正为「被多个读链共享」；本轮进一步把「旧分数残留」的影响边界按消费端收敛——工作台链排序不受影响（无条件重算）；历史比较存在**跨口径 rank_delta**（新 P3-14）；历史列表与单股复用路径不构成分数失真问题。

**状态修订**：撤回第四轮「无遗留争议」的概括表述。区分两类「开放」：

以下开放项记录的是第六轮复核结束时的状态；修复/决策进展以文末实施记录为准。

- **复核/决策层面开放项（2 项）**：P1-2 的版本治理决策（是否 bump `SCAN_STRATEGY_VERSION` 及重刷范围，与 `RANKING_POLICY_VERSION`/快照身份版本职责划分）；P3-14 的修复口径选择（参考日改用 v2_priority 排序，或输出明示口径差异）。
- **已确认待实施的代码修复（未动工）**：P0-1（含存量单位问题）、P1-1、P1-3、P1-4、P1-5、确认有效的 P2 清单（含 **P2-14 轮询竞态——复核已闭环但代码仍有缺陷**）、P2-18～P2-20、P3 清理项，均按「对账后的最终修复清单」四批次排程。

本文档只声明**复核结论**已闭环，不声明**代码缺陷**已修复；两清单以「对账后的最终修复清单」为准推进。

---

## 修复实施记录（2026-09-25 起）

### 批次 1：成交量数据契约 — 已实施

- 腾讯历史直连与实时行情在 provider 边界按证券代码类别统一为「股」；直连历史字段正式命名为 `volume`。换算规则与本机 AkShare 腾讯历史适配器一致，未在通用 normalizer 中无条件乘数。
- 历史帧与实时 bar 合并前先规范为 canonical OHLCV；`amount` 不再被通用 normalizer 猜作成交量，缺失成交量的行也不再伪装成 `0`。
- 缓存写入前校验 OHLCV 完整性，持久化 canonical 列并记录 `history_schema_version=2`、`volume_unit=shares`。已知旧腾讯缓存由统一读取入口按来源/旧列形态迁移，在线读取、板块广度、回放、快照重建及行情回补/追加脚本共用该入口。
- 复核的真实旧缓存 `300200_20250429_none.csv` 中，旧 `amount=183115` 经读取迁移为 `volume=18311500` 股；未批量改写或删除本地缓存文件。
- 回归覆盖纯腾讯历史、纯实时、合并、旧缓存迁移、异常缓存拒写及追加行情脚本成交量。验证：`./venv/bin/python -m unittest discover -s tests` → **411 tests OK**；`compileall` 与 `git diff --check` 通过。

批次 1 完成时批次 2 尚待执行；本文前文的「未动工」描述记录的是复核时状态，不覆盖以下实施记录。

### 批次 2：突破回填、当前股票池覆盖与版本边界（2026-09-26）— 已实施

- `build_c_signal_v2_state_from_result` 将 `v2_breakout` 正确映射为 `entry_breakout`，通过计划闸门时为 `breakout_allowed`；legacy `composite_breakout` 保留原兼容映射。
- BSE 当前名单改为 required provider source；请求失败、返回空名单或数据无法解析为有效成员时会显式失败，不再生成缺北交所的可扫描快照。
- 覆盖缺口汇总统一经 `_coverage_gaps`，包含 `partial`/`unknown`；当前扫描资格额外要求 SSE、SZSE、BSE 三所 membership 覆盖均明确可用。历史退市记录缺口仍只阻断历史研究，不误伤当前完整名单。
- P1-2 版本治理决定已记录到 ADR-0002：`SCAN_STRATEGY_VERSION` 负责扫描生成的信号事实、事件状态及单事件 Plan Gate；`RANKING_POLICY_VERSION` 负责工作区优先级、分组与宏观环境许可；两类 schema 版本只管序列化结构。当前排序/环境投影由既有 ranking policy 版本承担；本批兼容回填修正不改变扫描生成逻辑或快照结构，因此不 bump `SCAN_STRATEGY_VERSION`。旧快照缺失的数据身份字段仍按 unknown 如实审计。
- 回归覆盖 v2/legacy 突破回填、BSE 空/不可解析名单 fail-closed、当前名单部分/未知/缺失覆盖阻断，以及完整当前覆盖与不完整历史沿革的资格区分。验证：`./venv/bin/python -m unittest discover -s tests` → **414 tests OK**；`compileall` 与 `git diff --check` 通过。

### 批次 3：索引/缓存正确性与前端恢复路径（2026-09-26）— 已实施

- P2-1：单股事件缓存指纹改用列名/类型 schema + 全量行哈希的 SHA-256，不再用首尾行及哈希总和摘要；补中间行交换回归。
- P2-2：workspace raw cache key 与 lite 持久缓存 key 纳入历史比较是否生效；最新日该因子归一为 false，所以仍与候选接口共享构建，历史日则不再让两个不同 factory 互相污染。
- P2-3：快照索引逐文件使用 SQLite savepoint；单条候选转换异常会回滚该文件的部分写入、尽力记录错误 manifest，并继续处理后续文件。
- P2-4：CandidateSummary 数值投影跳过 bool、NaN 和正负 Infinity，继续尝试有限值 fallback。
- P2-6：前端未知 reason 改为不匹配，与后端 reason registry 的拒绝语义一致。
- P2-7：AkShare 帧与腾讯直连帧按日期合并，重叠日以直连值为准，保留两源覆盖范围的并集；直连无数据时不改 AkShare 路径，AkShare 为空时也直接返回原直连帧。
- P2-8：过期缓存候选不再提前 return；继续检查其他兼容缓存名，并在全部候选无效时正确报告 stale。
- P1-6：v5→v6 migration 按现有列集合幂等添加字段；初始化在进程内用共享可重入锁串行化，覆盖 threaded Flask 首次初始化竞态。
- P1-7：历史快照默认 snapshot-local 查询继续包含所有策略版本；请求 contextual 且未指定版本时，current 策略按上下文排序、legacy 策略仍显示并按本地分数排在 current 组之后。响应标明上下文版本及 `current_strategy_only` 覆盖范围；显式策略筛选时上下文与候选集合一致。排序模式先归一大小写。
- P2-14：轮询 catch 开头增加 stale job guard，旧任务请求失败不再清理新任务状态。
- P2-15：用户 force refresh 时清除 JSON fallback override/error 并重试 SQLite；若仍失败，现有 JSON fallback 会重新建立。
- P2-18：Node 子进程测试增加 30 秒超时；CI 环境缺 Node 时明确失败，本地开发仍可跳过。
- 本批未重复修改已经存在的请求超时/取消支持和 backtest 非有限收益过滤。P2-17 仍是已确认的 force-refresh 产品行为，不改。
- 回归新增覆盖缓存碰撞、不同 factory key、坏快照隔离、有限数校验、历史 contextual 版本边界、跨源历史合并、过期缓存候选遍历、旧任务轮询竞态及 SQLite 降级恢复。验证：`./venv/bin/python -m unittest discover -s tests` → **424 tests OK**；`git diff --check` 通过。

**批次 3 完成时待处理（批次 4 推进前状态）**：P3-14 历史比较口径、P2-19/P2-20 失效测试与参数清理、文档 D-1/D-3 及其余 P3 清理。P1-1/P1-3 已在前两批完成；P1-4/P1-5 也已在批次 2 完成。

### 批次 4：历史比较与退役边界治理（2026-09-26）— 已实施

- P3-14：参考日候选与当前工作台统一使用重算后的 `v2_priority_score` 排序；`strategy_status` 仍先分组。`rank_delta` 现在比较相同排序口径，新增“final_score 与 v2_priority_score 次序相反”的回归用例。
- P2-19：全仓确认 `market_breadth.py`、`board_market_refresh.py`、`resonance_calibration.py` 均无生产导入；删除退役模块及仅测试这些模块的用例。保留 `/api/board_market*` 的 410 兼容行为和工作台 `resonance_calibration: disabled` 响应字段。
- P2-20：从 `collect_scan_workspace`、`build_workspace_structure`、rank-context 物化器及 API 调用中移除不生效的 `include_market_universe` / `include_market_breadth` / `board_market_reader` 参数；清掉仅断言这些参数透传的测试条件，不动仍用于说明禁用市场因子的 rank-context policy fingerprint。
- D-1：`docs/current/implementation-status.md` 与 `AGENT_SYNC.md` 当前状态统一为 2026-09-26 全量 422 项通过；旧日志中的 266/378/402 等计数保留为历史记录，不覆盖当前基线。顺手将扫描索引版本说明从 v5 更正为 v6。
- D-3：`docs/data-operations.md` 明确离线 append 的断档/跳变护栏不覆盖在线 `force_refresh` 历史帧与实时 bar 合并；来源标记不代表 qfq 连续性校验。
- D-4：将 `tests/test_scan_market_context.py` 重命名为 `tests/test_market_permission.py`，与新版许可边界测试内容一致；确认旧路径没有代码引用。
- 验证：`./venv/bin/python -m unittest discover -s tests` → **422 tests OK**；`compileall` 与 `git diff --check` 通过。

**批次 4 当前状态**：P3-14 与 D-4 已完成；其余低优先级 P3 清理尚未处理。P2-17 维持已确认的 force-refresh 产品行为，不是待修缺陷。前文各轮的开放项是当时快照，当前实施状态以本记录为准。

### 批次 5：工作区死参数与退役宽度代码 — 已实施

- P3-8：从 `build_workspace_structure` 移除未使用的 `profile_cache`、`start_date`、`include_replay` 与 `replay_max_candidates`；从 `collect_scan_workspace` 移除 `include_replay`/`replay_max_candidates` 无效参数及调用端透传。API 不再把已退役的 `include_replay` 放进缓存键，也不再传入工作区 factory，避免同一 disabled 行为产生缓存分裂；保留 `replay_entry_model`，因其仍用于兼容响应元数据。
- P3-9：删除无调用者的市场宽度统计实现、无消费者的 `scan_resonance.py` facade，以及持久缓存中无调用者的 `_directory_stat`。候选行业/概念分布统计路径未改。
- 同步移除 `apply_score_confidence` 上无效的 `replay_calibration` 参数；保留 `replay_calibration: disabled` 的响应结构。
- 回归覆盖禁用回放字段兼容、不同 `include_replay` 查询不再让工作区与 candidates 分裂缓存，以及历史排序/工作区 API。验证：`./venv/bin/python -m unittest discover -s tests` → **422 tests OK**；`compileall` 与 `git diff --check` 通过。

**批次 5 后续复核顺序**：继续逐条核实并处理仍有效的 P3-1～P3-7、P3-10～P3-13；涉及任务取消语义或行情缓存身份的条目优先做行为验证和定向测试，不按“死代码清理”直接删除。P3-14、D-4、P3-8、P3-9 已完成。P2-17 仍是确认保留的产品行为。

### 批次 6：日线缓存身份一致性 — 已实施

- P3-12 复核：`generated_at` 不是缓存原始抓取时间，而是本次分析请求的北京时间；`cache_written_at` 单独表示本地缓存写入时间，契约文档已明确，因此撤回“缓存命中时生成时间错误”的判断。
- CSV 与 sidecar 使用独立临时文件和原子替换，但两次替换整体不是一个事务。新 sidecar 增加 `cache_payload_revision`；读取时重新计算 canonical OHLCV revision，若与 sidecar 不匹配就拒绝该缓存，避免写入中断/并发错配时沿用错误来源或 bar 状态。旧 sidecar 没有该字段时继续按兼容路径读取。
- 从 `data_fetcher.py` 移除未使用的 `market_symbol_for_tx` 再导入；对应测试从 `providers.stock_history` 导入。
- 回归覆盖新 sidecar revision 写入、CSV/sidecar 错配拒读以及原缓存身份往返。验证：`./venv/bin/python -m unittest discover -s tests` → **423 tests OK**；`compileall` 与 `git diff --check` 通过。

**当前复核进度**：P3-14、D-4、P3-8、P3-9、P3-11、P3-12 已处理；P3-1～P3-7、P3-10、P3-13 仍需逐条复核。下批先核实 P3-1 日志可见性是否仍是当前配置下的问题，再决定其最小修复。

### 批次 7：扫描任务取消与历史保留 — 已实施

- P3-11 取消语义：发现取消请求时，先保留当前批次中已完成、但尚未由 `as_completed` 循环消费的 future 结果；尚未完成的任务仍尝试取消，不等待可能阻塞的 provider 请求。取消后的 `completed/matched/results` 因而反映已收录结果。
- P3-11 历史裁剪：`max_history` 现在限制终态历史数量，所有非终态活动任务始终留在内存与落盘索引中，避免长任务被较新的已完成任务挤出。
- 完成钩子在任务终态前同步执行是既有生命周期契约：其失败只设置 `postprocess.status=failed`，不改写扫描主任务成功状态；维持现状。
- 新增受控 future 取消测试与活动任务超出历史窗口测试。验证：`./venv/bin/python -m unittest discover -s tests` → **425 tests OK**；`compileall` 与 `git diff --check` 通过。
