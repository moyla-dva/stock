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
    return stateItem.code === item.code
        && (stateItem.event_date || stateItem.date || '') === (item.event_date || item.date || '')
        && (stateItem._scan_type || stateItem.scan_type || scanWorkspaceState.activeType) === scanWorkspaceState.activeType;
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
    if (shouldOpenChart) {
        openScanResultChart(item);
    }
}
