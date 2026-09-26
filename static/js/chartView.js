var myChart = echarts.init(document.getElementById('chart-container'));
var timeframeRequestControllers = {};

function abortDeferredTimeframeRequests() {
    Object.keys(timeframeRequestControllers).forEach(function(period) {
        var controller = timeframeRequestControllers[period];
        if (controller) controller.abort();
    });
    timeframeRequestControllers = {};
}

function createTimeframeRequestController(period) {
    if (typeof AbortController === 'undefined') return null;
    if (timeframeRequestControllers[period]) {
        timeframeRequestControllers[period].abort();
    }
    var controller = new AbortController();
    timeframeRequestControllers[period] = controller;
    return controller;
}

function rerenderInspectorSignalBoard() {
    var viewData = analysisStore.getViewData();
    if (!viewData || typeof renderSignalBoard !== 'function') return;
    var allMarkPoints = getModeMarkPoints(viewData);
    var activeMarkPoints = allMarkPoints.filter(isPointActive);
    renderSignalBoard(allMarkPoints, activeMarkPoints);
}

function setInspectorHoverSignalDate(date) {
    var next = date || null;
    if (activeHoverSignalDate === next) return;
    activeHoverSignalDate = next;
    rerenderInspectorSignalBoard();
}

function updateChartSignalViewState() {
    ['focus', 'full'].forEach(function(view) {
        var el = document.getElementById('chart-view-' + view);
        if (el) el.classList.toggle('active', chartSignalView === view);
    });
}

