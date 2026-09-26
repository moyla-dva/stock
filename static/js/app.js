var chartSignalView = 'focus';
var workspaceView = 'candidates';
var deskView = 'scan';
var inspectorView = 'overview';
var pendingFocusDate = null;
var activeScanChartFocus = null;
var activeInspectorSignalDate = null;
var activeHoverSignalDate = null;
var activeSignalKeys = {};
var signalMeta = {};
var activeAnalysisController = null;
var autoAnalyzeTimer = null;
var lastAutoAnalyzedCode = '';
var AUTO_ANALYZE_DEBOUNCE_MS = 500;

function getModeText() {
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
    var signalText = typeof scanDisplaySignalText === 'function'
        ? scanDisplaySignalText(item)
        : ((item.signal_label || item.signal || '扫描') + ' ' + (item.signal_name || '')).trim();
    activeScanChartFocus = {
        code: normalizeChartStockCode(item.code),
        name: item.name || item.code || '',
        date: item.event_date || item.date || '',
        dataDate: item.data_date || item.date || '',
        price: item.price == null ? null : Number(item.price),
        signal: item.signal || '',
        signal_label: item.signal_label || '',
        signal_name: item.signal_name || '',
        signal_key: item.signal_key || '',
        v2_signal: item.v2_signal || '',
        v2_signal_name: item.v2_signal_name || '',
        v2_state: item.v2_state || '',
        v2_state_label: item.v2_state_label || '',
        v2_role: item.v2_role || '',
        v2_role_label: item.v2_role_label || '',
        v2_tone: item.v2_tone || '',
        v2_state_model: item.v2_state_model || null,
        v2_permission: item.v2_permission || '',
        v2_queue: item.v2_queue || '',
        v2_queue_label: item.v2_queue_label || '',
        candidate_substate: item.candidate_substate || '',
        candidate_substate_label: item.candidate_substate_label || '',
        candidate_display_label: item.candidate_display_label || '',
        candidate_confirmation_price: item.candidate_confirmation_price,
        candidate_invalidation_price: item.candidate_invalidation_price,
        candidate_missing_confirmations: Array.isArray(item.candidate_missing_confirmations) ? item.candidate_missing_confirmations.slice(0) : [],
        candidate_trigger_plan: item.candidate_trigger_plan || item.candidateTriggerPlan || null,
        trade_intent_label: item.trade_intent_label || '',
        requires_trade_plan: item.requires_trade_plan,
        requires_stop_loss: item.requires_stop_loss,
        final_score: item.final_score,
        rank_score: item.rank_score,
        risk_score: item.risk_score,
        confirm_score: item.confirm_score,
        _scan_type: item._scan_type || item.scan_type || '',
        scan_type: item.scan_type || item._scan_type || '',
        signalLabel: signalText || item.signal_label || item.signal || '扫描',
        signalName: '',
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
    var modeText = getModeText();
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
    var previousWorkspace = workspaceView;
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
    if (typeof isScanIndexReadRequested === 'function'
        && isScanIndexReadRequested()
        && typeof loadScanWorkspace === 'function'
        && previousWorkspace !== workspaceView) {
        var shouldRefreshReadSource = workspaceView === 'data'
            || (workspaceView === 'candidates'
                && scanWorkspaceState.readSource === 'json_snapshot'
                && scanWorkspaceState.readSourceOverride !== 'json');
        if (shouldRefreshReadSource) {
            loadScanWorkspace(
                scanWorkspaceState.activeType,
                scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : '',
                false
            );
        }
    }
    if (
        deskView === 'analysis'
        && !options.skipInitialAnalysis
        && typeof analysisStore !== 'undefined'
        && !analysisStore.getRootData()
        && !analysisStore.isAnalysisLoading()
    ) {
        analyzeStock({skipNavigation: true});
    }
}

function setDeskView(view) {
    setWorkspaceView(view === 'analysis' ? 'analysis' : 'candidates');
}

function cancelAutoAnalyzeStock() {
    if (autoAnalyzeTimer) {
        clearTimeout(autoAnalyzeTimer);
        autoAnalyzeTimer = null;
    }
}

function stockCodeFromInputValue(value) {
    var match = String(value || '').match(/\d{6}/);
    return match ? match[0] : '';
}

function handleStockCodeInput(event) {
    if (event && event.isComposing) return;
    cancelAutoAnalyzeStock();
    var input = event && event.target ? event.target : document.getElementById('stock-code');
    var code = stockCodeFromInputValue(input ? input.value : '');
    if (!code || String(input ? input.value : '').trim().length < 6 || code === lastAutoAnalyzedCode) {
        return;
    }
    autoAnalyzeTimer = setTimeout(function() {
        autoAnalyzeTimer = null;
        var currentInput = document.getElementById('stock-code');
        var currentCode = stockCodeFromInputValue(currentInput ? currentInput.value : '');
        if (!currentCode || currentCode !== code || currentCode === lastAutoAnalyzedCode) return;
        lastAutoAnalyzedCode = currentCode;
        analyzeStock({forceRefresh: true});
    }, AUTO_ANALYZE_DEBOUNCE_MS);
}

function handleKeyPress(event) {
    if (event.key === 'Enter') {
        cancelAutoAnalyzeStock();
        lastAutoAnalyzedCode = stockCodeFromInputValue(event && event.target ? event.target.value : '');
        analyzeStock();
    }
}

function analyzeStock(options) {
    options = options || {};
    var code = document.getElementById('stock-code').value.trim();
    if (!code) return;
    if (!options.skipNavigation && workspaceView !== 'analysis') {
        setWorkspaceView('analysis', {skipInitialAnalysis: true});
    }
    var forceRefresh = options.forceRefresh !== false;
    if (forceRefresh) {
        cancelAutoAnalyzeStock();
        lastAutoAnalyzedCode = stockCodeFromInputValue(code);
    }
    if (activeScanChartFocus && !scanChartFocusMatchesCode(code)) {
        clearActiveScanChartFocus();
    }

    if (activeAnalysisController) {
        activeAnalysisController.abort();
        activeAnalysisController = null;
    }
    if (typeof abortDeferredTimeframeRequests === 'function') {
        abortDeferredTimeframeRequests();
    }
    var requestController = typeof AbortController !== 'undefined'
        ? new AbortController()
        : null;
    activeAnalysisController = requestController;

    var btn = document.getElementById('btn-analyze');
    var refreshBtn = document.getElementById('btn-refresh-analysis');
    if (btn) btn.disabled = true;
    if (refreshBtn) refreshBtn.disabled = true;
    var analysisRequest = analysisStore.beginAnalysis(code);
    setDeskStatus(forceRefresh ? '刷新行情中' : '分析中');
    setChartState(forceRefresh ? '刷新行情数据' : '加载数据');

    return analyzeStockData(code, {
        signal: requestController ? requestController.signal : undefined,
        forceRefresh: forceRefresh
    })
        .then(function(data) {
            if (!analysisStore.isAnalysisRequestCurrent(analysisRequest)) {
                return;
            }
            if (data.error) {
                analysisStore.failAnalysis(analysisRequest, data.error);
                setDeskStatus('分析失败');
                setChartState('返回错误');
                alert('错误: ' + data.error);
                return;
            }
            analysisStore.completeAnalysis(analysisRequest, data);
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
            if (!analysisStore.failAnalysis(analysisRequest, err)) {
                return;
            }
            setDeskStatus('请求失败');
            setChartState('请求失败');
            alert('请求失败: ' + err.message);
        })
        .finally(function() {
            if (activeAnalysisController === requestController) {
                activeAnalysisController = null;
            }
            if (analysisStore.isAnalysisRequestCurrent(analysisRequest) || !analysisStore.isAnalysisLoading()) {
                if (btn) btn.disabled = false;
                if (refreshBtn) refreshBtn.disabled = false;
            }
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
    if (typeof renderScanStrategyViewToggle === 'function') {
        renderScanStrategyViewToggle();
    }
    if (workspaceView === 'analysis' && !analysisStore.getRootData()) {
        analyzeStock({skipNavigation: true});
    }
};
