const prototypeStocks = [
  {
    code: "300829", name: "金丹科技", sector: "食品加工", pool: "opportunity",
    signal: "C突", permission: "breakout_allowed", plan: "计划就绪", score: 88,
    reason: "箱体上沿确认，量价条件已进入计划校验。", action: "等待次日价格确认",
    invalidation: "收盘跌回 14.62 下方", stop: "14.42", target: "17.30",
    missing: "次日不高开超过 3%", source: "tencent_direct", revision: "9d13a7",
    tags: ["计划就绪", "突破", "低风险"], base: 15.1, seed: 3,
  },
  {
    code: "600063", name: "皖维高新", sector: "化学纤维", pool: "opportunity",
    signal: "C回", permission: "pullback_allowed", plan: "计划就绪", score: 82,
    reason: "MA20 上方缩量回踩，结构未破坏。", action: "观察回踩承接",
    invalidation: "收盘跌破 5.41", stop: "5.35", target: "6.18",
    missing: "放量阳线重新站稳 5.68", source: "tencent_via_akshare", revision: "4fa28c",
    tags: ["计划就绪", "回踩", "MA20"], base: 5.62, seed: 8,
  },
  {
    code: "002410", name: "广联达", sector: "软件开发", pool: "risk",
    signal: "C风", permission: "forbidden", plan: "计划受阻", score: 76,
    reason: "结构下沿失守，风险条件先于入场条件成立。", action: "停止新增入场研判",
    invalidation: "重新收复 13.86 并确认", stop: "-", target: "-",
    missing: "修复结构尚未形成", source: "tdx", revision: "8b21e1",
    tags: ["计划受阻", "破位", "风险"], base: 13.2, seed: 13,
  },
  {
    code: "000858", name: "五粮液", sector: "白酒", pool: "repair",
    signal: "C修", permission: "structure_only", plan: "观察", score: 69,
    reason: "底背离后动能改善，尚未获得入场许可。", action: "等待结构确认",
    invalidation: "再次创出阶段新低", stop: "-", target: "-",
    missing: "低点抬高、矩形结构、触发 K", source: "tencent_direct", revision: "b74f2a",
    tags: ["修复观察", "底背离", "待确认"], base: 118.4, seed: 21,
  },
];

let selectedStock = prototypeStocks[0];
let currentPool = "all";
let activePeriod = "daily";
let chartInstance = null;

function stockByCode(code) {
  return prototypeStocks.find((item) => item.code === String(code).trim());
}

function buildSeries(stock, period) {
  const count = period === "daily" ? 92 : period === "60m" ? 72 : 60;
  const dates = [];
  const values = [];
  const closes = [];
  let price = stock.base * 0.9;
  const stepMs = period === "daily" ? 86400000 : period === "60m" ? 3600000 : 14400000;
  let cursor = new Date("2026-06-01T01:30:00Z").getTime();
  for (let index = 0; index < count; index += 1) {
    const wave = Math.sin((index + stock.seed) / 6) * stock.base * 0.008;
    const drift = stock.pool === "risk" && index > count * 0.66 ? -stock.base * 0.0022 : stock.base * 0.0011;
    const open = price + Math.sin(index * 1.7) * stock.base * 0.003;
    const close = Math.max(stock.base * 0.62, open + wave + drift);
    const high = Math.max(open, close) + stock.base * (0.008 + (index % 4) * 0.001);
    const low = Math.min(open, close) - stock.base * (0.007 + (index % 3) * 0.001);
    const date = new Date(cursor);
    dates.push(period === "daily" ? date.toISOString().slice(0, 10) : date.toISOString().slice(5, 16).replace("T", " "));
    values.push([open, close, low, high].map((value) => Number(value.toFixed(2))));
    closes.push(close);
    price = close;
    cursor += stepMs;
  }
  const ma = closes.map((_, index) => {
    const start = Math.max(0, index - 19);
    const windowValues = closes.slice(start, index + 1);
    return Number((windowValues.reduce((sum, value) => sum + value, 0) / windowValues.length).toFixed(2));
  });
  return { dates, values, ma };
}

function renderChart() {
  const element = document.getElementById("prototype-chart");
  if (!element || typeof echarts === "undefined") return;
  chartInstance = chartInstance || echarts.init(element);
  const data = buildSeries(selectedStock, activePeriod);
  const markerIndex = Math.max(8, data.dates.length - 9);
  const markerColor = selectedStock.pool === "risk" ? "#c84545" : selectedStock.pool === "repair" ? "#a96712" : "#087f69";
  chartInstance.setOption({
    animation: false,
    grid: [{ left: 54, right: 22, top: 42, bottom: 72 }],
    tooltip: { trigger: "axis", axisPointer: { type: "cross" }, backgroundColor: "rgba(24,32,28,.94)", borderWidth: 0, textStyle: { color: "#fff" } },
    xAxis: { type: "category", data: data.dates, boundaryGap: true, axisLine: { lineStyle: { color: "#aeb8b0" } }, axisLabel: { color: "#69736d", hideOverlap: true } },
    yAxis: { scale: true, splitLine: { lineStyle: { color: "#e5e9e4" } }, axisLabel: { color: "#69736d" } },
    dataZoom: [
      { type: "inside", start: 28, end: 100 },
      { type: "slider", start: 28, end: 100, height: 22, bottom: 20, borderColor: "#d8ded7", fillerColor: "rgba(8,127,105,.12)" },
    ],
    series: [
      {
        name: "K线", type: "candlestick", data: data.values,
        itemStyle: { color: "#e55353", color0: "#14a38b", borderColor: "#e55353", borderColor0: "#14a38b" },
        markPoint: {
          symbol: "pin", symbolSize: 46,
          label: { color: "#fff", fontWeight: 800, formatter: selectedStock.signal },
          itemStyle: { color: markerColor },
          data: [{ coord: [data.dates[markerIndex], data.values[markerIndex][1]], value: selectedStock.signal }],
        },
      },
      { name: "MA20", type: "line", data: data.ma, showSymbol: false, smooth: false, lineStyle: { width: 1.5, color: "#d7a52b" } },
    ],
  }, true);
}

