# Data Operations

## User-Facing Model

数据后台只回答三件事：

- 当前结果是否可用。
- 哪些本地缓存或任务需要治理。
- 需要刷新时应该走哪个后台任务。

默认候选池不承载刷新策略、缓存清理、历史回放或实验校准。

## Data States

| State | Meaning |
| --- | --- |
| `provider` | 可按需请求的外部数据源。 |
| `ready` | 本地已有可用缓存或任务记录。 |
| `warning` | 本地数据存在，但可能过期、旧策略或需要清理。 |
| `empty` | 尚未建立本地缓存。 |
| `experimental` | 可供研究或内部解释，不计入核心可用率。 |

## Current Local Sources

- 日线历史缓存：单股分析、扫描、回放、真实宽度计算的基础。
- 分钟历史缓存：单股确认时的短周期补充。
- 扫描快照：候选池读取的本地结果。
- 股票画像：名称、行业、概念和关系证据的载体。
- 概念库：股票到概念的本地映射。
- 画像证据：人工或公告确认的股票关系证据。
- 板块行情：行业/概念指数趋势缓存。
- 扫描任务记录：后台扫描进度、历史和中断恢复。
- 概念图谱：实验性关系边，不是当前核心产品入口。

## Scan Policies

- `auto`：跳过有效快照，只补缺失、过期或旧策略结果。
- `cache`：只读本地快照，不计算新结果。
- `force`：忽略当前池快照并重算。

重复发起相同池和相同范围的活动扫描时，后台任务应复用已有任务，而不是创建第二条队列。

## Public Scan Types

当前产品入口只展示：

- `opportunity`：参与候选。
- `risk`：风险验证。

内部兼容仍保留：

- `bottom_div`：底背离/修复观察扫描类型，可存在于历史快照、测试和底层策略中，但不再作为候选池一级入口。

## Governance Placement

| Operation | Placement |
| --- | --- |
| 启动扫描任务 | 数据后台 |
| 强制重扫 | 数据后台 |
| 查看任务历史 | 数据后台 |
| 清理旧策略/无效快照 | 数据后台 |
| 刷新概念库 | 数据后台 |
| 刷新板块行情 | 数据后台 |
| 查看数据源健康 | 数据后台 |
| 候选筛选 | 候选池 |
| 单股执行确认 | 单股确认 |

## Profile Evidence

候选详情可以展示画像关系证据，用来说明股票和行业/概念之间的关系质量。

当前默认候选详情只读展示这些证据，不提供人工校准表单。证据写入 API 仍保留给数据后台、脚本或未来专门的研究工具使用：

```json
POST /api/profile_relations/evidence
{
  "code": "600063",
  "relation": {
    "relation_name": "储能",
    "relation_kind": "business",
    "relation_type": "core_business",
    "source": "manual",
    "confidence": 0.92,
    "evidence": "公告确认主营业务覆盖储能设备",
    "last_verified_date": "2026-05-13"
  }
}
```

## Concept Graph

概念图谱当前是实验层：

- 持久化边存放在 `.cache/catalog/concept_graph_edges.json`。
- `/api/concept_graph` 和 `/api/concept_graph/edges` 继续保留。
- 派生边来自股票画像中的成员重叠，只能说明共现关系，不能直接生成交易结论。
- 在 `/api/data_sources` 中标记为 `experimental`，不计入核心数据源可用率。
