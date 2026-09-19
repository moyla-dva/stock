var activeScanJobId = null;
var activeScanJobType = null;
var scanJobPollTimer = null;

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
    try {
        setScanStatus(requestedSnapshotDay ? '读取历史结果' : '读取本地结果');
        var workspace = await fetchScanWorkspace(requestedSnapshotDay, forceRefresh, limit, {
            lite: true,
            activeType: scanWorkspaceState.activeType
        });
        if (workspace.error) throw new Error(workspace.error);
        renderScanWorkspace(workspace);
        enrichActiveScanProfiles();
        var totalCount = workspace.scanned_count || 0;
        var activePool = workspace.pools && workspace.pools[scanWorkspaceState.activeType];
        var activeCount = activePool ? (activePool.count || 0) : 0;
        var activeTitle = activePool ? (activePool.title || scanWorkspaceState.activeType) : '候选';
        setScanStatus(requestedSnapshotDay
            ? (activeCount ? '历史 ' + workspace.latest_snapshot_day + ' · ' + activeTitle + ' ' + activeCount + ' 只' : '历史结果为空')
            : (totalCount ? activeTitle + ' ' + activeCount + ' 只 · 本地快照 ' + totalCount + ' 只' : '无本地结果'));
        return true;
    } catch (err) {
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
    }
}

async function loadScanCandidatesForCurrentFilters(scanType, offset, limit) {
    scanType = normalizeScanPoolType(scanType || scanWorkspaceState.activeType);
    var filters = scanWorkspaceState.filters || {};
    var payload = await fetchScanCandidates({
        scanType: scanType,
        snapshotDay: scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : '',
        sector: filters.sector || '',
        concept: filters.concept || '',
        query: filters.query || '',
        reason: filters.reason || '',
        offset: offset || 0,
        limit: limit || SCAN_RESULT_PAGE_SIZE,
        lite: true
    });
    if (payload.error) throw new Error(payload.error);
    mergeScanPoolResults(scanType, payload.results || []);
    setActiveScanFilterLoadMeta(payload);
    return payload;
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
    var nextLimit = hasActiveScanFilters() ? SCAN_RESULT_PAGE_SIZE : increaseScanResultLimitForCurrentView(pool);
    scanWorkspaceState.loadingMoreResults = true;
    var failed = false;
    setScanStatus(hasActiveScanFilters() ? '继续查找匹配候选' : '加载更多候选');
    renderActiveScanPool();
    try {
        if (hasActiveScanFilters()) {
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

function refreshScanActionState() {
    if (typeof renderScanSnapshotMeta === 'function') {
        renderScanSnapshotMeta();
    }
}

async function pollActiveScanJob() {
    if (!activeScanJobId) return;
    var list = document.getElementById('scan-list');
    try {
        var job = await fetchScanJob(activeScanJobId);
        if (job.error) throw new Error(job.error);
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
        scanJobPollTimer = setTimeout(pollActiveScanJob, 900);
    } catch (err) {
        var failedJobId = activeScanJobId;
        var failedJobType = activeScanJobType;
        activeScanJobId = null;
        activeScanJobType = null;
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
        var job = await startScanJob(scanType, signalMode, refreshPolicy, scopeOverride);
        if (job.error) throw new Error(job.error);
        activeScanJobId = job.id;
        activeScanJobType = scanType;
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
