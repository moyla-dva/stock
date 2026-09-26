// 冷缓存工作台构建约 45s，超时须显著大于该值；仅防连接永久挂起。
var REQUEST_TIMEOUT_MS = 90000;

function requestTimeoutSignal(timeoutMs) {
    if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
        return AbortSignal.timeout(timeoutMs || REQUEST_TIMEOUT_MS);
    }
    return null;
}

function combineRequestSignals(primarySignal, timeoutSignal) {
    if (primarySignal && timeoutSignal && typeof AbortSignal !== 'undefined' && typeof AbortSignal.any === 'function') {
        return AbortSignal.any([primarySignal, timeoutSignal]);
    }
    return primarySignal || timeoutSignal || null;
}

function isAbortLikeError(error) {
    return error && (error.name === 'AbortError' || error.name === 'TimeoutError');
}

function isRequestCancelled(error) {
    return Boolean(error && (
        error.cancelled
        || error.name === 'AbortError'
        || String(error.message || '').indexOf('请求已取消:') === 0
    ));
}

function buildHttpError(response, text) {
    var detail = String(text || '').substring(0, 100);
    var code = '';
    var retryable;
    try {
        var payload = JSON.parse(text || '{}');
        var apiError = payload && payload.error;
        if (apiError && typeof apiError === 'object') {
            detail = apiError.message || payload.message || detail;
            code = apiError.code || '';
            retryable = apiError.retryable;
        } else if (typeof apiError === 'string') {
            detail = apiError;
        } else if (payload && typeof payload.message === 'string') {
            detail = payload.message;
        }
    } catch (error) {
        // Non-JSON error bodies keep their existing text preview.
    }

    var message = '服务器错误 (' + response.status + ')'
        + (code ? ' [' + code + ']' : '')
        + ': ' + String(detail || '请求失败').substring(0, 160);
    var requestError = new Error(message);
    requestError.status = response.status;
    if (code) requestError.code = code;
    if (typeof retryable === 'boolean') requestError.retryable = retryable;
    return requestError;
}

function requestJson(url, options) {
    var fetchOptions = Object.assign({}, options || {});
    var timeoutMs = fetchOptions.timeoutMs || REQUEST_TIMEOUT_MS;
    var timeoutSignal = fetchOptions.disableTimeout ? null : requestTimeoutSignal(timeoutMs);
    var originalSignal = fetchOptions.signal || null;
    var combinedSignal = combineRequestSignals(originalSignal, timeoutSignal);
    delete fetchOptions.timeoutMs;
    delete fetchOptions.disableTimeout;
    if (combinedSignal) {
        fetchOptions.signal = combinedSignal;
    }
    return fetch(url, fetchOptions).catch(function (error) {
        if (isAbortLikeError(error)) {
            var requestError = new Error(error.name === 'AbortError' ? ('请求已取消: ' + url) : ('请求超时: ' + url));
            requestError.cancelled = error.name === 'AbortError';
            requestError.timeout = error.name === 'TimeoutError';
            throw requestError;
        }
        throw error;
    }).then(function(response) {
        if (!response.ok) {
            return response.text().then(function(text) {
                throw buildHttpError(response, text);
            });
        }
        return response.json();
    });
}

function analyzeStockData(code, options) {
    options = options || {};
    var params = new URLSearchParams();
    params.set('code', code);
    if (options.forceRefresh) params.set('refresh', '1');
    if (options.includeLegacy) params.set('include_legacy', '1');
    if (typeof shouldUseSingleStockReadModel === 'function'
        && shouldUseSingleStockReadModel()
        && typeof singleStockAnalysisToChartPayload === 'function') {
        return requestJson('/api/single_stock_analysis?' + params.toString(), {
            signal: options.signal,
            timeoutMs: options.timeoutMs,
            disableTimeout: options.disableTimeout
        }).then(singleStockAnalysisToChartPayload);
    }
    return requestJson('/api/analyze?' + params.toString(), {
        signal: options.signal,
        timeoutMs: options.timeoutMs,
        disableTimeout: options.disableTimeout
    });
}

function fetchAnalysisTimeframes(code, period, options) {
    var params = new URLSearchParams();
    params.set('code', code);
    if (period) params.set('period', period);
    return requestJson('/api/analyze/timeframes?' + params.toString(), options);
}

function fetchScanWorkspaceFromJson(snapshotDay, forceRefresh, limit, options) {
    options = options || {};
    var params = new URLSearchParams();
    if (snapshotDay) params.set('snapshot_day', snapshotDay);
    if (forceRefresh) params.set('refresh', '1');
    if (limit) params.set('limit', limit);
    if (options.lite) params.set('lite', '1');
    if (options.activeType) params.set('active_type', options.activeType);
    if (options.entryModel) params.set('entry_model', options.entryModel);
    if (options.includeReplay === false) params.set('include_replay', '0');
    if (options.includeReplay === true) params.set('include_replay', '1');
    var query = params.toString();
    return requestJson('/api/scan_workspace' + (query ? '?' + query : ''), {
        signal: options.signal,
        timeoutMs: options.timeoutMs,
        disableTimeout: options.disableTimeout
    });
}