function updateChartPositionViewState() {
    var view = getChartPositionView();
    ['flat', 'position'].forEach(function(positionView) {
        var el = document.getElementById('chart-position-' + positionView);
        if (!el) return;
        var active = view === positionView;
        el.classList.toggle('active', active);
        el.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

function setChartSignalView(view) {
    chartSignalView = view === 'full' ? 'full' : 'focus';
    updateChartSignalViewState();
    var rootData = analysisStore.getCurrentChartData();
    if (rootData) {
        renderChart(rootData);
    }
}

function setChartPositionView(view) {
    analysisStore.setChartPositionView(view);
    updateChartPositionViewState();
    var rootData = analysisStore.getCurrentChartData();
    if (rootData) {
        renderChart(rootData);
    }
}

function chartPeriodMeta(period) {
    if (period === '60m') return { key: '60m', id: 'chart-period-60m', label: '60m', summaryKey: 'hour_1' };
    if (period === '4h') return { key: '4h', id: 'chart-period-4h', label: '4h', summaryKey: 'hour_4' };
    return { key: 'daily', id: 'chart-period-daily', label: '日线', summaryKey: 'daily' };
}

function chartPayloadForPeriod(root, period) {
    if (!root) return null;
    if (period === 'daily') return root;
    var meta = chartPeriodMeta(period);
    var summary = root.multi_timeframes && root.multi_timeframes[meta.summaryKey];
    return summary && summary.chart ? summary.chart : null;
}

function chartSummaryForPeriod(root, period) {
    if (!root || period === 'daily') return null;
    var meta = chartPeriodMeta(period);
    return root.multi_timeframes && root.multi_timeframes[meta.summaryKey] ? root.multi_timeframes[meta.summaryKey] : null;
}

function chartPeriodAvailable(root, period) {
    if (period === 'daily') return true;
    return !!chartPayloadForPeriod(root, period);
}

function chartPeriodLoadable(root, period) {
    if (!root || period === 'daily') return false;
    return !!(root.stock_code || root.stock_name);
}

function chartPeriodLoading(period) {
    var meta = chartPeriodMeta(period);
    return Boolean(analysisStore.getTimeframePromise(meta.key));
}

function mergeTimeframePayload(root, payload) {
    if (!root || !payload || !payload.multi_timeframes) return;
    if (analysisStore.getRootData() === root) {
        analysisStore.mergeTimeframes(payload);
    }
}

function loadDeferredTimeframeCharts(period) {
    var root = analysisStore.getCurrentChartData();
    var meta = chartPeriodMeta(period);
    if (!root || !chartPeriodLoadable(root, meta.key)) {
        setChartState(meta.label + ' 暂无可用K线数据');
        return null;
    }
    var existingPromise = analysisStore.getTimeframePromise(meta.key);
    if (existingPromise) {
        setChartState(meta.label + ' 确认层加载中');
        return existingPromise;
    }

    var code = normalizeChartStockCode(root.stock_code || root.stock_name);
    if (!code) {
        setChartState(meta.label + ' 缺少股票代码');
        return null;
    }
    var timeframeRequest = analysisStore.beginTimeframeLoad(meta.key, code);
    if (!timeframeRequest && meta.key !== 'daily') {
        return null;
    }
    setChartState('正在加载 ' + meta.label + ' 确认层');
    updateChartPeriodState(root);

    var requestController = createTimeframeRequestController(meta.key);
    var loadPromise = fetchAnalysisTimeframes(code, meta.key, requestController ? { signal: requestController.signal } : undefined)
        .then(function(payload) {
            if (!analysisStore.isTimeframeRequestCurrent(timeframeRequest)) {
                return;
            }
            if (!payload || payload.error) {
                throw new Error(payload && payload.error ? payload.error : '分时确认层返回为空');
            }
            var currentRoot = analysisStore.getRootData() || root;
            if (normalizeChartStockCode(currentRoot.stock_code || currentRoot.stock_name) !== code) {
                return;
            }
            mergeTimeframePayload(currentRoot, payload);
            if (chartPeriodAvailable(currentRoot, meta.key)) {
                if (analysisStore.getActivePeriod() === meta.key) {
                    renderChart(currentRoot);
                } else {
                    updateChartPeriodState(currentRoot);
                }
            } else {
                if (analysisStore.getActivePeriod() === meta.key) {
                    analysisStore.setActivePeriod('daily');
                    renderChart(currentRoot);
                    setChartState(meta.label + ' 暂无可用K线数据');
                } else {
                    updateChartPeriodState(currentRoot);
                }
            }
        })
        .catch(function(err) {
            if (typeof isRequestCancelled === 'function' && isRequestCancelled(err)) {
                return;
            }
            if (!analysisStore.failTimeframeLoad(timeframeRequest, err)) {
                return;
            }
            updateChartPeriodState(analysisStore.getRootData() || root);
            setChartState(meta.label + ' 确认层加载失败: ' + err.message);
        })
        .finally(function() {
            analysisStore.finishTimeframeLoad(timeframeRequest);
            if (timeframeRequestControllers[meta.key] === requestController) {
                delete timeframeRequestControllers[meta.key];
            }
            updateChartPeriodState(analysisStore.getRootData() || root);
        });
    analysisStore.attachTimeframePromise(timeframeRequest, loadPromise);
    return loadPromise;
}

function buildChartPeriodData(root, period) {
    var frame = chartPayloadForPeriod(root, period);
    if (!frame) return null;
    var meta = chartPeriodMeta(period);
    var merged = Object.assign({}, root, frame);
    merged.stock_code = root.stock_code;
    merged.stock_name = root.stock_name;
    merged.stock_sector = root.stock_sector;
    merged.stock_concepts = root.stock_concepts;
    merged.trade_plan = root.trade_plan;
    merged.multi_timeframes = root.multi_timeframes;
    merged.signal_definitions = root.signal_definitions || frame.signal_definitions;
    merged.chart_period = meta.key;
    merged.chart_period_label = meta.label;
    merged._chart_period_view = true;
    return merged;
}

function updateChartPeriodState(root) {
    var currentPeriod = analysisStore.getActivePeriod();
    ['daily', '60m', '4h'].forEach(function(period) {
        var meta = chartPeriodMeta(period);
        var button = document.getElementById(meta.id);
        if (!button) return;
        var available = chartPeriodAvailable(root, period);
        var loadable = chartPeriodLoadable(root, period);
        var loading = chartPeriodLoading(period);
        button.classList.toggle('active', currentPeriod === period);
        button.classList.toggle('is-loading', loading);
        button.classList.toggle('is-deferred', !available && loadable);
        button.disabled = !available && !loadable;
        button.title = available
            ? meta.label + ' 已载入'
            : (loadable ? '点击加载 ' + meta.label + ' 确认层' : meta.label + ' 暂无可用K线数据');
        button.setAttribute('aria-pressed', currentPeriod === period ? 'true' : 'false');
    });
}

function setChartPeriod(period) {
    period = chartPeriodMeta(period).key;
    var root = analysisStore.getCurrentChartData();
    if (root && period !== 'daily' && chartPeriodLoading(period)) {
        analysisStore.setActivePeriod(period);
        updateChartPeriodState(root);
        setChartState(chartPeriodMeta(period).label + ' 确认层加载中');
        return;
    }
    if (root && !chartPeriodAvailable(root, period)) {
        if (chartPeriodLoadable(root, period)) {
            analysisStore.setActivePeriod(period);
            updateChartPeriodState(root);
            loadDeferredTimeframeCharts(period);
            return;
        }
        setChartState(chartPeriodMeta(period).label + ' 暂无可用K线数据');
        updateChartPeriodState(root);
        return;
    }
    analysisStore.setActivePeriod(period);
    updateChartPeriodState(root);
    if (root) {
        renderChart(root);
    }
}

function focusSignal(date) {
    var viewData = analysisStore.getViewData();
    if (!viewData || !date || !viewData.dates) return false;
    var idx = viewData.dates.indexOf(date);
    if (idx < 0) return false;
    activeHoverSignalDate = null;
    activeInspectorSignalDate = date;
    var total = Math.max(1, viewData.dates.length - 1);
    var start = Math.max(0, ((idx - 30) / total) * 100);
    var end = Math.min(100, ((idx + 30) / total) * 100);
    [0, 1].forEach(function(dataZoomIndex) {
        myChart.dispatchAction({
            type: 'dataZoom',
            dataZoomIndex: dataZoomIndex,
            start: start,
            end: end
        });
    });
    myChart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: idx });
    rerenderInspectorSignalBoard();
    return true;
}

function scanFocusColor(focus) {
    if (!focus) return '#202421';
    if (focus.scanType === 'risk') return '#c83737';
    if (focus.scanType === 'bottom_div') return '#2d63e6';
    return '#7c3aed';
}

function getActiveScanFocusForChart(data, dates) {
    if (!activeScanChartFocus || !data || !dates || !dates.length) return null;
    if (!scanChartFocusMatchesCode(data.stock_code || data.stock_name)) return null;
    if (dates.indexOf(activeScanChartFocus.date) < 0) return null;
    return activeScanChartFocus;
}

function getKLineAtDate(data, dates, date) {
    var index = dates.indexOf(date);
    if (index < 0) return null;
    return (data.k_data || [])[index] || null;
}

function buildScanFocusMarkPoint(data, dates, focus) {
    if (!focus) return null;
    var kLine = getKLineAtDate(data, dates, focus.date) || [];
    var close = Number.isFinite(Number(focus.price)) ? Number(focus.price) : Number(kLine[1]);
    var high = Number(kLine[3]);
    var y = Number.isFinite(high) ? Math.max(close, high) * 1.04 : close;
    if (!Number.isFinite(y)) return null;

    var color = scanFocusColor(focus);
    return {
        name: '扫描定位',
        signalKey: 'scan_focus',
        signalLabel: focus.signalLabel || '扫描',
        signalCategory: focus.scanType === 'risk' ? 'risk' : 'entry',
        date: focus.date,
        coord: [focus.date, y],
        price: close,
        reason: focus.reason || focus.signalName || '',
        symbol: 'pin',
        symbolSize: 54,
        symbolOffset: [0, -22],
        itemStyle: {
            color: color,
            borderColor: '#fff',
            borderWidth: 2,
            shadowBlur: 10,
            shadowColor: 'rgba(32, 36, 33, 0.28)'
        },
        label: {
            show: true,
            formatter: focus.signalLabel || '扫描',
            color: '#fff',
            fontSize: 11,
            fontWeight: 'bold'
        }
    };
}

function scanFocusStateText(focus) {
    if (!focus) return '';
    var parts = ['扫描定位', focus.poolTitle || '扫描候选', focus.signalLabel || ''];
    if (focus.historySnapshotDay) parts.splice(1, 0, '历史信号日');
    return parts.filter(Boolean).join(' · ');
}

function formatChartPercent(value, digits) {
    if (value == null || Number.isNaN(Number(value))) return '-';
    var number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits == null ? 1 : digits) + '%' : '-';
}

