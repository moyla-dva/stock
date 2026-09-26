# Research Documents

本目录保存策略审计、事件研究、参数敏感性、校准和数据质量实验。研究结论不会自动成为产品承诺。

- [候选排序因子字典与重复计分审计（2026-09）](candidate-ranking-factor-audit-2026-09.md)
- [CandidateRanking V1 设计草案（2026-09）](candidate-ranking-v1-design-2026-09.md)
- [CandidateRanking V1 特征覆盖与证据映射（2026-09）](candidate-ranking-feature-coverage-2026-09.md)
- [候选排序后续结果基线（2026-09）](candidate-ranking-outcome-baseline-2026-09.md)

新研究文档使用以下头部：

```yaml
---
status: exploratory
strategy_version: ""
data_window: ""
universe: ""
entry_model: ""
data_revision: ""
evidence_level: exploratory
supersedes: []
---
```

正文至少说明：

- 研究问题和假设。
- 数据来源、时间范围和股票池。
- 入场、退出、费用和缺失数据处理口径。
- 方法限制和可能偏差。
- 复现命令或脚本。
- 结果是否会改变当前产品或策略契约。

未经完整成交模型验证的结果使用“事件研究”或“历史事件统计”，不使用“可交易回测收益”。
