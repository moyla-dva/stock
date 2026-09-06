function scanHistoryPoolText(item) {
    var pools = item && item.pool_counts ? item.pool_counts : {};
    return SCAN_POOL_TYPES.map(function(scanType) {
        var pool = pools[scanType] || {};
        return getScanConfig(scanType).title + ' ' + (pool.count || 0);
    }).join(' · ');
}

function renderScanHistoryPanel() {
    var list = document.getElementById('scan-history-list');
    var current = document.getElementById('scan-history-current');
    var latestBtn = document.getElementById('scan-history-latest');
    var pruneBtn = document.getElementById('scan-cache-prune');
    var cacheStatus = document.getElementById('scan-cache-governance');
    if (!list) return;

    if (current) {
        current.textContent = scanWorkspaceState.historyMode
            ? '正在回看 ' + (scanWorkspaceState.latest_snapshot_day || '-')
            : '当前显示最新本地结果';
    }
    if (latestBtn) {
        latestBtn.disabled = !scanWorkspaceState.historyMode;
    }
    if (pruneBtn && !pruneBtn.disabled) {
        var currentStatus = scanWorkspaceState.cacheStatus || {};
        pruneBtn.textContent = currentStatus.obsolete_strategy_count ? '清理旧版' : '清理过期';
    }
    if (cacheStatus) {
        var status = scanWorkspaceState.cacheStatus || {};
        cacheStatus.textContent = status.file_count == null
            ? '本地结果状态读取中'
            : ('本地结果 ' + status.file_count + ' 个 · ' + (status.size_mb || 0) + ' MB · 过期 '
                + (status.stale_count || 0) + ' · 旧版可清 ' + (status.obsolete_strategy_count || 0)
                + ' · 无效 ' + (status.invalid_count || 0));
    }

    list.innerHTML = '';
    if (scanWorkspaceState.historyError) {
        showScanError(list, scanWorkspaceState.historyError, [
            {label: '重试历史', primary: true, onClick: refreshScanHistory},
            {label: '回到最新', onClick: showLatestScanWorkspace}
        ]);
        return;
    }
    if (scanWorkspaceState.historyLoading) {
        var loading = document.createElement('div');
        loading.className = 'empty-state';
        loading.textContent = '读取历史结果';
        list.appendChild(loading);
        return;
    }

    var items = scanWorkspaceState.historyDays || [];
    if (!items.length) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = '暂无历史结果';
        list.appendChild(empty);
        return;
    }

    items.forEach(function(item) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'scan-history-item';
        if (scanWorkspaceState.historySnapshotDay === item.snapshot_day) {
            button.className += ' active';
        }

        var main = document.createElement('div');
        main.className = 'scan-history-item__main';
        var title = document.createElement('strong');
        title.textContent = item.display_day || item.snapshot_day || '-';
        var detail = document.createElement('span');
        detail.textContent = (item.snapshot_count || 0) + ' 只 · 数据 ' + (item.latest_data_date || '-');
        var pools = document.createElement('small');
        pools.textContent = scanHistoryPoolText(item);
        main.appendChild(title);
        main.appendChild(detail);
        main.appendChild(pools);

        var status = document.createElement('em');
        status.textContent = item.legacy_strategy_count
            ? '旧 ' + item.legacy_strategy_count
            : '新 ' + (item.current_strategy_count || 0);
        button.appendChild(main);
        button.appendChild(status);
        button.onclick = function() {
            selectScanHistoryDay(item.snapshot_day);
        };
        list.appendChild(button);
    });
}

function hideScanCachePruneConfirm() {
    var panel = document.getElementById('scan-cache-prune-confirm');
    if (panel) panel.hidden = true;
}

function scanCachePruneImpact(status) {
    status = status || {};
    return {
        stale: Number(status.stale_count || 0),
        invalid: Number(status.invalid_count || 0),
        obsolete: Number(status.obsolete_strategy_count || 0),
        total: Number(status.stale_count || 0) + Number(status.invalid_count || 0) + Number(status.obsolete_strategy_count || 0)
    };
}

function showScanCachePruneConfirm() {
    var status = scanWorkspaceState.cacheStatus || {};
    var impact = scanCachePruneImpact(status);
    var panel = document.getElementById('scan-cache-prune-confirm');
    if (!panel) return false;
    setText('scan-cache-confirm-title', impact.obsolete ? '确认清理旧版结果' : '确认清理过期结果');
    setText(
        'scan-cache-confirm-detail',
        '将清理 旧版 ' + impact.obsolete + ' · 过期 ' + impact.stale + ' · 无效 ' + impact.invalid +
            '。当前策略结果会保留。'
    );
    var confirmBtn = document.getElementById('scan-cache-prune-confirm-btn');
    if (confirmBtn) confirmBtn.disabled = impact.total <= 0;
    panel.hidden = false;
    return impact.total > 0;
}

async function loadScanHistory() {
    scanWorkspaceState.historyLoading = true;
    scanWorkspaceState.historyError = '';
    renderScanHistoryPanel();
    try {
        var payload = await fetchScanHistory(30);
        if (payload.error) throw new Error(payload.error);
        scanWorkspaceState.historyDays = payload.items || [];
        if (typeof fetchScanCacheStatus === 'function') {
            scanWorkspaceState.cacheStatus = await fetchScanCacheStatus();
        }
    } catch (err) {
        scanWorkspaceState.historyDays = [];
        scanWorkspaceState.historyError = err.message || '历史结果读取失败';
    } finally {
        scanWorkspaceState.historyLoading = false;
        renderScanHistoryPanel();
    }
}

async function refreshScanHistory() {
    await loadScanHistory();
}

async function selectScanHistoryDay(snapshotDay) {
    if (!snapshotDay) return;
    setScanSideView('detail');
    resetScanResultLimit();
    await loadScanWorkspace(scanWorkspaceState.activeType, snapshotDay);
}

async function showLatestScanWorkspace() {
    clearScanHistorySnapshotState();
    resetScanResultLimit();
    await loadScanWorkspace(scanWorkspaceState.activeType, '');
    await loadScanHistory();
}

async function pruneExpiredScanCache() {
    if (showScanCachePruneConfirm()) {
        if (typeof setScanSideView === 'function') setScanSideView('detail');
        return;
    }
    setScanStatus('没有可清理结果');
}

async function confirmPruneScanCache() {
    var button = document.getElementById('scan-cache-prune');
    var confirmBtn = document.getElementById('scan-cache-prune-confirm-btn');
    try {
        if (button) {
            button.disabled = true;
            button.textContent = '清理中';
        }
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.textContent = '清理中';
        }
        var status = scanWorkspaceState.cacheStatus || {};
        var result = await pruneScanCache({
            deleteObsoleteStrategy: Boolean(status.obsolete_strategy_count)
        });
        if (result.error) throw new Error(result.error);
        scanWorkspaceState.cacheStatus = result.status || null;
        var obsolete = result.deleted_obsolete_strategy_count || 0;
        setScanStatus('已清理本地结果 ' + (result.deleted_count || 0) + ' 个' + (obsolete ? ' · 旧版 ' + obsolete : ''));
        await loadScanWorkspace(scanWorkspaceState.activeType, scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : '');
        await loadScanHistory();
    } catch (err) {
        setScanStatus('缓存清理失败');
    } finally {
        hideScanCachePruneConfirm();
        if (button) {
            button.disabled = false;
            var latestStatus = scanWorkspaceState.cacheStatus || {};
            button.textContent = latestStatus.obsolete_strategy_count ? '清理旧版' : '清理过期';
        }
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = '确认清理';
        }
        renderScanHistoryPanel();
    }
}
