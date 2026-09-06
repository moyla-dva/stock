function requestJson(url, options) {
    return fetch(url, options || {}).then(function(response) {
        if (!response.ok) {
            return response.text().then(function(text) {
                throw new Error('服务器错误 (' + response.status + '): ' + text.substring(0, 100));
            });
        }
        return response.json();
    });
}

function analyzeStockData(code) {
    return requestJson('/api/analyze?code=' + encodeURIComponent(code));
}

function fetchStockList() {
    return requestJson('/api/stock_list');
}

function fetchScanWorkspace(snapshotDay, forceRefresh, limit, options) {
    options = options || {};
    var params = new URLSearchParams();
    if (snapshotDay) params.set('snapshot_day', snapshotDay);
    if (forceRefresh) params.set('refresh', '1');
    if (limit) params.set('limit', limit);
    if (options.lite) params.set('lite', '1');
    if (options.includeReplay === false) params.set('include_replay', '0');
    if (options.includeReplay === true) params.set('include_replay', '1');
    var query = params.toString();
    return requestJson('/api/scan_workspace' + (query ? '?' + query : ''));
}

function fetchScanCandidates(options) {
    options = options || {};
    var params = new URLSearchParams();
    params.set('scan_type', options.scanType || 'opportunity');
    if (options.snapshotDay) params.set('snapshot_day', options.snapshotDay);
    if (options.forceRefresh) params.set('refresh', '1');
    if (options.sector) params.set('sector', options.sector);
    if (options.concept) params.set('concept', options.concept);
    if (options.query) params.set('query', options.query);
    if (options.limit) params.set('limit', options.limit);
    if (options.offset) params.set('offset', options.offset);
    if (options.lite) params.set('lite', '1');
    if (options.includeReplay === false) params.set('include_replay', '0');
    if (options.includeReplay === true) params.set('include_replay', '1');
    return requestJson('/api/scan_workspace/candidates?' + params.toString());
}

function fetchScanHistory(limit) {
    return requestJson('/api/scan_history?limit=' + encodeURIComponent(limit || 30));
}

function fetchScanCacheStatus() {
    return requestJson('/api/scan_cache');
}

function fetchDataSources() {
    return requestJson('/api/data_sources');
}

function fetchProfileRelationEvidence(code) {
    var params = new URLSearchParams();
    if (code) params.set('code', code);
    var query = params.toString();
    return requestJson('/api/profile_relations/evidence' + (query ? '?' + query : ''));
}

function saveProfileRelationEvidence(code, relation) {
    return requestJson('/api/profile_relations/evidence', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            code: code,
            relation: relation || {}
        })
    });
}

function deleteProfileRelationEvidence(code, relationName) {
    return requestJson('/api/profile_relations/evidence', {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            code: code,
            relation_name: relationName || ''
        })
    });
}

function pruneScanCache(options) {
    options = options || {};
    return requestJson('/api/scan_cache/prune', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            delete_obsolete_strategy: Boolean(options.deleteObsoleteStrategy)
        })
    });
}

function fetchStockProfiles(codes) {
    return requestJson('/api/stock_profiles', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({codes: codes || []})
    });
}

function fetchStockConceptStatus() {
    return requestJson('/api/stock_concepts/status');
}

function startStockConceptRefresh(maxConcepts) {
    return requestJson('/api/stock_concepts/refresh', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({max_concepts: maxConcepts == null ? null : maxConcepts})
    });
}

function fetchStockConceptJob(jobId) {
    return requestJson('/api/stock_concepts/jobs/' + encodeURIComponent(jobId));
}

function fetchBoardMarket(type, name, indexCode) {
    var params = new URLSearchParams();
    params.set('type', type || 'industry');
    if (name) params.set('name', name);
    if (indexCode) params.set('index_code', indexCode);
    return requestJson('/api/board_market?' + params.toString());
}

function refreshBoardMarketCache(type, limit, force) {
    return requestJson('/api/board_market/refresh', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            type: type || 'industry',
            limit: limit || 8,
            force: Boolean(force)
        })
    });
}

function startScanJob(scanType, mode, refreshPolicy, scope) {
    return requestJson('/api/scan_jobs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scan_type: scanType, mode: mode, refresh_policy: refreshPolicy, scope: scope})
    });
}

function fetchScanPlan(scanType, mode, refreshPolicy, scope) {
    return requestJson('/api/scan_plan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scan_type: scanType, mode: mode, refresh_policy: refreshPolicy, scope: scope})
    });
}

function fetchScanJob(jobId) {
    return requestJson('/api/scan_jobs/' + encodeURIComponent(jobId));
}

function fetchScanJobs(limit) {
    return requestJson('/api/scan_jobs?limit=' + encodeURIComponent(limit || 8));
}

function cancelScanJob(jobId) {
    return requestJson('/api/scan_jobs/' + encodeURIComponent(jobId) + '/cancel', {
        method: 'POST'
    });
}

function scanBatch() {
    return Promise.reject(new Error('同步批扫已下线，请使用后台扫描任务'));
}