function chartDataStatusText(data) {
    if (data.chart_period && data.chart_period !== 'daily') return '';
    var identity = data.data_identity || {};
    var state = identity.bar_state || 'unknown';
    var source = identity.data_source || '';
    var stateText = {
        closed: '已收盘',
        preview: source.indexOf('tencent_realtime') >= 0 ? '盘中实时' : '盘中预览',
        mixed: '含盘中数据',
        unknown: '状态未知'
    }[state] || '状态未知';
    var sourceText = source.indexOf('tencent_realtime') >= 0
        ? '腾讯实时行情'
        : source.indexOf('tencent') >= 0
            ? '腾讯行情'
            : source && source !== 'unknown'
                ? source
                : '';
    return '日线 ' + stateText + (sourceText ? ' · ' + sourceText : '');
}

function updateChartHeader(data, dates) {
    var focus = getActiveScanFocusForChart(data, dates);
    var periodLabel = data.chart_period_label || '日线';
    if (dates.length > 0) {
        var freshness = chartDataStatusText(data);
        setText('data-window', dates[0] + ' 至 ' + dates[dates.length - 1] + (freshness ? ' · ' + freshness : ''));
        setText('chart-context-label', getModeText() + ' · ' + periodLabel + (focus ? ' · SCAN FOCUS' : ' · SIGNAL MAP'));
        setText('chart-title', (data.stock_name || data.stock_code || '价格') + ' ' + periodLabel + '价格结构');
    } else {
        setText('data-window', '数据窗口: -');
        setText('chart-context-label', getModeText() + ' · ' + periodLabel + ' · SIGNAL MAP');
        setText('chart-title', '价格结构');
    }
}

