function setActiveScanType(scanType) {
    scanWorkspaceState.activeType = normalizeScanPoolType(scanType);
    return scanWorkspaceState.activeType;
}

function normalizeScanSideView(view) {
    return SCAN_SIDE_VIEWS.indexOf(view) >= 0 ? view : 'detail';
}

function defaultScanRouteForWorkspace(workspace) {
    if (workspace === 'candidates') {
        return {workspace: 'candidates', sideView: 'detail'};
    }
    if (workspace === 'data') {
        return {workspace: 'data', sideView: 'detail'};
    }
    if (workspace === 'analysis') {
        return {workspace: 'analysis'};
    }
    return {workspace: 'candidates', sideView: 'detail'};
}

function applyScanNavigationState(route) {
    route = route || {};
    var workspace = typeof normalizeWorkspaceView === 'function'
        ? normalizeWorkspaceView(route.workspace || route.view || (typeof getWorkspaceView === 'function' ? getWorkspaceView() : 'candidates'))
        : (route.workspace || route.view || 'candidates');
    var next = route.useDefaults
        ? Object.assign({}, defaultScanRouteForWorkspace(workspace), route, {workspace: workspace})
        : Object.assign({workspace: workspace}, route);

    if (next.activeType) setActiveScanType(next.activeType);
    if (next.sideView) scanWorkspaceState.sideView = normalizeScanSideView(next.sideView);
    if (next.resultLimit) scanWorkspaceState.resultLimit = Math.min(SCAN_RESULT_MAX_LIMIT, Math.max(1, Number(next.resultLimit) || SCAN_RESULT_PAGE_SIZE));
    scanWorkspaceState.previewResult = null;
    if (next.clearSelection) scanWorkspaceState.selectedResult = null;
    if (next.filters) {
        scanWorkspaceState.filters = Object.assign({}, scanWorkspaceState.filters, next.filters);
    }
    if (next.resetFilters) {
        scanWorkspaceState.filters = {query: '', sector: '', concept: '', reason: '', sort: 'system'};
    }
    return next;
}

function navigateScanWorkspace(route) {
    var next = applyScanNavigationState(route || {});
    if (typeof setWorkspaceView === 'function') {
        setWorkspaceView(next.workspace || 'candidates', {preserveScanContext: true, skipRender: true});
    }
    if (next.workspace === 'data') {
        if (typeof loadScanJobHistory === 'function') loadScanJobHistory();
        if (typeof loadScanHistory === 'function') loadScanHistory();
    }
    if ((next.workspace || 'candidates') !== 'analysis' && typeof renderScanWorkspace === 'function') {
        renderScanWorkspace();
    } else if (next.workspace === 'analysis' && typeof myChart !== 'undefined') {
        setTimeout(function() { myChart.resize(); }, 0);
    }
    return next;
}

function clearScanHistorySnapshotState() {
    scanWorkspaceState.historyMode = false;
    scanWorkspaceState.historySnapshotDay = '';
}

function resetScanProfileRequestState() {
    scanProfileRequestState = {};
}

function hasScanProfileRequest(code) {
    return Boolean(code && scanProfileRequestState[code]);
}

function markScanProfileRequestPending(code) {
    if (code) scanProfileRequestState[code] = 'pending';
}

function markScanProfileRequestDone(code) {
    if (code) scanProfileRequestState[code] = 'done';
}

function clearScanProfileRequest(code) {
    if (code) delete scanProfileRequestState[code];
}

function resetScanPool(scanType) {
    var normalized = normalizeScanPoolType(scanType);
    scanWorkspaceState.pools[normalized] = getEmptyPool(normalized);
}

function scanResultIdentity(item) {
    return [
        item && item.code || '',
        item && (item.event_date || item.date || ''),
        item && (item.signal || item.signal_label || item.signal_name || ''),
        item && (item.scan_type || item._scan_type || '')
    ].join('|');
}

