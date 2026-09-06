var signalMode = 'composite';
var chartSignalView = 'focus';
var workspaceView = 'candidates';
var deskView = 'scan';
var inspectorView = 'overview';
var lastData = null;
var lastAnalysisData = null;
var activeChartPeriod = 'daily';
var pendingFocusDate = null;
var activeScanChartFocus = null;
var activeInspectorSignalDate = null;
var activeHoverSignalDate = null;
var activeSignalKeys = {};
var signalMeta = {};

function getModeText(mode) {
    return '综合研判';
}

function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.innerText = text;
}

function setDeskStatus(text) {
    setText('loading', text);
}

function setChartState(text) {
    setText('chart-state', text);
}

function normalizeChartStockCode(code) {
    var match = String(code || '').match(/\d{6}/);
    return match ? match[0] : String(code || '').trim();
}

function setActiveScanChartFocus(item) {
    if (!item) {
        activeScanChartFocus = null;
        activeInspectorSignalDate = null;
        activeHoverSignalDate = null;
        return;
    }
    var queue = typeof scanCandidateQueue === 'function' ? scanCandidateQueue(item) : null;
    var role = typeof scanCandidateRole === 'function' ? scanCandidateRole(item) : null;
    activeScanChartFocus = {
        code: normalizeChartStockCode(item.code),
        name: item.name || item.code || '',
        date: item.event_date || item.date || '',
        dataDate: item.data_date || item.date || '',
        price: item.price == null ? null : Number(item.price),
        signalLabel: item.signal_label || item.signal || '扫描',
        signalName: item.signal_name || '',
        reason: item.reason || '',
        scanType: item._scan_type || item.scan_type || '',
        poolTitle: item._pool_title || '',
        historySnapshotDay: item._history_snapshot_day || '',
        sector: item.sector || '',
        concepts: Array.isArray(item.concepts) ? item.concepts.slice(0, 4) : [],
        queueLabel: queue ? queue.label : '',
        queueDetail: queue ? queue.detail : '',
        roleLabel: role ? role.label : '',
        roleAction: role ? role.action : '',
        roleTone: role ? role.tone : ''
    };
    activeInspectorSignalDate = activeScanChartFocus.date || null;
    activeHoverSignalDate = null;
}

function clearActiveScanChartFocus() {
    activeScanChartFocus = null;
    activeInspectorSignalDate = null;
    activeHoverSignalDate = null;
}

function getInspectorSignalDate() {
    return activeHoverSignalDate || activeInspectorSignalDate || null;
}

function scanChartFocusMatchesCode(code) {
    return Boolean(activeScanChartFocus)
        && normalizeChartStockCode(activeScanChartFocus.code) === normalizeChartStockCode(code);
}

function updateModeState() {
    var modeText = getModeText(signalMode);
    setText('active-mode-label', modeText);
    setText('legend-mode-label', modeText);
    if (typeof updateScanButtonLabel === 'function') {
        updateScanButtonLabel();
    }
}

function updateInspectorViewState() {
    ['overview', 'legend', 'events'].forEach(function(view) {
        var tab = document.getElementById('inspector-tab-' + view);
        var panel = document.getElementById('inspector-view-' + view);
        var active = inspectorView === view;
        if (tab) {
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        }
        if (panel) panel.classList.toggle('active', active);
    });
}

function setInspectorView(view) {
    var valid = ['overview', 'legend', 'events'];
    inspectorView = valid.indexOf(view) >= 0 ? view : 'overview';
    updateInspectorViewState();
}

function updateDeskViewState() {
    document.body.setAttribute('data-desk', deskView);
    document.body.setAttribute('data-workspace', workspaceView);
    ['candidates', 'analysis', 'data'].forEach(function(view) {
        var tab = document.getElementById('workspace-tab-' + view);
        var active = workspaceView === view;
        if (tab) {
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        }
    });
    ['analysis', 'scan'].forEach(function(view) {
        var panel = document.getElementById('desk-view-' + view);
        var active = deskView === view;
        if (panel) panel.classList.toggle('active', active);
    });
}

