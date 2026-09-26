# Documentation Index

本目录按“当前契约、架构决策、研究证据、历史资料”管理。目录位置代表文档用途，不代表代码已经完成对应能力。

## Authority Order

发生冲突时，按以下顺序判断当前有效内容：

1. `docs/current/`：当前产品、数据和接口契约。
2. `docs/adr/`：已经采纳的架构决策及其理由。
3. 根目录现有文档：迁移期间的现状说明，需结合文件状态判断。
4. `docs/research/`：研究、审计和实验结果，不自动成为产品契约。
5. `docs/archive/`：历史资料，只用于理解演进过程。

代码和当前契约不一致时，应记录差异并修正一方，不能用研究文档覆盖生产行为。

## Current Contracts

- [项目结构与推进路线](current/project-map.md)：生产链路、影子链路、目录职责和下一阶段验收顺序。
- [产品契约](current/product-contract.md)：产品角色、责任边界、术语和未来自动化边界。
- [读模型契约](current/read-model-contracts.md)：候选摘要、候选详情和单票分析的目标数据形状。
- [SQLite 扫描索引](current/sqlite-scan-index.md)：离线索引实现、重建方式和接管查询前的门槛。
- [市场参考数据](current/market-reference-data.md)：版本化交易日历、历史时点股票池及其导入边界。
- [证券身份与沿革模型](current/security-reference-model.md)：稳定证券 ID、代码别名和交易所成员有效期。
- [V2 Facts 时间线](current/facts-timeline.md)：历史时点计算、公共前缀复用和后续增量边界。
- [实施状态](current/implementation-status.md)：七条架构路线的底座、生产接管与剩余门槛。
- [当前功能流](current-feature-flow.md)：当前页面和后端流程，待逐步迁入 `current/`。
- [当前数据流](data-flow.md)：当前数据来源、缓存和计算链，待补充数据身份后迁入 `current/`。
- [数据运维](data-operations.md)：缓存及运维操作说明，迁移期间继续有效。

## Research

- [市场参考来源审计](research/market-reference-source-audit.md)：交易日历、股票池、交易所来源和授权边界。
- [上游数据使用条款审查](research/upstream-data-terms-audit-2026-09.md)：活跃行情/名单/概念接口的来源映射、公开条款证据与未解决授权门槛；不构成许可结论。
- [证券沿革事件来源清单](research/security-reference-event-sources.md)：成员、转板、退市、代码与名称事件的证据要求及覆盖门槛。
- [SQLite 候选读链影子比较](research/scan-candidate-read-shadow-2026-09.md)：五个历史快照日的候选成员、分页和排序差异。

## Architecture Decisions

- [ADR-0001：研究驱动的个人决策工作台](adr/0001-research-driven-decision-workbench.md)
- [ADR-0002：个股优先级与候选排序权归属（已采纳）](adr/0002-candidate-ranking-ownership.md)
- [ADR-0003：有效期证券身份](adr/0003-effective-dated-security-identity.md)

## Migration Rules

- 暂不批量移动根目录文档，避免打断现有链接和未提交修改。
- 文档完成状态审查后，再迁入 `current/`、`research/` 或 `archive/`。
- 新增研究文档必须声明数据窗口、策略版本、股票池、入场模型和证据等级。
- 新增当前契约必须声明状态、版本和最后确认日期。
- 过期文档进入 `archive/`，不要静默删除其历史背景。

## Document Metadata

当前契约建议包含：

```text
status
contract_version
last_verified
owners
supersedes
```

研究文档至少包含：

```text
status
strategy_version
data_window
universe
entry_model
data_revision
evidence_level
supersedes
```

`evidence_level` 使用以下值：

- `hypothesis`：待验证假设。
- `exploratory`：探索性结果，样本或方法仍有限制。
- `validated`：方法、数据和复现步骤已经核对。
- `production-observation`：来自生产运行的观测，不等同于因果结论。