function updateChartStats(data) {
    var markCount = getModeMarkPoints(data).length;
    setText('stat-signals', markCount);

    var stats = (data.event_stats || {}).v2 || {};
    var bySignal = stats.by_signal || {};
    var sampleCount = 0;
    var winRateSum = 0;
    var avgRetSum = 0;
    Object.keys(bySignal).forEach(function(key) {
        var item = bySignal[key] || {};
        var count = Number(item.evaluated_count || 0);
        if (count > 0) {
            sampleCount += count;
            winRateSum += Number(item.win_rate || 0) * count;
            avgRetSum += Number(item.avg_ret || 0) * count;
        }
    });
    if (sampleCount > 0) {
        var horizonUnit = data.chart_period === 'daily' ? '日' : '根';
        var horizon = stats.horizon == null ? 5 : stats.horizon;
        setText(
            'stat-detail',
            'V2 ' + sampleCount + ' 样本 / ' + horizon + horizonUnit
            + ' · 事件后上涨 ' + (winRateSum / sampleCount).toFixed(1) + '%'
            + ' / 平均涨跌 ' + (avgRetSum / sampleCount).toFixed(2) + '%'
        );
    } else {
        setText('stat-detail', '-');
    }
}

function buildVisibleMarkPoints(data, dates, scanFocus) {
    var rawMarkPoints = getModeMarkPoints(data);
    var allMarkPoints = annotateChartDisplayContext(rawMarkPoints);
    var activeMarkPoints = annotateChartDisplayContext(rawMarkPoints.filter(isPointActive), rawMarkPoints);
    var chartSourcePoints = chartSignalView === 'focus'
        ? selectFocusChartPoints(activeMarkPoints, dates)
        : activeMarkPoints;
    var markPoints = chartSourcePoints.map(function(point) {
        return styleChartPoint(point, chartSignalView);
    });
    var scanFocusPoint = buildScanFocusMarkPoint(data, dates, scanFocus);
    if (scanFocusPoint) {
        markPoints.push(scanFocusPoint);
    }

    renderSignalBoard(allMarkPoints, activeMarkPoints);

    if (dates.length > 0) {
        var viewText = chartSignalView === 'focus' ? '核心' : '全部';
        var positionText = getChartPositionView() === 'position' ? '信号后跟踪' : '入场研判';
        var focusText = scanFocus ? ' · ' + scanFocusStateText(scanFocus) : '';
        var unitText = data.chart_period === 'daily' ? '日' : '根';
        setChartState('已载入 ' + dates.length + ' ' + unitText + ' · ' + (data.chart_period_label || '日线') + ' · ' + positionText + ' · ' + viewText + ' ' + chartSourcePoints.length + '/' + activeMarkPoints.length + focusText);
    } else {
        setChartState('无数据');
    }

    return markPoints;
}

