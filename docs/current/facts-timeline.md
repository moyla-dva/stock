---
status: current
contract_version: 1
last_verified: 2026-09-23
implementation_status: incremental-prefix-reuse
owners: local-user
supersedes: []
---

# V2 Facts Timeline

## Current Boundary

图表事件需要观察最近若干根 K 线在各自历史时点上的 facts，不能用今天的 facts
反推过去。时间线因此仍按 `frame[:idx + 1]` 计算，保证每个事件只看到当时已经存在
的数据。

当前实现分两层降低成本：

- `build_c_signal_v2_event_facts` 只返回图表投影实际读取的 setup、repair、risk、
  fractals、rectangle、exit gate 和 trigger，不返回宏观潮汐、目标结构、完整归一化
  K 线等大对象。
- `V2FactsTimelineCache` 按单票/周期 scope 保存最近事件窗口的 facts 和逐行内容哈希。
  新 K 线追加且历史前缀不变时，只计算新时点；任一历史行变化后，只复用变化位置
  之前的 facts。

完全相同的行情仍由事件结果缓存直接命中。增量 facts 缓存仅保留有限 scope，属于
可丢弃的进程内性能层，不是事实来源，也不写入扫描索引。

## Correctness Rules

- 缓存身份必须包含调用方提供的股票和周期 scope。
- 只有逐行内容哈希一致的公共前缀可以复用。
- 最新完整 facts 可以注入时间线，图表不得为同一最新 bar 重算第二份口径。
- 首次访问仍需建立 lookback 窗口；“增量”指后续追加或重复访问，不声称首次计算
  已成为 O(1)。
- 事件 facts 与完整 facts 必须保持事件签名零差异，使用
  `scripts/benchmark_v2_event_facts.py` 做离线核对。

## Next Step

若首次打开单票页的时间线仍是主要瓶颈，再把包含关系、分型和矩形识别改造成显式
状态机，并为每个状态定义版本和序列化格式。在零差异基线建立前，不把复杂结构算法
改写成不可验证的滚动近似。
