---
status: accepted
decision_date: 2026-09-26
last_verified: 2026-09-26
supersedes: []
---

# ADR-0005: SQLite Candidate Read Default

## Context

候选页曾默认读取并组装 JSON 工作区，SQLite 摘要/详情只通过 URL 参数启用。随着扫描
快照增长到 103,437 份，目录遍历和 JSON 组装已成为默认读取的主要成本。SQLite schema
v8 已具备源目录 revision 对账、快照计算类型、稳定摘要分页、精确详情定位和完整排名上下文。

2026-09-24 三池共 5,134 条候选的影子对比通过：成员、关键字段和完整排序均一致；全量
索引 103,437/103,437，解析失败为 0。扫描计划由全量解析 JSON 的约 44.56 秒降至约
0.41 秒，缓存指纹由约 1.97 秒降至约 0.04 秒。

## Decision

1. 候选页默认使用 SQLite `CandidateSummary` 和 `CandidateDetail` 读模型。
2. `?candidate_source=json` 是显式回退开关；SQLite 不完整、排名上下文不可用或请求失败时，
   当前页面仍自动整页回退 JSON，不混合两种列表来源。
3. JSON 快照继续保存完整扫描事实与详情，不迁入 SQLite。
4. 扫描计划优先读取完整 SQLite manifest；索引或规划元数据不完整时才回退 JSON。
5. `index_complete`、工作区缓存指纹和候选 API 使用同一 source-sync revision 契约。

## Consequences

- 默认候选读取不再遍历全部 JSON 文件。
- 新增、修改或删除快照后，索引必须完成源目录对账才重新声明完整。
- 全量重建后必须重新物化 `snapshot` 与 `latest_fresh` 两类排名上下文。
- JSON 回退保留为迁移和故障恢复路径，不再是候选页默认生产路径。