function defaultChartZoomStart(data, totalDays) {
    if (!totalDays) return 0;
    var visibleBars = 365;
    if (data.chart_period === '60m') {
        visibleBars = 160;
    } else if (data.chart_period === '4h') {
        visibleBars = 120;
    }
    return totalDays > visibleBars ? Math.round((1 - visibleBars / totalDays) * 100) : 0;
}

function renderChart(data) {
    if (data && data.multi_timeframes && !data._chart_period_view) {
        analysisStore.setRootData(data);
    }
    var rootData = analysisStore.getRootData() || data;
    var currentPeriod = analysisStore.getActivePeriod();
    if (!chartPeriodAvailable(rootData, currentPeriod)) {
        currentPeriod = 'daily';
        analysisStore.setActivePeriod(currentPeriod);
    }
    updateChartPeriodState(rootData);
    data = buildChartPeriodData(rootData, currentPeriod) || rootData;
    analysisStore.setViewData(data);
    mergeSignalDefinitions(data.signal_definitions);
    renderScoreSummary(data.score_summary);
    setText('stock-title', data.stock_name || data.stock_code || '未知股票');
    var concepts = Array.isArray(data.stock_concepts) ? data.stock_concepts.slice(0, 3).join(' / ') : '';
    setText('stock-sector', '板块: ' + (data.stock_sector || '-') + (concepts ? ' · 概念: ' + concepts : ''));
    updateModeState();
    updateChartSignalViewState();
    updateChartPositionViewState();
    if (typeof renderStockTagProfile === 'function') {
        renderStockTagProfile(data.tag_profile || null);
    }

    var dates = data.dates || [];
    var scanFocus = getActiveScanFocusForChart(data, dates);
    updateChartHeader(data, dates);
    updateChartStats(data);

    var markPoints = buildVisibleMarkPoints(data, dates, scanFocus);
    var totalDays = dates.length;
    var defaultStart = defaultChartZoomStart(data, totalDays);
    if (typeof renderMultiTimeframeBoard === 'function') {
        renderMultiTimeframeBoard(data.multi_timeframes || null);
    }
    myChart.setOption(buildChartOption(data, dates, markPoints, defaultStart, scanFocus));
}

window.onresize = function() {
    myChart.resize();
};

myChart.on('mouseover', function(params) {
    if (!params || params.componentType !== 'markPoint' || !params.data) return;
    if (params.data.signalKey === 'scan_focus') return;
    setInspectorHoverSignalDate(params.data.date || null);
});

myChart.on('mouseout', function(params) {
    if (!params || params.componentType !== 'markPoint') return;
    setInspectorHoverSignalDate(null);
});

myChart.on('globalout', function() {
    setInspectorHoverSignalDate(null);
});

myChart.on('click', function(params) {
    if (!params || params.componentType !== 'markPoint' || !params.data) return;
    if (!params.data.date) return;
    focusSignal(params.data.date);
});
