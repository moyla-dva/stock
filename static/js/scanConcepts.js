var conceptRefreshTimer = null;

function isConceptJobRunning(job) {
    return Boolean(job && ['queued', 'running'].indexOf(job.status) >= 0);
}

function renderStockConceptFailure(message) {
    if (conceptRefreshTimer) clearTimeout(conceptRefreshTimer);
    var previousJob = scanWorkspaceState.conceptJob || {};
    renderStockConceptStatus({
        cache: scanWorkspaceState.conceptCache,
        job: {
            id: previousJob.id || '',
            status: 'failed',
            total: previousJob.total || 0,
            completed: previousJob.completed || 0,
            progress: previousJob.progress || 0,
            current_concept: '',
            stock_count: previousJob.stock_count || 0,
            concept_count: previousJob.concept_count || 0,
            error: message || '服务连接中断，请重新刷新'
        }
    });
}

function renderStockConceptStatus(payload) {
    payload = payload || {};
    var cache = payload.cache || scanWorkspaceState.conceptCache || {};
    var job = payload.job || scanWorkspaceState.conceptJob || null;
    scanWorkspaceState.conceptCache = cache;
    scanWorkspaceState.conceptJob = job;

    var running = isConceptJobRunning(job);
    var interrupted = Boolean(job && job.status === 'interrupted');
    var failed = Boolean(job && (job.status === 'failed' || interrupted));
    var status = document.getElementById('scan-concept-status');
    if (status) {
        var statusClass = 'scan-concept-status--empty';
        if (running) {
            statusClass = 'scan-concept-status--running';
        } else if (failed) {
            statusClass = 'scan-concept-status--failed';
        } else if (cache.available) {
            statusClass = 'scan-concept-status--ready';
        }
        status.className = 'scan-concept-status ' + statusClass;
    }

    var title = running ? '刷新中' : (interrupted ? '刷新中断' : (failed ? '刷新失败' : (cache.available ? '已构建' : '未构建')));
    setText('scan-concept-health', title);
    setText('scan-data-concept-health', title);

    var detail = '覆盖 ' + (cache.stock_count || 0) + ' 只 · ' + (cache.concept_count || 0) + ' 概念';
    if (running) {
        detail = '进度 ' + (job.progress || 0) + '% · ' + (job.completed || 0) + '/' + (job.total || 0);
        if (job.current_concept) detail += ' · ' + job.current_concept;
    } else if (failed) {
        detail = job.error ? job.error : '请稍后重试';
    } else if (cache.updated_at && cache.updated_at !== '-') {
        detail += ' · ' + cache.updated_at.replace('T', ' ');
    }
    setText('scan-concept-detail', detail);
    setText('scan-data-concept-detail', detail);

    var button = document.getElementById('btn-refresh-concepts');
    if (button) {
        button.disabled = running;
        button.textContent = running ? '刷新中' : '刷新概念库';
    }
    if (typeof setScanActionButtonState === 'function') {
        setScanActionButtonState('refresh-concepts', running, running ? '刷新中' : null);
    }
    if (typeof renderScanDataWorkspace === 'function') {
        renderScanDataWorkspace();
    }
}

function scheduleConceptStatusPoll(jobId) {
    if (conceptRefreshTimer) clearTimeout(conceptRefreshTimer);
    if (!jobId) return;
    conceptRefreshTimer = setTimeout(function() {
        pollStockConceptJob(jobId);
    }, 1200);
}

async function loadStockConceptStatus() {
    if (typeof fetchStockConceptStatus !== 'function') return;
    try {
        var payload = await fetchStockConceptStatus();
        if (payload.error) throw new Error(payload.error);
        renderStockConceptStatus(payload);
        if (isConceptJobRunning(payload.job)) {
            scheduleConceptStatusPoll(payload.job.id);
        }
    } catch (err) {
        renderStockConceptFailure('服务状态不可用，请确认后端已启动');
        console.error('概念库状态获取失败:', err);
    }
}

async function pollStockConceptJob(jobId) {
    if (!jobId || typeof fetchStockConceptJob !== 'function') return;
    try {
        var job = await fetchStockConceptJob(jobId);
        if (job.error && job.status !== 'failed') throw new Error(job.error);
        renderStockConceptStatus({cache: scanWorkspaceState.conceptCache, job: job});
        if (isConceptJobRunning(job)) {
            scheduleConceptStatusPoll(job.id);
            return;
        }
        await loadStockConceptStatus();
        if (job.status === 'completed' && typeof loadScanWorkspace === 'function') {
            await loadScanWorkspace(scanWorkspaceState.activeType);
        }
    } catch (err) {
        renderStockConceptFailure('刷新连接中断，请重新刷新');
        console.error('概念库刷新轮询失败:', err);
    }
}

async function refreshStockConceptLibrary() {
    if (typeof startStockConceptRefresh !== 'function') return;
    try {
        setText('scan-concept-health', '启动中');
        setText('scan-data-concept-health', '启动中');
        var job = await startStockConceptRefresh();
        if (job.error) throw new Error(job.error);
        renderStockConceptStatus({cache: scanWorkspaceState.conceptCache, job: job});
        scheduleConceptStatusPoll(job.id);
    } catch (err) {
        renderStockConceptFailure('刷新启动失败，请稍后重试');
        console.error('概念库刷新启动失败:', err);
    }
}
