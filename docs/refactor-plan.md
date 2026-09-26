# Refactor Plan

## Goal

保持本地优先架构，把项目收敛成稳定的 A 股短线结构工作台：

```text
Provider -> Local Cache -> Scan Snapshot -> Candidate Workspace -> Single Stock Confirmation
```

当前重构目标不是恢复旧主线能力，而是减少候选流里的噪声、明确数据治理边界，并让后端返回结构成为前端渲染的唯一依据。

## Target Boundaries

| Layer | Responsibility | Should Avoid |
| --- | --- | --- |
| `providers/` | 外部数据适配：行情、概念、板块行情 | 策略评分、UI 语言、缓存治理 |
| cache modules | 路径、读写、过期、清理 | 候选解释和交易结论 |
| scan modules | 指标、策略扫描、快照、候选聚合 | 页面状态和用户交互 |
| workspace modules | 读取快照、补画像、聚合结构、生成 view model | 发起长任务、编辑证据 |
| services | Flask 路由和后台任务复用的业务 API | 直接操作 DOM 或混入前端 fallback |
| frontend | 渲染服务端状态、管理交互 | 重做后端评分、暴露底层控制台 |

## Current Decisions

1. 候选池保留三个一级入口：参与候选、风险验证、修复观察（2026-09-20 起恢复 `bottom_div` 为一级 tab）。
2. `bottom_div` 的历史快照与内部扫描兼容继续保留。
3. 同步批扫 `/api/scan_batch` 退役，统一使用后台任务 `/api/scan_jobs`。
4. 概念图谱保留 API 和本地文件能力，但在数据源健康中标记为实验项，不参与核心可用率。
5. 候选详情只读展示画像证据；人工编辑从默认决策流移出。
6. README 和当前 docs 只描述现行系统，旧设计文档进入 `docs/archive/`。

## Execution Order

1. 清理当前产品契约：README、流程图、数据流、设计方向、裁剪审计。
2. 收敛候选池 UI：保留参与候选 / 风险验证 / 修复观察三个一级入口，替换旧英文标签。
3. 收敛候选详情：保留画像证据展示，移出校准编辑控件。
4. 收敛扫描入口：让 `/api/scan_batch` 明确返回退役状态。
5. 调整数据源状态：概念图谱标记为实验项，核心可用率只统计核心数据源。
6. 补测试：退役接口、实验数据源状态。
7. 运行全量测试并做残留关键词检查。

## Acceptance Criteria

- 当前文档不再把项目描述为旧主线决策系统。
- 候选池默认产品入口稳定展示修复观察一级 tab，且明确其观察语义。
- 历史 `bottom_div` 数据仍能被后端和旧快照读取。
- `/api/scan_batch` 不再触发同步扫描。
- `/api/data_sources` 能区分核心数据源与实验项。
- `./venv/bin/python -m unittest discover -s tests` 通过。

## Next Architecture Track

以下项目属于结构性收敛，需分阶段落地，不应混入小型行为修复：

1. **Signal/Event Registry**：集中定义 `signal_key`、池归属、权重、前端筛选标签和文档名称，由注册表派生 `SCAN_CONFIG`、`EVENT_WEIGHTS` 与前端 reason 映射，避免字符串契约多处漂移。
2. **Facts Timeline**：把 V2 facts 从逐根前缀重算改为一次性时间线，事件层、历史事件研究层和单股页消费同一份中间事实，降低单股页首开成本。
3. **Workspace Index**：扫描快照先生成 canonical pool index，主工作台、候选分页和详情都从 index 派生，避免 API 端点各自冷构建完整 workspace。
4. **Cache Registry**：统一缓存键、元数据、TTL、原子写、版本迁移和清理策略，覆盖日线、分钟线、扫描快照和 workspace response。
5. **API/Frontend Safety Contract**：`/api/*` 始终返回 JSON 错误；前端所有 HTML formatter 的动态字段默认转义。

当前进展：

- 后端已新增 `stock_analyzer/signal_registry.py`，`scanner.py` 的三池配置和事件权重、候选分页的 C类 reason alias 已改为读取注册表；前端 `scanFilters.js` 先收敛为本地 alias 常量。下一步如果要做到完全单源，需要由注册表导出一个前端可消费的静态 JSON 或 API 片段。
- 已新增 `stock_analyzer/v2_facts_timeline.py`，把事件层逐根构建 facts 的 prefix 窗口抽成 timeline，并按股票/周期 scope 复用内容哈希一致的公共前缀。行情只追加一根时，后续请求只计算新增时点；历史行被修订时从首个变化位置失效。首次访问仍需建立 lookback 窗口，复杂结构算法尚未改写为持久化状态机。timeline 默认使用 `build_c_signal_v2_event_facts()` 轻量 profile；`scripts/benchmark_v2_event_facts.py` 继续校验 full facts 与 event facts 的事件签名零差异。
- 已新增 `CandidateSummary`、`CandidateDetail`、`SingleStockAnalysis` 三种读模型和可重建 SQLite 扫描索引。索引具备完整/局部构建状态、后台任务增量同步、摘要分页和 opt-in API；当前生产候选 API 尚未切换，完整快照仍是详情事实来源。
- 已新增独立 `market_metadata.sqlite3` 底座，支持版本化交易日历和历史时点股票池的本地导入、来源记录与严格时点查询。当前尚未导入权威数据，生产扫描链未消费。
- 已建立候选优先和单票优先两份静态交互原型；用户已选择候选优先作为默认入口方向，单票分析仍需一键可达；最终视觉实现和前端技术栈尚未决策。
- 前端请求层已支持 AbortSignal/超时组合，主分析请求会取消上一笔未完成请求；扫描任务轮询对瞬时状态失败做短退避重试；搜索筛选已加防抖。ECharts 改为本地 `static/vendor/echarts.min.js`，不再依赖 jsdelivr 首屏可用性。
