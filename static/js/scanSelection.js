function openScanResultChart(item) {
    scanWorkspaceState.previewResult = null;
    var codeInput = document.getElementById('stock-code');
    if (codeInput) codeInput.value = item.code;
    var scanType = item._scan_type || item.scan_type || scanWorkspaceState.activeType;
    var config = getScanConfig(scanType);
    if (typeof setActiveScanChartFocus === 'function') {
        setActiveScanChartFocus(Object.assign({}, item, {
            _scan_type: scanType,
            _pool_title: config.title
        }));
    }
    if (typeof pendingFocusDate !== 'undefined') {
        pendingFocusDate = item.event_date || item.date || null;
    }
    if (typeof setSignalMode === 'function') {
        setSignalMode('composite');
    }
    if (typeof setDeskView === 'function') {
        setDeskView('analysis');
    }
    analyzeStock();
}

function isSelectedScanResult(item) {
    var selected = scanWorkspaceState.selectedResult;
    if (!selected || !item) return false;
    return scanResultMatchesWorkspaceItem(item, selected);
}

function isPreviewScanResult(item) {
    var preview = scanWorkspaceState.previewResult;
    if (!preview || !item) return false;
    return scanResultMatchesWorkspaceItem(item, preview);
}

function scanResultMatchesWorkspaceItem(item, stateItem) {
    if (!item || !stateItem) return false;
    var itemType = item._scan_type || item.scan_type || scanWorkspaceState.activeType;
    var stateType = stateItem._scan_type || stateItem.scan_type || scanWorkspaceState.activeType;
    return stateItem.code === item.code
        && (stateItem.event_date || stateItem.date || '') === (item.event_date || item.date || '')
        && stateType === itemType;
}

function scanCandidateDetailKey(item) {
    if (!item) return '';
    return [
        item.code || '',
        item.event_date || item.date || '',
        item._scan_type || item.scan_type || scanWorkspaceState.activeType,
        item._history_snapshot_day || scanWorkspaceState.historySnapshotDay || ''
    ].join('|');
}

function mergeScanCandidateDetail(compactItem, detailItem) {
    var preserved = {
        _variant: compactItem._variant,
        _scan_type: compactItem._scan_type,
        _visible_rank: compactItem._visible_rank,
        _history_snapshot_day: compactItem._history_snapshot_day
    };
    return Object.assign({}, compactItem, detailItem || {}, preserved, {
        _compact: false,
        _detail_loading: false,
        _detail_error: ''
    });
}

async function loadScanCandidateDetailForSelection() {
    var selected = scanWorkspaceState.selectedResult;
    if (!selected || !selected._compact || selected._detail_loading) return;
    var requestKey = scanCandidateDetailKey(selected);
    scanWorkspaceState.loadingCandidateDetail = true;
    scanWorkspaceState.candidateDetailRequestKey = requestKey;
    scanWorkspaceState.selectedResult = Object.assign({}, selected, {
        _detail_loading: true,
        _detail_error: ''
    });
    renderScanSelection();
    try {
        var payload = await fetchScanCandidateDetail({
            scanType: selected._scan_type || selected.scan_type || scanWorkspaceState.activeType,
            snapshotDay: selected._history_snapshot_day || (scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : ''),
            code: selected.code || '',
            eventDate: selected.event_date || selected.date || ''
        });
        var current = scanWorkspaceState.selectedResult;
        if (!current || scanCandidateDetailKey(current) !== requestKey) return;
        var detail = (payload.results || []).find(function(item) {
            return scanResultMatchesWorkspaceItem(item, current);
        }) || null;
        if (!detail) {
            scanWorkspaceState.selectedResult = Object.assign({}, current, {
                _compact: false,
                _detail_loading: false,
                _detail_error: '未找到完整详情'
            });
            renderScanSelection();
            return;
        }
        scanWorkspaceState.selectedResult = mergeScanCandidateDetail(current, detail);
        mergeScanPoolResults(current._scan_type || current.scan_type || scanWorkspaceState.activeType, [scanWorkspaceState.selectedResult]);
        renderScanSelection();
    } catch (err) {
        var latest = scanWorkspaceState.selectedResult;
        if (latest && scanCandidateDetailKey(latest) === requestKey) {
            scanWorkspaceState.selectedResult = Object.assign({}, latest, {
                _compact: false,
                _detail_loading: false,
                _detail_error: err.message || '详情加载失败'
            });
            renderScanSelection();
        }
    } finally {
        if (scanWorkspaceState.candidateDetailRequestKey === requestKey) {
            scanWorkspaceState.loadingCandidateDetail = false;
            scanWorkspaceState.candidateDetailRequestKey = '';
        }
    }
}

function previewScanResult(item, variant, visibleRank) {
    if (!item) return;
    if (isPreviewScanResult(item)) return;
    scanWorkspaceState.previewResult = Object.assign({}, item, {
        _variant: variant,
        _scan_type: scanWorkspaceState.activeType,
        _visible_rank: visibleRank || item._visible_rank || null,
        _history_snapshot_day: scanWorkspaceState.historySnapshotDay || ''
    });
    renderScanSelection();
}

function clearPreviewScanResult(skipRender) {
    if (!scanWorkspaceState.previewResult) return;
    scanWorkspaceState.previewResult = null;
    if (!skipRender) {
        renderScanSelection();
    }
}

function selectScanResult(item, variant, shouldOpenChart, visibleRank) {
    scanWorkspaceState.previewResult = null;
    scanWorkspaceState.selectedResult = Object.assign({}, item, {
        _variant: variant,
        _scan_type: scanWorkspaceState.activeType,
        _visible_rank: visibleRank || item._visible_rank || null,
        _history_snapshot_day: scanWorkspaceState.historySnapshotDay || ''
    });
    renderScanSelection();
    setScanSideView('detail');
    loadScanCandidateDetailForSelection();
    if (shouldOpenChart) {
        openScanResultChart(item);
    }
}
