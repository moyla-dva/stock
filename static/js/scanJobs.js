var activeScanJobId = null;
var activeScanJobType = null;
var scanJobPollTimer = null;
var scanJobPollFailureCount = 0;
var SCAN_JOB_POLL_INTERVAL_MS = 900;
var SCAN_JOB_POLL_MAX_FAILURES = 3;
var SCAN_JOB_POLL_MAX_BACKOFF_MS = 8000;
var scanWorkspaceRequestController = null;
var scanCandidatesRequestController = null;

function createAbortControllerIfAvailable() {
    return typeof AbortController !== 'undefined' ? new AbortController() : null;
}

function abortScanWorkspaceRequest() {
    if (scanWorkspaceRequestController) {
        scanWorkspaceRequestController.abort();
        scanWorkspaceRequestController = null;
    }
}

function abortScanCandidatesRequest() {
    if (scanCandidatesRequestController) {
        scanCandidatesRequestController.abort();
        scanCandidatesRequestController = null;
    }
}

function openScanWorkspace(view) {
    if (typeof navigateScanWorkspace === 'function') {
        navigateScanWorkspace({workspace: view || 'candidates', useDefaults: true});
    } else if (typeof setWorkspaceView === 'function') {
        setWorkspaceView(view || 'candidates');
    } else if (typeof setDeskView === 'function') {
        setDeskView('scan');
    }
}

function openScanTaskWorkspace() {
    openScanWorkspace('data');
    if (typeof setScanSideView === 'function') {
        setScanSideView('detail');
    }
}

function resumeScanJob(job) {
    if (!job) return;
    var refreshPolicy = job.refresh_policy === 'force' ? 'auto' : (job.refresh_policy || 'auto');
    var scope = job.scope || (isStrategyMigrationJob(job) ? 'legacy_strategy' : 'market');
    openScanTaskWorkspace();
    return scanMarket(job.scan_type || scanWorkspaceState.activeType, refreshPolicy, '续扫', scope);
}

function setScanPool(scanType) {
    scanType = normalizeScanPoolType(scanType || scanWorkspaceState.activeType);
    if (typeof navigateScanWorkspace === 'function') {
        navigateScanWorkspace({workspace: 'candidates', activeType: scanType, sideView: 'detail'});
    } else {
        setActiveScanType(scanType);
        openScanWorkspace('candidates');
        renderScanWorkspace();
    }
    var pool = getScanPool(scanType);
    if ((pool.count || 0) > 0 && !(pool.results || []).length) {
        loadScanWorkspace(scanType, scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : '', false);
    }
    enrichActiveScanProfiles();
}

async function loadScanWorkspace(activeType, snapshotDay, forceRefresh, limitOverride) {
    if (activeType) {
        setActiveScanType(activeType);
    }
    var requestedSnapshotDay = snapshotDay === undefined
        ? (scanWorkspaceState.historySnapshotDay || '')
        : (snapshotDay || '');
    var limit = limitOverride || scanWorkspaceState.resultLimit || SCAN_RESULT_PAGE_SIZE;
    abortScanWorkspaceRequest();
    var requestController = createAbortControllerIfAvailable();
    scanWorkspaceRequestController = requestController;
    try {
        setScanStatus(requestedSnapshotDay ? '读取历史结果' : '读取本地结果');
        var workspace = await fetchScanWorkspace(requestedSnapshotDay, forceRefresh, limit, {
            lite: true,
            activeType: scanWorkspaceState.activeType,
            entryModel: scanWorkspaceState.entryModel,
            forceJson: typeof getActiveWorkspaceView === 'function' && getActiveWorkspaceView() === 'data',
            signal: requestController ? requestController.signal : undefined
        });
        if (workspace.error) throw new Error(workspace.error);
        renderScanWorkspace(workspace);
        enrichActiveScanProfiles();
        var totalCount = workspace.scanned_count || 0;
        var activePool = workspace.pools && workspace.pools[scanWorkspaceState.activeType];
        var activeCount = activePool ? (activePool.count || 0) : 0;
        var activeTitle = activePool ? (activePool.title || scanWorkspaceState.activeType) : '候选';
        var statusText = workspace.read_source === 'json_fallback'
            ? 'SQLite 读取不可用 · 已回退 JSON'
            : (workspace.read_source === 'sqlite_index'
                ? (activeCount ? activeTitle + ' ' + activeCount + ' 只 · SQLite 摘要' : 'SQLite 当前池暂无候选')
                : (requestedSnapshotDay
                    ? (activeCount ? '历史 ' + workspace.latest_snapshot_day + ' · ' + activeTitle + ' ' + activeCount + ' 只' : '历史结果为空')
                    : (totalCount ? activeTitle + ' ' + activeCount + ' 只 · 本地快照 ' + totalCount + ' 只' : '无本地结果')));
        setScanStatus(statusText);
        return true;
    } catch (err) {
        if (typeof isRequestCancelled === 'function' && isRequestCancelled(err)) {
            return false;
        }
        setScanStatus('结果读取失败');
        var list = document.getElementById('scan-list');
        if (list) showScanError(list, err.message, [
            {
                label: '重试读取',
                primary: true,
                onClick: function() {
                    loadScanWorkspace(activeType || scanWorkspaceState.activeType, requestedSnapshotDay, forceRefresh, limit);
                }
            },
            {
                label: requestedSnapshotDay ? '回到最新' : '刷新本地结果',
                onClick: function() {
                    if (requestedSnapshotDay && typeof showLatestScanWorkspace === 'function') {
                        showLatestScanWorkspace();
                    } else {
                        loadScanWorkspace(activeType || scanWorkspaceState.activeType, '', true, limit);
                    }
                }
            },
            {
                label: '查看任务记录',
                onClick: function() {
                    openScanTaskWorkspace();
                    loadScanJobHistory();
                }
            }
        ]);
        return false;
    } finally {
        if (scanWorkspaceRequestController === requestController) {
            scanWorkspaceRequestController = null;
        }
    }
}

