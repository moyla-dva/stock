function getScanPrimaryActionLabel(scanType) {
    var config = getScanConfig(scanType || scanWorkspaceState.activeType);
    var meta = scanWorkspaceState.snapshotMeta || {};
    var health = meta.health || 'empty';
    if (scanWorkspaceState.historyMode) return '回到最新';
    if (health === 'legacy') return '重算旧策略';
    if (health === 'expired') return '重建' + config.title;
    if (health === 'partial') return '增量更新';
    if (health === 'empty') return '开始扫描';
    return config.action;
}

function scanCacheHealthHeadline(health) {
    if (health === 'legacy') return '旧策略待重算';
    if (health === 'expired') return '结果过期';
    if (health === 'partial') return '结果待补齐';
    if (health === 'empty') return '等待扫描';
    return '本地结果可用';
}

function scanCacheDecisionSentence(meta) {
    meta = meta || {};
    var health = meta.health || 'empty';
    var scanned = scanWorkspaceState.scanned_count || 0;
    var dataDay = scanWorkspaceState.latest_data_date || '-';
    var snapshotDay = scanWorkspaceState.latest_snapshot_day || '-';

    if (scanWorkspaceState.historyMode) {
        return '当前正在查看 ' + (scanWorkspaceState.historySnapshotDay || snapshotDay) + ' 的本地快照，可随时回到最新结果。';
    }
    if (health === 'empty') {
        return '还没有本地结果，先更新参与候选，再看候选名单。';
    }
    if (health === 'legacy') {
        return '当前结果来自旧策略，建议先重算当前池，再根据结构做判断。';
    }
    if (health === 'expired') {
        return '当前结果已过期，建议先重建当前池，再看候选名单。';
    }
    if (health === 'partial') {
        return '本地结果可用，但仍有缺口，建议先做一次增量更新。';
    }
    return '本地结果可用，已覆盖 ' + scanned + ' 只股票，可直接查看 ' + dataDay + ' / ' + snapshotDay + ' 的结构与参与名单。';
}

function updateScanButtonLabel() {
    var config = getScanConfig(scanWorkspaceState.activeType);
    var label = getScanPrimaryActionLabel(scanWorkspaceState.activeType);
    var btn = document.getElementById('btn-scan-active');
    if (btn && !btn.disabled) {
        btn.innerText = label;
        btn.className = 'scan-button scan-button--' + config.variant;
    }
    var candidateBtn = document.getElementById('btn-scan-candidate-action');
    if (candidateBtn && !candidateBtn.disabled) {
        candidateBtn.innerText = label;
        candidateBtn.className = 'candidate-desk-brief__action candidate-desk-brief__action--' + config.variant;
    }
}

function renderScanRefreshPolicy() {
    ['auto', 'cache', 'force'].forEach(function(policy) {
        var btn = document.getElementById('scan-refresh-' + policy);
        if (btn) btn.classList.toggle('active', scanWorkspaceState.refreshPolicy === policy);
    });
}

function renderScanSideView() {
    var allowedViews = SCAN_SIDE_VIEWS;
    var activeView = allowedViews.indexOf(scanWorkspaceState.sideView) >= 0
        ? scanWorkspaceState.sideView
        : 'detail';
    if (activeView !== scanWorkspaceState.sideView) {
        scanWorkspaceState.sideView = activeView;
    }
    SCAN_SIDE_VIEWS.forEach(function(view) {
        var tab = document.getElementById('scan-side-tab-' + view);
        var panel = document.getElementById('scan-side-view-' + view);
        if (tab) {
            tab.classList.toggle('active', activeView === view);
            tab.setAttribute('aria-selected', activeView === view ? 'true' : 'false');
        }
        if (panel) panel.classList.toggle('active', activeView === view);
    });
}

function setScanSideView(view) {
    scanWorkspaceState.sideView = SCAN_SIDE_VIEWS.indexOf(view) >= 0 ? view : 'detail';
    renderScanSideView();
}