function toneClass(stock) {
  if (stock.pool === "risk") return "risk";
  if (stock.pool === "repair") return "watch";
  return "ready";
}

function renderCandidateList() {
  const list = document.getElementById("candidate-list");
  if (!list) return;
  const query = (document.getElementById("candidate-search")?.value || "").trim().toLowerCase();
  const visible = prototypeStocks.filter((stock) => {
    const inPool = currentPool === "all" || stock.pool === currentPool;
    const matches = !query || `${stock.code}${stock.name}${stock.sector}`.toLowerCase().includes(query);
    return inPool && matches;
  });
  list.innerHTML = visible.map((stock, index) => `
    <button class="candidate-row ${stock.code === selectedStock.code ? "active" : ""}" data-code="${stock.code}">
      <span class="rank">${String(index + 1).padStart(2, "0")}</span>
      <span>
        <span class="candidate-name"><strong>${stock.name}</strong><small>${stock.code}</small></span>
        <span class="candidate-reason">${stock.reason}</span>
        <span class="row-tags">${stock.tags.map((tag) => `<span class="tag ${toneClass(stock)}">${tag}</span>`).join("")}</span>
      </span>
      <span class="score">${stock.score}</span>
    </button>
  `).join("") || `<div class="empty-state">没有符合当前筛选的样例候选</div>`;
  list.querySelectorAll("[data-code]").forEach((button) => {
    button.addEventListener("click", () => selectStock(button.dataset.code));
  });
}

function renderStockContext() {
  const values = {
    "stock-name": selectedStock.name,
    "stock-code": selectedStock.code,
    "stock-sector": selectedStock.sector,
    "stock-signal": `${selectedStock.signal} · ${selectedStock.plan}`,
    "stock-action": selectedStock.action,
    "stock-reason": selectedStock.reason,
    "stock-permission": selectedStock.permission,
    "stock-missing": selectedStock.missing,
    "stock-invalidation": selectedStock.invalidation,
    "stock-stop": selectedStock.stop,
    "stock-target": selectedStock.target,
    "stock-source": selectedStock.source,
    "stock-revision": selectedStock.revision,
  };
  Object.entries(values).forEach(([id, value]) => {
    document.querySelectorAll(`#${id}, [data-bind="${id}"]`).forEach((element) => {
      element.textContent = value;
    });
  });
  document.querySelectorAll("[data-stock-tone]").forEach((element) => {
    element.className = `tag ${toneClass(selectedStock)}`;
  });
}

function selectStock(code) {
  const stock = stockByCode(code);
  if (!stock) return;
  selectedStock = stock;
  renderCandidateList();
  renderStockContext();
  renderChart();
}

function setPool(pool, button) {
  currentPool = pool;
  document.querySelectorAll("[data-pool]").forEach((item) => item.classList.toggle("active", item === button));
  renderCandidateList();
}

function setPeriod(period, button) {
  activePeriod = period;
  document.querySelectorAll("[data-period]").forEach((item) => item.classList.toggle("active", item === button));
  renderChart();
}

function analyzePrototypeCode() {
  const input = document.getElementById("prototype-code-input");
  const stock = stockByCode(input?.value || "");
  if (stock) {
    selectStock(stock.code);
    renderCompactCandidates();
  }
  else if (input) {
    input.setCustomValidity("交互样例仅内置 300829、600063、002410、000858");
    input.reportValidity();
    setTimeout(() => input.setCustomValidity(""), 1200);
  }
}

function renderCompactCandidates() {
  const target = document.getElementById("compact-candidates");
  if (!target) return;
  target.innerHTML = prototypeStocks.filter((stock) => stock.code !== selectedStock.code).slice(0, 3).map((stock) => `
    <button class="compact-candidate" data-compact-code="${stock.code}">
      <strong>${stock.name} ${stock.code} <span class="tag ${toneClass(stock)}">${stock.signal}</span></strong>
      <span>${stock.action} · ${stock.score} 分</span>
    </button>
  `).join("");
  target.querySelectorAll("[data-compact-code]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById("prototype-code-input");
      if (input) input.value = button.dataset.compactCode;
      selectStock(button.dataset.compactCode);
      renderCompactCandidates();
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  renderCandidateList();
  renderStockContext();
  renderCompactCandidates();
  renderChart();
  document.getElementById("candidate-search")?.addEventListener("input", renderCandidateList);
  document.getElementById("prototype-code-input")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") analyzePrototypeCode();
  });
  window.addEventListener("resize", () => chartInstance?.resize());
});