async function loadScanCandidatesForCurrentFilters(scanType, offset, limit) {
    scanType = normalizeScanPoolType(scanType || scanWorkspaceState.activeType);
    var filters = scanWorkspaceState.filters || {};
    abortScanCandidatesRequest();
    var requestController = createAbortControllerIfAvailable();
    scanCandidatesRequestController = requestController;
    try {
        var pageOffset = offset || 0;
        var payload = await fetchScanCandidates({
            scanType: scanType,
            snapshotDay: scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : '',
            sector: filters.sector || '',
            concept: filters.concept || '',
            query: filters.query || '',
            reason: filters.reason || '',
            entryModel: scanWorkspaceState.entryModel,
            offset: pageOffset,
            limit: limit || SCAN_RESULT_PAGE_SIZE,
            lite: true,
            signal: requestController ? requestController.signal : undefined
        });
        if (payload.error) throw new Error(payload.error);
        if (payload.source === 'sqlite_index' && pageOffset === 0) {
            var currentPool = getScanPool(scanType);
            currentPool.results = [];
            currentPool.loaded_count = 0;
        }
        mergeScanPoolResults(scanType, payload.results || []);
        setActiveScanFilterLoadMeta(payload);
        return payload;
    } finally {
        if (scanCandidatesRequestController === requestController) {
            scanCandidatesRequestController = null;
        }
    }
}

