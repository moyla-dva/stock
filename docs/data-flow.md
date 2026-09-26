# Data Flow

当前项目的数据流遵循一个核心原则：**本地数据先落盘，候选池消费快照，单股确认支撑最终人工判断**。

## Core Flow

```mermaid
flowchart LR
    user["用户操作"]

    subgraph providers["外部/本地数据源"]
        stockCatalog["AkShare / 当前上市名单"]
        akshare["AkShare / 行情"]
        tencent["腾讯行情"]
        tdx["TDX 兜底"]
        adata["AData / 概念辅助"]
        ths["同花顺页面"]
        cninfo["巨潮资讯 / 画像"]
    end

    subgraph cache["本地缓存层"]
        history["日线历史缓存"]
        minute["分钟历史缓存"]
        profiles["股票画像缓存"]
        concepts["概念库缓存"]
        relationEvidence["画像关系证据"]
        snapshots["扫描快照"]
        jobs["任务记录"]
    end

    subgraph compute["计算与结构层"]
        indicators["指标计算"]
        strategy["V2 事实层/状态机 C研/C候/C修/C回/C突/C爆/C风"]
        universe["当前股票池解析"]
        scanner["策略扫描器"]
        structure["行业/概念候选分布统计"]
        tradePlan["交易权限与交易计划（单股页与候选池共用 V2 许可契约）"]
    end

    subgraph api["后端 API"]
        stockListApi["/api/stock_list"]
        workspaceApi["/api/scan_workspace"]
        candidateApi["/api/scan_workspace/candidates"]
        analyzeApi["/api/analyze"]
        jobApi["/api/scan_jobs"]
        dataApi["/api/data_sources"]
    end

    subgraph ui["前端工作台"]
        candidates["候选池"]
        singleStock["单股确认"]
        dataJobs["数据后台"]
    end

    stockCatalog --> universe
    universe --> scanner
    stockCatalog --> stockListApi
    akshare --> history
    tencent --> history
    tdx --> history
    akshare --> minute
    tdx --> minute
    adata --> concepts
    ths --> concepts
    cninfo --> profiles
    relationEvidence --> profiles

    history --> indicators
    minute --> indicators
    indicators --> strategy
    strategy --> scanner
    scanner --> snapshots
    profiles --> structure
    concepts --> structure
    snapshots --> structure
    strategy --> tradePlan

    structure --> workspaceApi
    snapshots --> candidateApi
    history --> analyzeApi
    minute --> analyzeApi
    tradePlan --> analyzeApi
    jobs --> jobApi
    cache --> dataApi

    user --> candidates
    user --> singleStock
    user --> dataJobs
    workspaceApi --> candidates
    candidateApi --> candidates
    analyzeApi --> singleStock
    jobApi --> dataJobs
    dataApi --> dataJobs
```

板块/概念指数行情、宽度与共振计算不在当前候选工作台决策链路中。旧行情 API 返回
`410 Gone`；磁盘上遗留的行情缓存不再读取或刷新。候选页只按个股结果展示行业/概念分布，
它们不影响排序和许可。

## Workspace Flow

```mermaid
sequenceDiagram
    participant U as 用户
    participant UI as 候选池
    participant API as /api/scan_workspace
    participant S as 本地扫描快照
    participant P as 股票画像/概念库

    U->>UI: 打开候选池
    UI->>API: GET /api/scan_workspace?limit=120
    API->>S: 读取最新有效快照
    API->>P: 补股票名称、行业、概念和画像证据
    API-->>UI: 候选池、行业/概念分布、个股许可和数据状态
    UI->>UI: 默认展示参与候选、风险验证和修复观察
```

## Candidate Filtering

`/api/scan_workspace/candidates` 只负责从本地完整快照里做轻量筛选：

- `scan_type`
- `sector`
- `concept`
- `query`
- `limit`
- `offset`

不再支持 `mainline_id`。如果后续重新设计更高层主题能力，应先形成新的领域契约和测试，再接回候选筛选。

## Single Stock Flow

```mermaid
sequenceDiagram
    participant U as 用户
    participant UI as 单股确认
    participant API as /api/analyze
    participant H as 行情缓存/Provider
    participant C as 计算模块

    U->>UI: 输入股票或从候选池打开
    UI->>API: GET /api/analyze?code=...
    API->>H: 读取/刷新日线和分钟线
    API->>C: 指标、V2 事实/状态机、多周期、交易计划
    API-->>UI: ECharts 数据、事件、画像、trade_plan
    UI->>UI: 展示图表、信号、止损、仓位和风险动作
```

## Data Backstage Flow

```mermaid
flowchart TD
    A[数据后台] --> B[扫描任务]
    A --> C[历史快照]
    A --> D[概念库]
    A --> F[数据源状态]
    A --> G[缓存清理]

    B --> B1[/api/scan_jobs]
    C --> C1[/api/scan_history]
    D --> D1[/api/stock_concepts/status + refresh]
    F --> F1[/api/data_sources]
    G --> G1[/api/scan_cache/prune]
```

## Boundary Rules

- 候选池只消费本地结果，不承载刷新策略、缓存清理或任务细节。
- 单股确认负责提供人工判断所需的行情、结构与条件化计划，不负责全市场扫描。
- 数据后台负责刷新、重扫、历史回看和数据治理；行业/概念分桶校准已退役。
- 概念图谱和画像证据可以辅助结构解释，但当前不是核心产品入口。
- 板块/概念行情抓取与刷新已退役；行业/概念标签和候选分布只作描述与筛选，不进入个股排序或许可判断。
- AI 不应替代数据源、评分、回放、交易计划或风险判断。