function setScanRefreshPolicy(policy) {
    scanWorkspaceState.refreshPolicy = ['auto', 'cache', 'force'].indexOf(policy) >= 0 ? policy : 'auto';
    renderScanRefreshPolicy();
    updateScanButtonLabel();
    var labels = {
        auto: '刷新策略：增量更新 · 点击主操作按钮后只补缺失、过期或旧策略结果',
        cache: '刷新策略：只读本地 · 不联网、不重算',
        force: '刷新策略：强制重扫 · 点击主操作按钮后重建当前池'
    };
    if (typeof setScanStatus === 'function') {
        setScanStatus(labels[scanWorkspaceState.refreshPolicy] || labels.auto);
    }
}

function disableScanButtons(disabled, activeType) {
    var config = getScanConfig(activeType || scanWorkspaceState.activeType);
    var label = disabled ? '扫描中' : getScanPrimaryActionLabel(activeType || scanWorkspaceState.activeType);
    var btn = document.getElementById('btn-scan-active');
    if (btn) {
        btn.disabled = disabled;
        btn.innerText = label;
        btn.className = 'scan-button scan-button--' + config.variant;
    }
    var candidateBtn = document.getElementById('btn-scan-candidate-action');
    if (candidateBtn) {
        candidateBtn.disabled = disabled;
        candidateBtn.innerText = label;
        candidateBtn.className = 'candidate-desk-brief__action candidate-desk-brief__action--' + config.variant;
    }
    var cancelBtn = document.getElementById('btn-cancel-scan');
    if (cancelBtn) {
        cancelBtn.disabled = !disabled;
        cancelBtn.hidden = !disabled;
    }
}

function renderScanCacheStrip() {
    var meta = scanWorkspaceState.snapshotMeta || {};
    var strategy = scanWorkspaceState.strategyMeta || {};
    var health = meta.health || 'empty';
    var strip = document.getElementById('scan-cache-strip');
    if (strip) {
        strip.className = 'scan-cache-strip scan-cache-strip--single scan-cache-strip--' + health;
        strip.title = meta.health_detail || '';
    }
    var summary = scanCacheHealthHeadline(health);
    var extra = '';
    if (health === 'legacy' && meta.legacy_snapshot_count) {
        extra = ' · 旧版 ' + meta.legacy_snapshot_count;
    } else if ((health === 'partial' || health === 'expired') && meta.stale_snapshot_count) {
        extra = ' · 过期 ' + meta.stale_snapshot_count;
    } else if (meta.valid_snapshot_count || meta.snapshot_count) {
        extra = ' · 有效 ' + (meta.valid_snapshot_count || 0);
    }
    var compactSummary = scanCacheDecisionSentence(meta);
    var factSummary = summary +
        ' · 已扫 ' + (scanWorkspaceState.scanned_count || 0) +
        ' · 数据 ' + (scanWorkspaceState.latest_data_date || '-') +
        ' · 结果 ' + (scanWorkspaceState.latest_snapshot_day || '-');
    var fullSummary = factSummary + extra + ' · 策略 ' + (meta.strategy_version || strategy.strategy_version || '-');
    setText('scan-cache-summary', compactSummary);
    if (strip) strip.title = (meta.health_detail || '') + (meta.health_detail ? ' · ' : '') + fullSummary;
}

function renderScanSnapshotMeta() {
    var meta = scanWorkspaceState.snapshotMeta || {};
    var strategy = scanWorkspaceState.strategyMeta || {};
    var health = meta.health || 'empty';
    var status = document.getElementById('scan-snapshot-status');
    if (status) {
        status.className = 'scan-snapshot-status scan-snapshot-status--' + health;
    }
    setText('scan-snapshot-health', meta.health_summary || meta.health_label || '等待');
    var strategyVersion = meta.strategy_version || strategy.strategy_version || '-';
    var detail = meta.health_detail || ('策略 ' + strategyVersion +
        ' · 有效 ' + (meta.valid_snapshot_count || 0));
    if (!meta.health_detail) {
        if (meta.legacy_snapshot_count) {
            detail += ' · 旧版 ' + meta.legacy_snapshot_count;
        } else {
            detail += ' · 过期 ' + (meta.stale_snapshot_count || 0);
        }
    }
    setText(
        'scan-snapshot-detail',
        detail
    );
    var rebuildBtn = document.getElementById('btn-rebuild-snapshot');
    if (rebuildBtn) {
        rebuildBtn.textContent = scanWorkspaceState.historyMode
            ? '回到最新结果'
            : (health === 'legacy'
            ? '重算旧策略'
            : (meta.action_label || '重建') + '当前池');
        rebuildBtn.title = scanWorkspaceState.historyMode
            ? '退出历史回看，恢复最新本地结果'
            : (health === 'legacy'
            ? '按当前策略增量更新旧版结果'
            : '强制重建当前扫描池');
        rebuildBtn.disabled = typeof activeScanJobId !== 'undefined' && Boolean(activeScanJobId);
    }
    if (health !== 'legacy' || scanWorkspaceState.historyMode) {
        hideScanPlanConfirm();
    }
}

