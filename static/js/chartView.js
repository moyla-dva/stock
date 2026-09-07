var myChart = echarts.init(document.getElementById('chart-container'));

function rerenderInspectorSignalBoard() {
    if (!lastData || typeof renderSignalBoard !== 'function') return;
    var allMarkPoints = getModeMarkPoints(lastData);
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

function setChartSignalView(view) {
    chartSignalView = view === 'full' ? 'full' : 'focus';
    updateChartSignalViewState();
    if (lastData) {
        renderChart(lastData);
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

function chartPeriodAvailable(root, period) {
    if (period === 'daily') return true;
    return !!chartPayloadForPeriod(root, period);
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
    ['daily', '60m', '4h'].forEach(function(period) {
        var meta = chartPeriodMeta(period);
        var button = document.getElementById(meta.id);
        if (!button) return;
        var available = chartPeriodAvailable(root, period);
        button.classList.toggle('active', activeChartPeriod === period);
        button.disabled = !available;
        button.setAttribute('aria-pressed', activeChartPeriod === period ? 'true' : 'false');
    });
}

function setChartPeriod(period) {
    period = chartPeriodMeta(period).key;
    var root = lastAnalysisData || lastData;
    if (root && !chartPeriodAvailable(root, period)) {
        setChartState(chartPeriodMeta(period).label + ' 暂无可用K线数据');
        updateChartPeriodState(root);
        return;
    }
    activeChartPeriod = period;
    updateChartPeriodState(root);
    if (root) {
        renderChart(root);
    }
}

function focusSignal(date) {
    if (!lastData || !date || !lastData.dates) return false;
    var idx = lastData.dates.indexOf(date);
    if (idx < 0) return false;
    activeHoverSignalDate = null;
    activeInspectorSignalDate = date;
    var total = Math.max(1, lastData.dates.length - 1);
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

function updateChartHeader(data, dates) {
    var focus = getActiveScanFocusForChart(data, dates);
    var periodLabel = data.chart_period_label || '日线';
    if (dates.length > 0) {
        setText('data-window', dates[0] + ' 至 ' + dates[dates.length - 1]);
        setText('chart-context-label', getModeText(signalMode) + ' · ' + periodLabel + (focus ? ' · SCAN FOCUS' : ' · SIGNAL MAP'));
        setText('chart-title', (data.stock_name || data.stock_code || '价格') + ' ' + periodLabel + '价格结构');
    } else {
        setText('data-window', '数据窗口: -');
        setText('chart-context-label', getModeText(signalMode) + ' · ' + periodLabel + ' · SIGNAL MAP');
        setText('chart-title', '价格结构');
    }
}

function updateChartStats(data) {
    var compositeCount = getModeMarkPoints(data).length;
    setText('stat-composite', compositeCount);

    var stats = data.stats_composite;

    if (stats && stats.b) {
        var horizonUnit = data.chart_period === 'daily' ? '日' : '根';
        var horizon = (stats.b.horizon == null) ? '-' : stats.b.horizon + horizonUnit;
        var bWin = formatChartPercent(stats.b.win_rate, 1);
        var bRet = formatChartPercent(stats.b.avg_ret, 2);
        var sWin = stats.s ? formatChartPercent(stats.s.win_rate, 1) : '-';
        var sRet = stats.s ? formatChartPercent(stats.s.avg_ret, 2) : '-';
        setText('stat-detail', horizon + ' B ' + bWin + ' / ' + bRet + ' | 离场 ' + sWin + ' / ' + sRet);
    } else {
        setText('stat-detail', '-');
    }
}

function buildVisibleMarkPoints(data, dates, scanFocus) {
    var allMarkPoints = getModeMarkPoints(data);
    var activeMarkPoints = allMarkPoints.filter(isPointActive);
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
        var focusText = scanFocus ? ' · ' + scanFocusStateText(scanFocus) : '';
        var unitText = data.chart_period === 'daily' ? '日' : '根';
        setChartState('已载入 ' + dates.length + ' ' + unitText + ' · ' + (data.chart_period_label || '日线') + ' · ' + viewText + ' ' + chartSourcePoints.length + '/' + activeMarkPoints.length + focusText);
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
        lastAnalysisData = data;
    }
    var rootData = lastAnalysisData || data;
    if (!chartPeriodAvailable(rootData, activeChartPeriod)) {
        activeChartPeriod = 'daily';
    }
    updateChartPeriodState(rootData);
    data = buildChartPeriodData(rootData, activeChartPeriod) || rootData;
    lastData = data;
    mergeSignalDefinitions(data.signal_definitions);
    renderScoreSummary(data.score_summary);
    setText('stock-title', data.stock_name || data.stock_code || '未知股票');
    var concepts = Array.isArray(data.stock_concepts) ? data.stock_concepts.slice(0, 3).join(' / ') : '';
    setText('stock-sector', '板块: ' + (data.stock_sector || '-') + (concepts ? ' · 概念: ' + concepts : ''));
    updateModeState();
    updateChartSignalViewState();
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