function fetchScanWorkspace(snapshotDay, forceRefresh, limit, options) {
    options = options || {};
    if (forceRefresh && scanWorkspaceState.readSourceOverride === 'json') {
        scanWorkspaceState.readSourceOverride = '';
        scanWorkspaceState.readSourceError = '';
    }
    if (typeof shouldUseScanIndexRead !== 'function' || !shouldUseScanIndexRead(options)) {
        return fetchScanWorkspaceFromJson(snapshotDay, forceRefresh, limit, options).then(function (workspace) {
            if (typeof isScanIndexReadRequested === 'function' && isScanIndexReadRequested()) {
                workspace.read_source = scanWorkspaceState.readSourceOverride === 'json'
                    ? 'json_fallback'
                    : 'json_snapshot';
                workspace.read_source_error = scanWorkspaceState.readSourceError || '';
            }
            return workspace;
        });
    }

    return fetchScanIndexWorkspace({
        snapshotDay: snapshotDay,
        limit: limit,
        activeType: options.activeType,
        signal: options.signal,
        timeoutMs: options.timeoutMs
    }).catch(function (error) {
        if (isRequestCancelled(error)) {
            throw error;
        }
        scanWorkspaceState.readSourceOverride = 'json';
        scanWorkspaceState.readSourceError = error.message || 'SQLite 候选索引读取失败';
        return fetchScanWorkspaceFromJson(snapshotDay, forceRefresh, limit, options).then(function (workspace) {
            workspace.read_source = 'json_fallback';
            workspace.read_source_error = scanWorkspaceState.readSourceError;
            return workspace;
        });
    });
}

function fetchScanCandidates(options) {
    options = options || {};
    if (!options.detail
        && typeof shouldUseScanIndexRead === 'function'
        && shouldUseScanIndexRead(options)) {
        return fetchScanIndexCandidatePage(options);
    }
    var params = new URLSearchParams();
    params.set('scan_type', options.scanType || 'opportunity');
    if (options.snapshotDay) params.set('snapshot_day', options.snapshotDay);
    if (options.forceRefresh) params.set('refresh', '1');
    if (options.sector) params.set('sector', options.sector);
    if (options.concept) params.set('concept', options.concept);
    if (options.code) params.set('code', options.code);
    if (options.query) params.set('query', options.query);
    if (options.reason) params.set('reason', options.reason);
    if (options.eventDate) params.set('event_date', options.eventDate);
    if (options.limit) params.set('limit', options.limit);
    if (options.offset) params.set('offset', options.offset);
    if (options.entryModel) params.set('entry_model', options.entryModel);
    if (options.lite) params.set('lite', '1');
    if (options.detail) params.set('detail', '1');
    if (options.compact === false) params.set('compact', '0');
    if (options.includeReplay === false) params.set('include_replay', '0');
    if (options.includeReplay === true) params.set('include_replay', '1');
    return requestJson('/api/scan_workspace/candidates?' + params.toString(), {
        signal: options.signal,
        timeoutMs: options.timeoutMs,
        disableTimeout: options.disableTimeout
    });
}

function fetchScanCandidateDetail(options) {
    options = options || {};
    var detailOptions = Object.assign({}, options, {
        limit: 1,
        offset: 0,
        lite: true,
        detail: true,
        compact: false,
        includeReplay: false
    });
    if (options.indexedSummary
        && typeof shouldUseScanIndexRead === 'function'
        && shouldUseScanIndexRead(options)
        && typeof fetchScanIndexCandidateDetail === 'function') {
        return fetchScanIndexCandidateDetail(detailOptions).then(function (detail) {
            return {candidate_detail: detail, _detail_read_source: 'sqlite_candidate_detail'};
        }).catch(function (error) {
            if (isRequestCancelled(error)) throw error;
            return fetchScanCandidates(detailOptions).then(function (payload) {
                payload._detail_read_source = 'json_fallback';
                payload._detail_read_error = error.message || 'SQLite 候选详情读取失败';
                return payload;
            });
        });
    }
    return fetchScanCandidates(detailOptions);
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

function startScanJob(scanType, refreshPolicy, scope) {
    return requestJson('/api/scan_jobs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scan_type: scanType, refresh_policy: refreshPolicy, scope: scope})
    });
}

function fetchScanPlan(scanType, refreshPolicy, scope) {
    return requestJson('/api/scan_plan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scan_type: scanType, refresh_policy: refreshPolicy, scope: scope})
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
