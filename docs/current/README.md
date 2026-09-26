# Current Contracts

本目录只保存当前生产行为应当遵守的产品、数据和接口契约。

- [产品契约](product-contract.md)
- [读模型契约](read-model-contracts.md)
- [SQLite 扫描索引](sqlite-scan-index.md)
- [行情数据身份](market-data-identity.md)
- [市场参考数据](market-reference-data.md)
- [证券身份与沿革模型](security-reference-model.md)
- [V2 Facts 时间线](facts-timeline.md)
- [实施状态](implementation-status.md)

进入本目录的文档必须满足：

- 已明确由当前代码实现，或者明确标注尚未实现的目标状态。
- 带有 `status`、`contract_version` 和 `last_verified`。
- 不以实验结果或旧版本说明替代当前契约。
- 行为变化时同步修改代码、测试和对应契约。