async function loadMoreScanResults() {
    var pool = getScanPool(scanWorkspaceState.activeType);
    var filterMeta = typeof getActiveScanFilterLoadMeta === 'function' ? getActiveScanFilterLoadMeta() : null;
    var canLoad = hasActiveScanFilters()
        ? (!filterMeta || filterMeta.has_more || scanPoolHasMore(pool))
        : scanPoolHasMore(pool);
    if (scanWorkspaceState.loadingMoreResults || !canLoad) return;
    var beforeFiltered = typeof getVisibleScanResults === 'function' ? getVisibleScanResults().length : 0;
    var filterOffset = filterMeta && Number.isFinite(Number(filterMeta.loaded_count))
        ? Number(filterMeta.loaded_count)
        : beforeFiltered;
    var useSqliteRead = typeof shouldUseScanIndexRead === 'function' && shouldUseScanIndexRead();
    var nextLimit = useSqliteRead || hasActiveScanFilters()
        ? SCAN_RESULT_PAGE_SIZE
        : increaseScanResultLimitForCurrentView(pool);
    scanWorkspaceState.loadingMoreResults = true;
    var failed = false;
    setScanStatus(hasActiveScanFilters() ? '继续查找匹配候选' : '加载更多候选');
    renderActiveScanPool();
    try {
        if (useSqliteRead) {
            var pageOffset = hasActiveScanFilters()
                ? (filterMeta && Number.isFinite(Number(filterMeta.loaded_count)) ? Number(filterMeta.loaded_count) : 0)
                : scanPoolLoadedCount(pool);
            await loadScanCandidatesForCurrentFilters(scanWorkspaceState.activeType, pageOffset, nextLimit);
            renderActiveScanPool();
        } else if (hasActiveScanFilters()) {
            await loadScanCandidatesForCurrentFilters(scanWorkspaceState.activeType, filterOffset, nextLimit);
            renderActiveScanPool();
        } else {
            var loaded = await loadScanWorkspace(
                scanWorkspaceState.activeType,
                scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : '',
                false,
                nextLimit
            );
            if (!loaded) {
                failed = true;
                return;
            }
        }
        var afterFiltered = typeof getVisibleScanResults === 'function' ? getVisibleScanResults().length : beforeFiltered;
        if (hasActiveScanFilters() && afterFiltered <= beforeFiltered) {
            setScanStatus('已继续查找 · 当前匹配仍 ' + afterFiltered + ' 只');
        }
    } catch (err) {
        if (typeof isRequestCancelled === 'function' && isRequestCancelled(err)) {
            failed = true;
            return;
        }
        if (useSqliteRead) {
            scanWorkspaceState.readSourceOverride = 'json';
            scanWorkspaceState.readSourceError = err.message || 'SQLite 候选分页失败';
            failed = true;
            var recovered = await loadScanWorkspace(
                scanWorkspaceState.activeType,
                scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : '',
                false,
                SCAN_RESULT_PAGE_SIZE
            );
            if (recovered) setScanStatus('SQLite 分页读取失败 · 已回退 JSON');
            return;
        }
        failed = true;
        setScanStatus('加载候选失败');
        var list = document.getElementById('scan-list');
        if (list) showScanError(list, err.message, [
            {label: '重试加载', primary: true, onClick: loadMoreScanResults},
            {label: '清除筛选', onClick: resetScanFilters}
        ]);
    } finally {
        scanWorkspaceState.loadingMoreResults = false;
        if (!failed) renderActiveScanPool();
    }
}

async function loadScanJobHistory() {
    try {
        var payload = await fetchScanJobs(8);
        if (payload.error) throw new Error(payload.error);
        renderScanJobHistory(payload.jobs || []);
    } catch (err) {
        var list = document.getElementById('scan-data-job-list') || document.getElementById('scan-job-list');
        if (list) {
            list.innerHTML = '';
            showScanError(list, err.message, [
                {label: '重试任务记录', primary: true, onClick: loadScanJobHistory},
                {label: '回到详情', onClick: function() { if (typeof setScanSideView === 'function') setScanSideView('detail'); }}
            ]);
        }
    }
}

function clearScanJobPoll() {
    if (scanJobPollTimer) {
        clearTimeout(scanJobPollTimer);
        scanJobPollTimer = null;
    }
}

function scheduleScanJobPoll(delayMs) {
    clearScanJobPoll();
    scanJobPollTimer = setTimeout(pollActiveScanJob, delayMs || SCAN_JOB_POLL_INTERVAL_MS);
}

function scanJobPollBackoffDelay() {
    var delay = SCAN_JOB_POLL_INTERVAL_MS * Math.pow(2, Math.max(0, scanJobPollFailureCount - 1));
    return Math.min(delay, SCAN_JOB_POLL_MAX_BACKOFF_MS);
}

function refreshScanActionState() {
    if (typeof renderScanSnapshotMeta === 'function') {
        renderScanSnapshotMeta();
    }
}

