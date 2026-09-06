function dataSourceStatusLabel(status) {
    if (status === 'warning') return '待整理';
    if (status === 'empty') return '待建立';
    if (status === 'provider') return 'Provider';
    return '可用';
}

function renderDataSourceStatus() {
    var payload = scanWorkspaceState.dataSources || {};
    var overall = payload.overall || {};
    var sources = Array.isArray(payload.sources) ? payload.sources : [];
    var status = document.getElementById('scan-data-source-status');
    if (status) {
        status.className = 'scan-data-source-status scan-data-source-status--' + (overall.status || 'empty');
        status.title = sources.map(function(source) {
            return source.label + ': ' + dataSourceStatusLabel(source.status) + ' · ' + (source.detail || '-');
        }).join('\n');
    }
    setText('scan-data-source-health', overall.label || '读取中');
    setText('scan-data-source-detail', overall.summary || '等待数据源状态');
    setText('scan-data-source-health-main', overall.label || '读取中');
    setText('scan-data-source-detail-main', overall.summary || '等待数据源状态');
    if (typeof renderScanDataWorkspace === 'function') {
        renderScanDataWorkspace();
    }
}

async function loadDataSourceStatus() {
    renderDataSourceStatus();
    try {
        var payload = await fetchDataSources();
        if (payload.error) throw new Error(payload.error);
        scanWorkspaceState.dataSources = payload;
        renderDataSourceStatus();
    } catch (err) {
        scanWorkspaceState.dataSources = {
            overall: {
                status: 'warning',
                label: '读取失败',
                summary: err.message || '数据源状态不可用'
            },
            sources: []
        };
        renderDataSourceStatus();
    }
}

async function refreshDataSourceStatus() {
    if (typeof setScanActionButtonState === 'function') {
        setScanActionButtonState('refresh-data-sources', true, '刷新中');
    }
    try {
        await loadDataSourceStatus();
    } finally {
        if (typeof setScanActionButtonState === 'function') {
            setScanActionButtonState('refresh-data-sources', false, null);
        }
    }
}

async function syncDataGovernanceStatus() {
    if (typeof setScanActionButtonState === 'function') {
        setScanActionButtonState('sync-governance', true, '同步中');
    }
    try {
        setScanStatus('同步治理状态');
        var tasks = [loadDataSourceStatus()];
        if (typeof loadStockConceptStatus === 'function') {
            tasks.push(loadStockConceptStatus());
        }
        if (typeof loadScanHistory === 'function') {
            tasks.push(loadScanHistory());
        }
        await Promise.all(tasks);
        setScanStatus('治理状态已更新');
    } catch (err) {
        setScanStatus('治理状态同步失败');
        console.error('治理状态同步失败:', err);
    } finally {
        if (typeof setScanActionButtonState === 'function') {
            setScanActionButtonState('sync-governance', false, null);
        }
    }
}

async function refreshConceptBoardMarketCache() {
    if (typeof setScanActionButtonState === 'function') {
        setScanActionButtonState('refresh-board-market', true, '刷新中');
    }
    try {
        setScanStatus('刷新概念板块行情');
        var result = await refreshBoardMarketCache('concept', 8, false);
        if (result.error) throw new Error(result.error);
        var changed = (result.updated_count || 0) + (result.fallback_count || 0);
        setScanStatus(
            '概念行情完成 · 更新 ' + (result.updated_count || 0)
            + ' · 旧缓存 ' + (result.fallback_count || 0)
            + ' · 跳过 ' + (result.skipped_count || 0)
            + ' · 失败 ' + (result.failed_count || 0)
        );
        await loadDataSourceStatus();
        await loadScanWorkspace(
            scanWorkspaceState.activeType,
            scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : '',
            changed > 0,
            scanWorkspaceState.resultLimit
        );
    } catch (err) {
        setScanStatus('概念行情刷新失败');
        console.error('概念行情刷新失败:', err);
    } finally {
        if (typeof setScanActionButtonState === 'function') {
            setScanActionButtonState('refresh-board-market', false, null);
        }
    }
}
