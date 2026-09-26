# A股短线结构工作台

本项目是一个本地优先、研究驱动、人工判断优先的 A 股短线个人决策工作台。它当前不再提供“主线决策”功能，也不管理真实账户、持仓或订单，核心目标收敛为：

```text
扫描候选 -> 结构验证 -> 单股确认 -> 数据后台治理
```

系统使用 AkShare、AData、同花顺页面、巨潮资讯、腾讯行情、TDX 兜底源和本地缓存获取行情、股票画像、概念库和扫描快照，并通过 Flask + ECharts 提供本地 Web 工作台。

> 分析结果只用于研究和复盘，不构成投资建议。

## 当前工作区

- **候选池**：默认查看参与候选、风险验证和修复观察三类名单；排序基于个股信号/结构与宏观许可，行业和概念仅用于筛选及候选分布统计。
- **单股确认**：查看 K 线、综合信号、多周期确认、画像核对和交易计划。
- **数据后台**：管理扫描任务、历史快照、概念库、缓存清理和活跃数据源状态。

候选池为三个一级入口：参与候选 / 风险验证 / **修复观察**（2026-09-20 恢复）。底背离和修复线索同时作为候选标签、结构宽度证据和单股图表事件存在。

## 产品边界

当前保留：

- 本地日线/分钟线缓存和过期判断。
- 参与候选、风险验证、修复观察的底层扫描结果。
- 候选池个股排序、解释、交易计划和画像质量展示；行业/概念只作描述和筛选。
- 单股综合研判、60m/4h 辅助确认和止损/仓位规则。
- 数据后台中的扫描任务、历史快照、概念库和缓存治理。

当前裁剪或下沉：

- 主线、主线拆解、市场决策、`mainline_id` 筛选等旧契约已从当前产品面移除。
- 候选池为三池入口：参与候选 / 风险验证 / 修复观察（`bottom_div`，2026-09-20 恢复为一级 tab）。
- 同步批扫 `/api/scan_batch` 已退役（API 返回 410），统一使用后台扫描任务 `/api/scan_jobs`；旧同步批扫脚本已移除，不再保留旧 C 图面字段测试入口。
- 概念/板块关系图谱保留为实验性内部能力，不进入核心数据健康判断。
- 画像证据编辑器从候选详情中移除，候选详情只读展示画像质量。
- 历史快照、刷新策略和缓存治理统一留在数据后台。板块/概念行情共振与刷新入口已退役；旧服务端行情 API 返回 `410 Gone`，不参与排序、许可或工作台状态。

当前流程图见 [docs/current-feature-flow.md](/Users/vainve/股票短线分析软件/docs/current-feature-flow.md:1)，数据流见 [docs/data-flow.md](/Users/vainve/股票短线分析软件/docs/data-flow.md:1)，裁剪记录见 [docs/feature-simplification-audit.md](/Users/vainve/股票短线分析软件/docs/feature-simplification-audit.md:1)。

产品边界、读模型目标和文档权威顺序见 [docs/README.md](/Users/vainve/股票短线分析软件/docs/README.md:1)。

旧主线设计文档已归档到 [docs/archive](/Users/vainve/股票短线分析软件/docs/archive:1)，仅作为历史参考。

## 主要源码入口

- [app.py](/Users/vainve/股票短线分析软件/app.py:1)：本地 Web 主程序，提供候选池、单股分析、扫描任务和数据治理 API。
- [stock_analyzer/scan_workspace.py](/Users/vainve/股票短线分析软件/stock_analyzer/scan_workspace.py:1)：扫描工作区编排入口，负责汇总本地快照、行业/概念候选分布和响应。
- [stock_analyzer/scan_workspace_structure.py](/Users/vainve/股票短线分析软件/stock_analyzer/scan_workspace_structure.py:1)：生成行业/概念候选分布与覆盖统计，不计算市场共振分。
- [stock_analyzer/stock_service.py](/Users/vainve/股票短线分析软件/stock_analyzer/stock_service.py:1)：单股分析、画像、交易计划和多周期确认服务。
- [stock_analyzer/providers](/Users/vainve/股票短线分析软件/stock_analyzer/providers:1)：外部数据源适配层。
- [templates/index.html](/Users/vainve/股票短线分析软件/templates/index.html:1)：Flask 单页工作台模板。

## 环境准备

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 启动 Web 版

```bash
source venv/bin/activate
python app.py
```

默认监听：

```text
http://127.0.0.1:5009
```

如需从局域网其他设备或 devtunnel 访问，启动前显式设置绑定地址（注意：所有接口无鉴权，放开前确认网络环境）：

```bash
STOCK_ANALYZER_BIND_HOST=0.0.0.0 python app.py
```

页面默认进入候选工作台。切换到“单股确认”后，可输入 `600063`、`sh600063` 或 `600063.SH`，按 Enter 或开始分析加载该股票行情与信号。

## 常用 API

### 单股分析

```bash
curl "http://127.0.0.1:5009/api/single_stock_analysis?code=600063"
```

兼容接口 `/api/analyze` 仍保留；页面需临时回退时可在 URL 添加 `?single_stock_source=legacy`。

### 候选工作区

```bash
curl "http://127.0.0.1:5009/api/scan_workspace?limit=120"
```

该接口返回本地扫描结果、行业/概念候选分布、候选池和数据状态；板块行情与类别回放不在当前响应的决策链路中。

### 候选筛选

```bash
curl "http://127.0.0.1:5009/api/scan_workspace/candidates?scan_type=opportunity&sector=计算机"
```

支持按 `scan_type`、`sector`、`concept`、`query`、`limit`、`offset` 筛选本地快照候选。不再支持 `mainline_id`。

### 扫描任务

```bash
curl -X POST "http://127.0.0.1:5009/api/scan_jobs" \
  -H "Content-Type: application/json" \
  -d '{"scan_type":"opportunity","refresh_policy":"auto"}'
```

`refresh_policy` 支持：

- `auto`：增量更新，只补缺失、过期或旧策略结果。
- `cache`：仅读取本地结果。
- `force`：当前池全量重扫。

公开入口：

- `opportunity`：参与候选。
- `risk`：风险验证。
- `bottom_div`：修复观察池，作为候选池第三个一级 tab；只表达 C研/C修 观察语义，不代表入场许可。

## 测试

```bash
source venv/bin/activate
python -m unittest discover -s tests
```

当前测试覆盖无需联网的基础逻辑、扫描快照、候选工作区、数据治理、后台任务、图表序列化、画像证据、概念图谱内部能力和交易计划。
