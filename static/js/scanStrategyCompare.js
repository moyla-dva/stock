var SCAN_STRATEGY_VIEW_MODES = ['legacy', 'v2'];

function normalizeScanStrategyView(value) {
    return SCAN_STRATEGY_VIEW_MODES.indexOf(value) >= 0 ? value : 'v2';
}

function scanFirstText(item, keys) {
    item = item || {};
    for (var i = 0; i < keys.length; i++) {
        var value = item[keys[i]];
        if (value != null && String(value).trim()) {
            return String(value).trim();
        }
    }
    return '';
}

function scanBooleanField(item, snakeKey, camelKey) {
    item = item || {};
    if (item[snakeKey] != null) return Boolean(item[snakeKey]);
    if (item[camelKey] != null) return Boolean(item[camelKey]);
    return false;
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
    var label = scanFirstText(item, ['signal_label', 'signalLabel', 'signalCode', 'signal']) || '-';
    var name = scanFirstText(item, ['signal_name']);
    if (!name && (item.signalKey || item.signalLabel || item.signalCode)) {
        name = scanFirstText(item, ['name']);
    }
    return (label + ' ' + name).trim();
}

function scanV2SignalText(item) {
    item = item || {};
    var signal = scanFirstText(item, ['v2_signal', 'v2Signal']);
    if (!signal) return scanLegacySignalText(item);
    return (signal + ' ' + scanFirstText(item, ['v2_signal_name', 'v2SignalName'])).trim();
}

function scanDisplaySignalText(item) {
    return isScanV2StrategyView() ? scanV2SignalText(item) : scanLegacySignalText(item);
}

function scanV2CandidateRole(item) {
    item = item || {};
    var roleLabel = scanFirstText(item, ['v2_role_label', 'v2RoleLabel']);
    if (!roleLabel) return null;
    var role = scanFirstText(item, ['v2_role', 'v2Role']) || 'candidate';
    var requiresPlan = scanBooleanField(item, 'requires_trade_plan', 'requiresTradePlan');
    var requiresStop = scanBooleanField(item, 'requires_stop_loss', 'requiresStopLoss');
    return {
        kind: 'v2_' + role,
        label: roleLabel,
        tone: scanFirstText(item, ['v2_tone', 'v2Tone']) || 'muted',
        score: role === 'entry' ? 90 : (role === 'risk' ? 80 : (role === 'watch' ? 48 : 36)),
        detail: scanFirstText(item, ['v2_detail', 'v2Detail', 'v2_state_label', 'v2StateLabel']) || 'V2 语义定位',
        action: scanFirstText(item, ['trade_intent_label', 'tradeIntentLabel']) || (requiresPlan ? '进入交易计划校验。' : '先观察，不直接交易。'),
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
        detail: (scanFirstText(item, ['v2_detail', 'v2Detail']) || (explanation && explanation.summary) || item.reason || '等待更多结构确认')
            + ' · ' + planText + ' / ' + stopText,
        action: scanFirstText(item, ['trade_intent_label', 'tradeIntentLabel']) || role.action
    };
}

function scanV2PointCategory(item, fallbackCategory) {
    var role = scanFirstText(item, ['v2_role', 'v2Role']);
    if (role === 'entry') return 'entry';
    if (role === 'risk') return 'risk';
    return fallbackCategory || 'observe';
}

function scanV2PointChartLabel(item, signal) {
    item = item || {};
    signal = signal || scanFirstText(item, ['v2_signal', 'v2Signal']);
    if (signal !== 'C风') return signal;
    var state = scanFirstText(item, ['v2_state', 'v2State']);
    var name = scanFirstText(item, ['v2_signal_name', 'v2SignalName']);
    if (state === 'risk_top_watch' || name.indexOf('顶部') >= 0) return '风顶';
    if (state === 'risk_warning' || name.indexOf('预警') >= 0) return '风警';
    if (state === 'risk_stop_loss' || name.indexOf('止损') >= 0) return '风损';
    if (state === 'risk_take_profit' || name.indexOf('收益') >= 0) return '风盈';
    if (state === 'risk_exit' || name.indexOf('离场') >= 0) return '风离';
    return 'C风';
}

function scanPointStrategyMeta(point, meta) {
    point = point || {};
    meta = meta || {};
    if (!isScanV2StrategyView()) return meta;
    var signal = scanFirstText(point, ['v2_signal', 'v2Signal']);
    if (!signal) return meta;
    return Object.assign({}, meta, {
        label: signal,
        name: scanFirstText(point, ['v2_signal_name', 'v2SignalName']) || meta.name || '',
        chartLabel: scanV2PointChartLabel(point, signal),
        detail: scanFirstText(point, ['v2_detail', 'v2Detail']) || meta.detail || '',
        category: scanV2PointCategory(point, meta.category)
    });
}

function refreshActiveScanChartFocusStrategyView() {
    if (!activeScanChartFocus) return;
    activeScanChartFocus.signalLabel = scanDisplaySignalText(activeScanChartFocus)
        || activeScanChartFocus.signalLabel
        || '扫描';
    activeScanChartFocus.signalName = '';
    if (typeof scanCandidateRole === 'function') {
        var role = scanCandidateRole(activeScanChartFocus);
        activeScanChartFocus.roleLabel = role ? role.label : '';
        activeScanChartFocus.roleAction = role ? role.action : '';
        activeScanChartFocus.roleTone = role ? role.tone : '';
    }
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
    var view = getScanStrategyView();
    document.querySelectorAll('[data-scan-strategy-toggle], #scan-strategy-view-toggle').forEach(function(node) {
        node.querySelectorAll('[data-scan-strategy-view]').forEach(function(button) {
            var active = button.dataset.scanStrategyView === view;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        var label = node.querySelector('span');
        if (label) {
            label.textContent = view === 'v2' ? 'V2语义' : '旧C字段';
        }
    });
}

function setScanStrategyView(view) {
    scanWorkspaceState.strategyView = normalizeScanStrategyView(view);
    renderScanStrategyViewToggle();
    refreshActiveScanChartFocusStrategyView();
    if (lastData && typeof renderChart === 'function') {
        renderChart(lastAnalysisData || lastData);
    }
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
window.scanV2PointChartLabel = scanV2PointChartLabel;
window.scanPointStrategyMeta = scanPointStrategyMeta;
window.refreshActiveScanChartFocusStrategyView = refreshActiveScanChartFocusStrategyView;
window.scanLegacyViewExplanation = scanLegacyViewExplanation;
window.renderScanStrategyViewToggle = renderScanStrategyViewToggle;
window.setScanStrategyView = setScanStrategyView;