function mergeScanPoolResults(scanType, results) {
    scanType = normalizeScanPoolType(scanType);
    var pool = getScanPool(scanType);
    var byKey = {};
    (pool.results || []).forEach(function(item) {
        byKey[scanResultIdentity(item)] = item;
    });
    (results || []).forEach(function(item) {
        byKey[scanResultIdentity(item)] = Object.assign({}, item);
    });
    pool.results = Object.keys(byKey).map(function(key) { return byKey[key]; });
    pool.loaded_count = Math.max(scanPoolLoadedCount(pool), pool.results.length);
    pool.has_more = scanPoolLoadedCount(pool) < scanPoolTotalCount(pool);
    return pool;
}

function scanFilterLoadKey(scanType, filters, snapshotDay) {
    filters = filters || scanWorkspaceState.filters || {};
    return [
        normalizeScanPoolType(scanType || scanWorkspaceState.activeType),
        snapshotDay || scanWorkspaceState.historySnapshotDay || '',
        normalizeFilterText(filters.query || ''),
        filters.sector || '',
        filters.concept || '',
        filters.reason || ''
    ].join('|');
}

function getActiveScanFilterLoadMeta() {
    if (!hasActiveScanFilters()) return null;
    return scanWorkspaceState.filteredCandidateLoads[scanFilterLoadKey()];
}

function setActiveScanFilterLoadMeta(meta) {
    if (!meta) return;
    scanWorkspaceState.filteredCandidateLoads[scanFilterLoadKey(meta.scan_type, meta.filters || scanWorkspaceState.filters)] = meta;
}

function applyRunningScanJobToWorkspace(job) {
    if (!job) return false;
    var scanType = setActiveScanType(job.scan_type);
    if (job.refresh_policy === 'force') {
        var config = getScanConfig(scanType);
        var existingPool = scanWorkspaceState.pools[scanType] || {};
        if (job.results_omitted || !Array.isArray(job.results) || !job.results.length) {
            scanWorkspaceState.pools[scanType] = Object.assign({}, existingPool, {
                title: existingPool.title || config.title,
                count: job.matched || existingPool.count || 0
            });
            return false;
        }
        scanWorkspaceState.pools[scanType] = {
            title: config.title,
            count: job.matched || 0,
            loaded_count: job.results.length,
            max_items: job.results.length,
            has_more: false,
            results: job.results
        };
        return true;
    }
    return false;
}

function applyScanWorkspacePayload(workspace) {
    if (!workspace) return false;

    scanWorkspaceState.scanned_count = workspace.scanned_count || 0;
    scanWorkspaceState.valid_snapshot_count = workspace.valid_snapshot_count || 0;
    scanWorkspaceState.stale_snapshot_count = workspace.stale_snapshot_count || 0;
    scanWorkspaceState.latest_data_date = workspace.latest_data_date || '-';
    scanWorkspaceState.latest_snapshot_day = workspace.latest_snapshot_day || '-';
    scanWorkspaceState.snapshotMeta = workspace.snapshot_meta || null;
    scanWorkspaceState.strategyMeta = workspace.strategy_meta || null;
    scanWorkspaceState.strategyHealth = workspace.strategy_health || null;
    scanWorkspaceState.workspaceMaxItems = workspace.max_items || scanWorkspaceState.resultLimit || SCAN_RESULT_PAGE_SIZE;
    scanWorkspaceState.resultLimit = scanWorkspaceState.workspaceMaxItems;
    scanWorkspaceState.filteredCandidateLoads = {};
    scanWorkspaceState.historyMode = Boolean(workspace.history_mode);
    scanWorkspaceState.historySnapshotDay = workspace.history_snapshot_day || '';
    scanWorkspaceState.pools = workspace.pools || {};
    scanWorkspaceState.sectorOverview = workspace.sector_overview || [];
    scanWorkspaceState.conceptOverview = workspace.concept_overview || [];
    scanWorkspaceState.marketStructureMeta = workspace.market_structure_meta || null;
    scanWorkspaceState.resonanceCalibration = workspace.resonance_calibration || null;
    scanWorkspaceState.replayCalibration = workspace.replay_calibration || null;
    resetScanProfileRequestState();
    return true;
}
