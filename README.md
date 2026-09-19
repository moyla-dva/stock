# A股短线结构工作台

本项目是一个本地优先的 A 股短线研究与确认工作台。它当前不再提供“主线决策”功能，核心目标收敛为：

```text
扫描候选 -> 结构验证 -> 单股确认 -> 数据后台治理
```

系统使用 AkShare、AData、同花顺页面、巨潮资讯、腾讯行情、TDX 兜底源和本地缓存获取行情、股票画像、概念库、板块行情和扫描快照，并通过 Flask + ECharts 提供本地 Web 工作台。

> 分析结果只用于研究和复盘，不构成投资建议。

## 当前工作区

- **候选池**：默认查看参与候选和风险验证名单，按结构、确认、风险、板块/概念共振排序。
- **单股确认**：查看 K 线、综合信号、多周期确认、画像核对和交易计划。
- **数据后台**：管理扫描任务、历史快照、概念库、板块行情、缓存清理和数据源状态。

“修复观察”不再是一级入口。底背离和修复线索仍作为综合信号、候选标签、结构宽度证据和单股图表事件存在。

## 产品边界

当前保留：

- 本地日线/分钟线缓存和过期判断。
- 参与候选、风险验证、修复观察的底层扫描结果。
- 候选池排序、解释、交易计划和画像质量展示。
- 单股综合研判、60m/4h 辅助确认和止损/仓位规则。
- 数据后台中的扫描任务、历史快照、概念库、板块行情和缓存治理。

当前裁剪或下沉：

- 主线、主线拆解、市场决策、`mainline_id` 筛选等旧契约已从当前产品面移除。
- `bottom_div` 保留为内部兼容扫描类型，不再作为候选池一级 tab。
- 同步批扫 `/api/scan_batch` 已退役，统一使用后台扫描任务 `/api/scan_jobs`。
- 概念/板块关系图谱保留为实验性内部能力，不进入核心数据健康判断。
- 画像证据编辑器从候选详情中移除，候选详情只读展示画像质量。
- 回放校准、历史快照、刷新策略和缓存治理统一留在数据后台。

当前流程图见 [docs/current-feature-flow.md](/Users/vainve/股票短线分析软件/docs/current-feature-flow.md:1)，数据流见 [docs/data-flow.md](/Users/vainve/股票短线分析软件/docs/data-flow.md:1)，裁剪记录见 [docs/feature-simplification-audit.md](/Users/vainve/股票短线分析软件/docs/feature-simplification-audit.md:1)。

旧主线设计文档已归档到 [docs/archive](/Users/vainve/股票短线分析软件/docs/archive:1)，仅作为历史参考。

## 主要源码入口

- [app.py](/Users/vainve/股票短线分析软件/app.py:1)：本地 Web 主程序，提供候选池、单股分析、扫描任务和数据治理 API。
- [stock_analyzer/scan_workspace.py](/Users/vainve/股票短线分析软件/stock_analyzer/scan_workspace.py:1)：扫描工作区编排入口，负责汇总本地快照、结构、校准和响应。
- [stock_analyzer/scan_workspace_structure.py](/Users/vainve/股票短线分析软件/stock_analyzer/scan_workspace_structure.py:1)：市场结构、候选验证、真实宽度和板块/概念行情组装。
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

页面会默认分析 `600063`，也可以输入 `600063`、`sh600063` 或 `600063.SH`。

## 常用 API

### 单股分析

```bash
curl "http://127.0.0.1:5009/api/analyze?code=600063"
```

### 候选工作区

```bash
curl "http://127.0.0.1:5009/api/scan_workspace?limit=120"
```

该接口返回本地扫描结果、板块/概念结构、候选池、校准和数据状态。

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

公开入口建议使用：

- `opportunity`：参与候选。
- `risk`：风险验证。

内部兼容仍保留：

- `bottom_div`：修复观察底层扫描类型，不再作为候选池一级入口。

## 测试

```bash
source venv/bin/activate
python -m unittest discover -s tests
```

当前测试覆盖无需联网的基础逻辑、扫描快照、候选工作区、数据治理、后台任务、图表序列化、画像证据、概念图谱内部能力和交易计划。
