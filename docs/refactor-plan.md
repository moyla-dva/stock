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

1. 候选池保留两个一级入口：参与候选、风险验证。
2. `bottom_div` 保留为历史快照和内部扫描兼容，不再作为一级 tab。
3. 同步批扫 `/api/scan_batch` 退役，统一使用后台任务 `/api/scan_jobs`。
4. 概念图谱保留 API 和本地文件能力，但在数据源健康中标记为实验项，不参与核心可用率。
5. 候选详情只读展示画像证据；人工编辑从默认决策流移出。
6. README 和当前 docs 只描述现行系统，旧设计文档进入 `docs/archive/`。

## Execution Order

1. 清理当前产品契约：README、流程图、数据流、设计方向、裁剪审计。
2. 收敛候选池 UI：删除修复观察一级入口，替换旧英文标签。
3. 收敛候选详情：保留画像证据展示，移出校准编辑控件。
4. 收敛扫描入口：让 `/api/scan_batch` 明确返回退役状态。
5. 调整数据源状态：概念图谱标记为实验项，核心可用率只统计核心数据源。
6. 补测试：退役接口、实验数据源状态。
7. 运行全量测试并做残留关键词检查。

## Acceptance Criteria

- 当前文档不再把项目描述为旧主线决策系统。
- 候选池默认产品入口不再出现修复观察一级 tab。
- 历史 `bottom_div` 数据仍能被后端和旧快照读取。
- `/api/scan_batch` 不再触发同步扫描。
- `/api/data_sources` 能区分核心数据源与实验项。
- `./venv/bin/python -m unittest discover -s tests` 通过。
