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
    var label = scanFirstText(item, ['signal_label', 'signalLabel', 'signalCode', 'signal', 'label']) || '-';
    var name = scanFirstText(item, ['signal_name', 'signalName']);
    if (!name && (item.signal_key || item.signalKey || item.signalLabel || item.signalCode || item.label)) {
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

function scanV2StateModel(item) {
    item = item || {};
    return item.c_signal_v2_state || item.v2_state_model || item.v2StateModel || null;
}

function scanV2StateSignalText(model) {
    if (!model) return '';
    return ((model.signal || '') + ' ' + (model.signal_name || model.signalName || '')).trim();
}

function scanStrategyScopeText() {
    return isScanV2StrategyView()
        ? 'V2状态模型对比 · 旧C事件保留为迁移来源'
        : '旧C字段对照 · 显示原信号名称与原评分';
}

function scanV2CandidateRole(item) {
    item = item || {};
    var model = scanV2StateModel(item);
    if (model && (model.role_label || model.permission_label)) {
        var modelRole = model.role || model.permission || 'watch';
        return {
            kind: 'v2_' + modelRole,
            label: model.role_label || model.permission_label,
            tone: model.tone || 'muted',
            score: modelRole === 'entry' ? 90 : (modelRole === 'risk' ? 80 : (modelRole === 'watch' ? 48 : 36)),
            detail: model.detail || model.reason || model.state_label || 'V2 状态模型',
            action: model.next_action || model.trade_intent_label || '按 V2 状态模型处理',
            requiresPlan: Boolean(model.requires_trade_plan || model.requiresTradePlan),
            requiresStop: Boolean(model.requires_stop_loss || model.requiresStopLoss)
        };
    }
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
    var model = scanV2StateModel(item);
    if (model) {
        var modelPlanText = model.requires_trade_plan || model.requiresTradePlan ? '需要交易计划' : '不生成入场计划';
        var modelStopText = model.requires_stop_loss || model.requiresStopLoss ? '需要入场止损价' : '不要求入场止损价';
        return {
            tone: model.tone || 'muted',
            title: (model.role_label || model.permission_label || 'V2定位') + ' · ' + (scanV2StateSignalText(model) || model.state_label || '状态模型'),
            detail: (model.reason || model.detail || (explanation && explanation.summary) || item.reason || '等待更多结构确认')
                + ' · ' + modelPlanText + ' / ' + modelStopText,
            action: model.next_action || model.trade_intent_label || '按 V2 状态模型处理'
        };
    }
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

function scanStrategyDeltaItems(item) {
    item = item || {};
    if (!isScanV2StrategyView()) {
        return [
            { label: '显示口径', value: '旧C字段与原信号名称' },
            { label: '评分口径', value: '原建仓/确认/风险分' },
            { label: '用途', value: '用于和 V2 语义层逐项对照' }
        ];
    }

    var legacyText = scanLegacySignalText(item);
    var v2Text = scanV2SignalText(item);
    var model = scanV2StateModel(item);
    var role = scanV2CandidateRole(item);
    var action = scanFirstText(item, ['trade_intent_label', 'tradeIntentLabel'])
        || (role && role.action)
        || '先按语义定位处理';
    var planText = role && role.requiresPlan ? '需要交易计划' : '不生成入场计划';
    var stopText = role && role.requiresStop ? '需要入场止损价' : '不要求入场止损价';
    if (model) {
        var modelSignalText = scanV2StateSignalText(model) || v2Text || legacyText || '暂无信号';
        var modelPlanText = model.requires_trade_plan || model.requiresTradePlan ? '需要交易计划' : '不生成入场计划';
        var modelStopText = model.requires_stop_loss || model.requiresStopLoss ? '需要入场止损价' : '不要求入场止损价';
        return [
            {
                label: '信号映射',
                value: (legacyText && legacyText !== modelSignalText)
                    ? (legacyText + ' -> ' + modelSignalText)
                    : modelSignalText
            },
            { label: '状态模型', value: (model.state_label || '-') + ' / ' + (model.permission_label || '-') },
            { label: '执行含义', value: (model.next_action || model.trade_intent_label || '按 V2 状态模型处理') + ' · ' + modelPlanText + ' / ' + modelStopText },
            { label: '指标口径', value: '已接入 V2 事实/许可状态模型，旧C事件仍保留为迁移来源' }
        ];
    }

    return [
        {
            label: '信号映射',
            value: (legacyText && v2Text && legacyText !== v2Text)
                ? (legacyText + ' -> ' + v2Text)
                : (v2Text || legacyText || '暂无信号')
        },
        { label: 'V2定位', value: role ? role.label : '观察' },
        { label: '执行含义', value: action + ' · ' + planText + ' / ' + stopText },
        { label: '指标口径', value: '沿用当前策略指标与评分，尚未启用 V2 独立阈值' }
    ];
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
        return ['V2定位', 'V2状态'].indexOf(driver.label) < 0;
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
    document.querySelectorAll('[data-scan-strategy-scope]').forEach(function(node) {
        node.textContent = scanStrategyScopeText();
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
window.scanV2StateModel = scanV2StateModel;
window.scanStrategyScopeText = scanStrategyScopeText;
window.scanV2CandidateRole = scanV2CandidateRole;
window.scanV2DecisionVerdict = scanV2DecisionVerdict;
window.scanV2PointChartLabel = scanV2PointChartLabel;
window.scanStrategyDeltaItems = scanStrategyDeltaItems;
window.scanPointStrategyMeta = scanPointStrategyMeta;
window.refreshActiveScanChartFocusStrategyView = refreshActiveScanChartFocusStrategyView;
window.scanLegacyViewExplanation = scanLegacyViewExplanation;
window.renderScanStrategyViewToggle = renderScanStrategyViewToggle;
window.setScanStrategyView = setScanStrategyView;
