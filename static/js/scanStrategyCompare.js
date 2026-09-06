var SCAN_STRATEGY_VIEW_MODES = ['legacy', 'v2'];

function normalizeScanStrategyView(value) {
    return SCAN_STRATEGY_VIEW_MODES.indexOf(value) >= 0 ? value : 'v2';
}

function getScanStrategyView() {
    return normalizeScanStrategyView(scanWorkspaceState.strategyView);
}

function isScanV2StrategyView() {
    return getScanStrategyView() === 'v2';
}

function isScanLegacyStrategyView() {
    return getScanStrategyView() === 'legacy';
}

function scanLegacySignalText(item) {
    item = item || {};
    return ((item.signal_label || item.signal || '-') + ' ' + (item.signal_name || '')).trim();
}

function scanV2SignalText(item) {
    item = item || {};
    if (!item.v2_signal) return scanLegacySignalText(item);
    return (item.v2_signal + ' ' + (item.v2_signal_name || '')).trim();
}

function scanDisplaySignalText(item) {
    return isScanV2StrategyView() ? scanV2SignalText(item) : scanLegacySignalText(item);
}

function scanV2CandidateRole(item) {
    item = item || {};
    if (!item.v2_role_label) return null;
    var role = item.v2_role || 'candidate';
    var requiresPlan = Boolean(item.requires_trade_plan);
    var requiresStop = Boolean(item.requires_stop_loss);
    return {
        kind: 'v2_' + role,
        label: item.v2_role_label,
        tone: item.v2_tone || 'muted',
        score: role === 'entry' ? 90 : (role === 'risk' ? 80 : (role === 'watch' ? 48 : 36)),
        detail: item.v2_detail || item.v2_state_label || 'V2 语义定位',
        action: item.trade_intent_label || (requiresPlan ? '进入交易计划校验。' : '先观察，不直接交易。'),
        requiresPlan: requiresPlan,
        requiresStop: requiresStop
    };
}

function scanV2DecisionVerdict(item, explanation) {
    item = item || {};
    var role = scanV2CandidateRole(item);
    if (!role) return null;
    var planText = role.requiresPlan ? '需要交易计划' : '不生成入场计划';
    var stopText = role.requiresStop ? '需要入场止损价' : '不要求入场止损价';
    return {
        tone: role.tone,
        title: role.label + ' · ' + scanV2SignalText(item),
        detail: (item.v2_detail || (explanation && explanation.summary) || item.reason || '等待更多结构确认')
            + ' · ' + planText + ' / ' + stopText,
        action: item.trade_intent_label || role.action
    };
}

function scanLegacyViewExplanation(item) {
    var explanation = hasBackendScanExplanation(item)
        ? normalizeBackendScanExplanation(item)
        : buildLegacyScanExplanation(item);
    var signalName = scanLegacySignalText(item);
    explanation.headline = signalName;
    explanation.drivers = (explanation.drivers || []).filter(function(driver) {
        return driver.label !== 'V2定位';
    });
    explanation.score_badges = (explanation.score_badges || []).filter(function(badge) {
        return badge.label !== '定位';
    });
    return explanation;
}

function renderScanStrategyViewToggle() {
    var node = document.getElementById('scan-strategy-view-toggle');
    if (!node) return;
    var view = getScanStrategyView();
    node.querySelectorAll('[data-scan-strategy-view]').forEach(function(button) {
        var active = button.dataset.scanStrategyView === view;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    var label = document.getElementById('scan-strategy-view-current');
    if (label) {
        label.textContent = view === 'v2' ? 'V2语义' : '旧C字段';
    }
}

function setScanStrategyView(view) {
    scanWorkspaceState.strategyView = normalizeScanStrategyView(view);
    renderScanStrategyViewToggle();
    if (typeof renderActiveScanPool === 'function') {
        renderActiveScanPool();
    }
    if (typeof renderScanSelection === 'function') {
        renderScanSelection();
    }
    if (typeof renderScanCandidateContext === 'function') {
        renderScanCandidateContext();
    }
}

window.normalizeScanStrategyView = normalizeScanStrategyView;
window.getScanStrategyView = getScanStrategyView;
window.isScanV2StrategyView = isScanV2StrategyView;
window.isScanLegacyStrategyView = isScanLegacyStrategyView;
window.scanDisplaySignalText = scanDisplaySignalText;
window.scanV2CandidateRole = scanV2CandidateRole;
window.scanV2DecisionVerdict = scanV2DecisionVerdict;
window.scanLegacyViewExplanation = scanLegacyViewExplanation;
window.renderScanStrategyViewToggle = renderScanStrategyViewToggle;
window.setScanStrategyView = setScanStrategyView;