async function pollActiveScanJob() {
    if (!activeScanJobId) return;
    var list = document.getElementById('scan-list');
    var polledJobId = activeScanJobId;
    try {
        var job = await fetchScanJob(polledJobId);
        if (!activeScanJobId || activeScanJobId !== polledJobId) return;
        if (job.error) throw new Error(job.error);
        scanJobPollFailureCount = 0;
        renderScanJob(job);

        if (isScanJobTerminal(job.status)) {
            var finalType = activeScanJobType || job.scan_type;
            activeScanJobId = null;
            activeScanJobType = null;
            clearScanJobPoll();
            disableScanButtons(false);
            refreshScanActionState();
            updateScanButtonLabel();
            await loadScanWorkspace(finalType, '', true);
            await loadScanJobHistory();
            return;
        }
        scheduleScanJobPoll(SCAN_JOB_POLL_INTERVAL_MS);
    } catch (err) {
        if (!activeScanJobId || activeScanJobId !== polledJobId) return;
        if (activeScanJobId && activeScanJobId === polledJobId && scanJobPollFailureCount < SCAN_JOB_POLL_MAX_FAILURES) {
            scanJobPollFailureCount += 1;
            setScanStatus('任务状态暂时不可用，重试中 ' + scanJobPollFailureCount + '/' + SCAN_JOB_POLL_MAX_FAILURES);
            scheduleScanJobPoll(scanJobPollBackoffDelay());
            return;
        }
        var failedJobId = activeScanJobId;
        var failedJobType = activeScanJobType;
        activeScanJobId = null;
        activeScanJobType = null;
        scanJobPollFailureCount = 0;
        clearScanJobPoll();
        disableScanButtons(false);
        refreshScanActionState();
        setScanStatus('任务状态失败');
        if (list) showScanError(list, err.message, [
            {
                label: '重试状态',
                primary: true,
                onClick: function() {
                    if (!failedJobId) return;
                    activeScanJobId = failedJobId;
                    activeScanJobType = failedJobType;
                    scanJobPollFailureCount = 0;
                    disableScanButtons(true, failedJobType);
                    pollActiveScanJob();
                }
            },
            {
                label: '查看任务',
                onClick: function() {
                    openScanTaskWorkspace();
                    loadScanJobHistory();
                }
            }
        ]);
    }
}

async function scanMarket(scanType, refreshPolicyOverride, intentLabel, scopeOverride) {
    openScanTaskWorkspace();
    scanType = setActiveScanType(scanType);
    var refreshPolicy = refreshPolicyOverride || scanWorkspaceState.refreshPolicy;
    clearScanHistorySnapshotState();
    resetScanResultLimit();
    if (refreshPolicy === 'force') {
        resetScanPool(scanType);
    }
    renderScanWorkspace();
    if (typeof setScanSideView === 'function') setScanSideView('detail');
    if (typeof renderPendingScanJob === 'function') {
        renderPendingScanJob(scanType, refreshPolicy, intentLabel ? '启动' + intentLabel : '启动扫描任务');
    }
    disableScanButtons(true, scanType);
    refreshScanActionState();
    clearScanJobPoll();

    try {
        setScanStatus(intentLabel ? '启动' + intentLabel : '启动扫描任务');
        var job = await startScanJob(scanType, refreshPolicy, scopeOverride);
        if (job.error) throw new Error(job.error);
        activeScanJobId = job.id;
        activeScanJobType = scanType;
        scanJobPollFailureCount = 0;
        renderScanJob(job);
        renderScanJobHistory([job].concat(scanWorkspaceState.jobs || []));
        if (job.duplicate_reused) {
            setScanStatus(job.duplicate_note || '已有同类任务运行');
        }
        pollActiveScanJob();
    } catch (err) {
        var list = document.getElementById('scan-list');
        activeScanJobId = null;
        activeScanJobType = null;
        setScanStatus('扫描出错');
        if (list) showScanError(list, err.message, [
            {
                label: '重新启动',
                primary: true,
                onClick: function() {
                    scanMarket(scanType, refreshPolicy, intentLabel, scopeOverride);
                }
            },
            {
                label: '读取本地结果',
                onClick: function() {
                    loadScanWorkspace(scanType, '', false);
                }
            },
            {
                label: '查看任务记录',
                onClick: function() {
                    openScanTaskWorkspace();
                    loadScanJobHistory();
                }
            }
        ]);
        console.error('扫描错误:', err);
        disableScanButtons(false);
        refreshScanActionState();
        updateScanButtonLabel();
    }
}

function scanActivePool() {
    var meta = scanWorkspaceState.snapshotMeta || {};
    if (scanWorkspaceState.historyMode && typeof showLatestScanWorkspace === 'function') {
        return showLatestScanWorkspace();
    }
    if (meta.health === 'legacy' && typeof refreshStrategySnapshots === 'function') {
        return refreshStrategySnapshots();
    }
    if (meta.health === 'expired' && typeof rebuildActiveScanPool === 'function') {
        return rebuildActiveScanPool();
    }
    return scanMarket(scanWorkspaceState.activeType);
}

async function cancelActiveScanJob() {
    if (!activeScanJobId) return;
    try {
        setScanStatus('正在停止');
        var job = await cancelScanJob(activeScanJobId);
        renderScanJob(job);
    } catch (err) {
        setScanStatus('停止失败');
    }
}