function formatScanPlanDetail(plan) {
    var total = plan.queued_count || plan.total || 0;
    var parts = [
        '将处理 ' + total + ' 只'
    ];
    if (plan.batch_count) {
        parts.push('分 ' + plan.batch_count + ' 批');
    }
    if (plan.legacy_strategy_count) {
        parts.push('旧策略 ' + plan.legacy_strategy_count);
    }
    if (plan.missing_count) {
        parts.push('缺失 ' + plan.missing_count);
    }
    if (plan.stale_count) {
        parts.push('过期 ' + plan.stale_count);
    }
    if (plan.cache_hit_count) {
        parts.push('跳过缓存 ' + plan.cache_hit_count);
    }
    if (plan.resume_supported) {
        parts.push('可停止后继续');
    }
    return parts.join(' · ');
}

function hideScanPlanConfirm() {
    scanWorkspaceState.pendingScanPlan = null;
    var panel = document.getElementById('scan-plan-confirm');
    if (panel) panel.hidden = true;
}

function showScanPlanConfirm(plan, intentLabel) {
    scanWorkspaceState.pendingScanPlan = {
        scanType: plan.scan_type || scanWorkspaceState.activeType,
        refreshPolicy: plan.refresh_policy || 'auto',
        scope: plan.scope || 'market',
        intentLabel: intentLabel || '策略重算'
    };
    setText('scan-plan-title', getScanConfig(scanWorkspaceState.pendingScanPlan.scanType).title + ' · ' + intentLabel);
    setText('scan-plan-detail', formatScanPlanDetail(plan));
    setText(
        'scan-plan-version',
        '策略 ' + ((plan.strategy_meta || {}).strategy_version || '-') +
            (plan.batch_size ? ' · 每批 ' + plan.batch_size : '')
    );
    var confirmBtn = document.getElementById('btn-confirm-scan-plan');
    if (confirmBtn) confirmBtn.disabled = typeof activeScanJobId !== 'undefined' && Boolean(activeScanJobId);
    var panel = document.getElementById('scan-plan-confirm');
    if (panel) panel.hidden = false;
    var settings = document.querySelector('.scan-settings-menu');
    if (settings) settings.open = true;
}

async function confirmPendingScanPlan() {
    var pending = scanWorkspaceState.pendingScanPlan;
    if (!pending) return;
    hideScanPlanConfirm();
    return scanMarket(pending.scanType, pending.refreshPolicy, pending.intentLabel, pending.scope);
}

async function refreshStrategySnapshots() {
    try {
        setScanStatus('估算策略重算');
        var plan = await fetchScanPlan(scanWorkspaceState.activeType, signalMode, 'auto', 'legacy_strategy');
        if (plan.error) throw new Error(plan.error);
        if (!(plan.queued_count || plan.total)) {
            hideScanPlanConfirm();
            setScanStatus('无需重算');
            await loadScanWorkspace(scanWorkspaceState.activeType);
            return;
        }
        showScanPlanConfirm(plan, '策略重算');
    } catch (err) {
        setScanStatus('预估失败');
        console.error('扫描计划预估失败:', err);
    }
}

function rebuildActiveScanPool() {
    hideScanPlanConfirm();
    setScanRefreshPolicy('force');
    return scanMarket(scanWorkspaceState.activeType, 'force', '重建');
}

function runSnapshotGovernanceAction() {
    var meta = scanWorkspaceState.snapshotMeta || {};
    if (scanWorkspaceState.historyMode && typeof showLatestScanWorkspace === 'function') {
        return showLatestScanWorkspace();
    }
    if (meta.health === 'legacy') {
        return refreshStrategySnapshots();
    }
    return rebuildActiveScanPool();
}
