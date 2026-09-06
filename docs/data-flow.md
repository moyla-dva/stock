# Data Flow

当前项目的数据流遵循一个核心原则：**本地数据先落盘，候选池消费快照，单股确认负责最终执行判断**。

## Core Flow

```mermaid
flowchart LR
    user["用户操作"]

    subgraph providers["外部/本地数据源"]
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
        boardMarket["板块/概念行情缓存"]
        relationEvidence["画像关系证据"]
        snapshots["扫描快照"]
        jobs["任务记录"]
    end

    subgraph compute["计算与结构层"]
        indicators["指标计算"]
        strategy["综合策略 C观/C回/C突"]
        scanner["策略扫描器"]
        breadth["真实宽度计算"]
        structure["板块/概念结构聚合"]
        resonance["候选共振评分"]
        tradePlan["交易权限与交易计划"]
        replay["回放/校准"]
    end

    subgraph api["后端 API"]
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

    akshare --> history
    tencent --> history
    tdx --> history
    akshare --> minute
    tdx --> minute
    adata --> concepts
    ths --> concepts
    cninfo --> profiles
    akshare --> boardMarket
    relationEvidence --> profiles

    history --> indicators
    minute --> indicators
    indicators --> strategy
    strategy --> scanner
    scanner --> snapshots
    profiles --> structure
    concepts --> structure
    boardMarket --> structure
    history --> breadth
    snapshots --> structure
    breadth --> structure
    structure --> resonance
    snapshots --> replay
    strategy --> tradePlan

    structure --> workspaceApi
    resonance --> workspaceApi
    replay --> workspaceApi
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

## Workspace Flow

```mermaid
sequenceDiagram
    participant U as 用户
    participant UI as 候选池
    participant API as /api/scan_workspace
    participant S as 本地扫描快照
    participant P as 股票画像/概念库
    participant B as 板块行情/真实宽度

    U->>UI: 打开候选池
    UI->>API: GET /api/scan_workspace?limit=120
    API->>S: 读取最新有效快照
    API->>P: 补股票名称、行业、概念和画像证据
    API->>B: 合成板块/概念结构和宽度
    API-->>UI: 候选池、结构概览、校准、数据状态
    UI->>UI: 默认展示参与候选和风险验证
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
    API->>C: 指标、综合策略、多周期、交易计划
    API-->>UI: ECharts 数据、事件、画像、trade_plan
    UI->>UI: 展示图表、信号、止损、仓位和风险动作
```

## Data Backstage Flow

```mermaid
flowchart TD
    A[数据后台] --> B[扫描任务]
    A --> C[历史快照]
    A --> D[概念库]
    A --> E[板块/概念行情]
    A --> F[数据源状态]
    A --> G[缓存清理]

    B --> B1[/api/scan_jobs]
    C --> C1[/api/scan_history]
    D --> D1[/api/stock_concepts/status + refresh]
    E --> E1[/api/board_market + refresh]
    F --> F1[/api/data_sources]
    G --> G1[/api/scan_cache/prune]
```

## Boundary Rules

- 候选池只消费本地结果，不承载刷新策略、缓存清理或任务细节。
- 单股确认负责执行判断，不负责全市场扫描。
- 数据后台负责刷新、重扫、历史回看、校准和治理。
- 概念图谱和画像证据可以辅助结构解释，但当前不是核心产品入口。
- AI 不应替代数据源、评分、回放、交易计划或风险判断。
