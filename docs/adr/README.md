# Architecture Decision Records

本目录记录已经采纳、会长期影响代码结构或产品边界的决策。

文件命名使用：

```text
NNNN-short-decision-title.md
```

状态使用：

- `proposed`：正在讨论。
- `accepted`：已经采纳。
- `superseded`：被后续 ADR 替代。
- `rejected`：明确不采用，但保留理由。

当前已采纳的决策：

- [ADR-0001：研究驱动的决策工作台](0001-research-driven-decision-workbench.md)
- [ADR-0002：候选排序所有权](0002-candidate-ranking-ownership.md)
- [ADR-0003：按有效期管理证券身份](0003-effective-dated-security-identity.md)
- [ADR-0004：候选优先默认入口](0004-candidate-first-default-entry.md)
- [ADR-0005：SQLite 候选读模型转默认](0005-sqlite-candidate-read-default.md)

当前没有待裁决的 proposed ADR。

ADR 记录为什么作出决定，不承担当前接口字段的完整说明。当前行为由 `docs/current/` 定义。