function normalizeWorkspaceView(view) {
    return ['candidates', 'analysis', 'data'].indexOf(view) >= 0 ? view : 'candidates';
}

function deskForWorkspace(view) {
    return view === 'analysis' ? 'analysis' : 'scan';
}

function getWorkspaceView() {
    return workspaceView;
}

function syncWorkspaceContext(view, options) {
    options = options || {};
    if (options.preserveScanContext) return;
    if (typeof applyScanNavigationState === 'function') {
        applyScanNavigationState({workspace: view, useDefaults: true});
        if (view === 'data') {
            if (typeof loadScanJobHistory === 'function') loadScanJobHistory();
            if (typeof loadScanHistory === 'function') loadScanHistory();
        }
        return;
    }
    if (view === 'candidates') {
        if (typeof scanWorkspaceState !== 'undefined') {
            scanWorkspaceState.sideView = 'detail';
        }
    } else if (view === 'data') {
        if (typeof scanWorkspaceState !== 'undefined') {
            scanWorkspaceState.sideView = 'detail';
        }
        if (typeof loadScanJobHistory === 'function') loadScanJobHistory();
        if (typeof loadScanHistory === 'function') loadScanHistory();
    }
}

function setWorkspaceView(view, options) {
    options = options || {};
    workspaceView = normalizeWorkspaceView(view);
    deskView = deskForWorkspace(workspaceView);
    updateDeskViewState();
    syncWorkspaceContext(workspaceView, options);
    if (!options.skipRender && deskView === 'scan' && typeof renderScanWorkspace === 'function') {
        renderScanWorkspace();
    }
    if (deskView === 'analysis' && typeof myChart !== 'undefined') {
        setTimeout(function() {
            myChart.resize();
        }, 0);
    }
}

function setDeskView(view) {
    setWorkspaceView(view === 'analysis' ? 'analysis' : 'candidates');
}

function handleKeyPress(event) {
    if (event.key === 'Enter') {
        analyzeStock();
    }
}

function setSignalMode(mode) {
    signalMode = 'composite';
    updateModeState();
    if (lastData) {
        renderChart(lastData);
    }
}

function analyzeStock(options) {
    options = options || {};
    var code = document.getElementById('stock-code').value.trim();
    if (!code) return;
    if (activeScanChartFocus && !scanChartFocusMatchesCode(code)) {
        clearActiveScanChartFocus();
    }

    var btn = document.getElementById('btn-analyze');
    btn.disabled = true;
    setDeskStatus('分析中');
    setChartState('加载数据');

    return analyzeStockData(code)
        .then(function(data) {
            if (data.error) {
                setDeskStatus('分析失败');
                setChartState('返回错误');
                alert('错误: ' + data.error);
                return;
            }
            renderChart(data);
            if (pendingFocusDate && typeof focusSignal === 'function') {
                var focused = focusSignal(pendingFocusDate);
                if (focused && activeScanChartFocus) {
                    var historyText = activeScanChartFocus.historySnapshotDay ? ' · 历史结果' : '';
                    setChartState('已定位扫描候选' + historyText + ' · ' + activeScanChartFocus.signalLabel + ' · ' + activeScanChartFocus.date);
                }
                pendingFocusDate = null;
            }
            setDeskStatus('已更新');
        })
        .catch(function(err) {
            setDeskStatus('请求失败');
            setChartState('请求失败');
            alert('请求失败: ' + err.message);
        })
        .finally(function() {
            btn.disabled = false;
        });
}

window.onload = function() {
    updateModeState();
    updateDeskViewState();
    updateInspectorViewState();
    if (typeof loadScanWorkspace === 'function') {
        loadScanWorkspace();
    }
    if (typeof loadScanJobHistory === 'function') {
        loadScanJobHistory();
    }
    if (typeof loadScanHistory === 'function') {
        loadScanHistory();
    }
    if (typeof loadStockConceptStatus === 'function') {
        loadStockConceptStatus();
    }
    if (typeof loadDataSourceStatus === 'function') {
        loadDataSourceStatus();
    }
    analyzeStock();
};
