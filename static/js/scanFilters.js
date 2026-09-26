function scanStrategyRank(item) {
    return item && item.strategy_status === 'current' ? 1 : 0;
}

function scanCompositeScore(item) {
    return scanNumericValue(item, 'final_score', scanNumericValue(item, 'rank_score', 0));
}

function scanV2PriorityScore(item) {
    return scanNumericValue(item, 'v2_priority_score', scanCompositeScore(item));
}

function scanSortScore(item) {
    return scanUsesV2Priority() ? scanV2PriorityScore(item) : scanSystemRankScore(item);
}

function scanUsesV2Priority() {
    return typeof isScanV2StrategyView === 'function' && isScanV2StrategyView();
}

var SCAN_SORT_MODES = ['system', 'sector', 'concept', 'event', 'risk'];
var SCAN_REASON_FILTERS = [
    {key: 'plan_ready', label: 'Plan ready', tone: 'positive', pools: ['opportunity']},
    {key: 'plan_blocked', label: 'Plan blocked', tone: 'danger', pools: ['opportunity']},
    {key: 'macro_veto', label: '宏观否决', tone: 'danger', pools: ['opportunity']},
    {key: 'ma60', label: 'MA60未满足', tone: 'warning', pools: ['opportunity']},
    {key: 'ma250', label: 'MA250下方', tone: 'danger', pools: ['opportunity']},
    {key: 'rr', label: '2R不足', tone: 'danger', pools: ['opportunity']},
    {key: 'chase', label: '追高', tone: 'warning', pools: ['opportunity']},
    {key: 'heat', label: '过热', tone: 'warning', pools: ['opportunity', 'risk']},
    {key: 'wide_stop', label: '止损过宽', tone: 'danger', pools: ['opportunity']},
    {key: 'c_pullback', label: 'C回', tone: 'positive', pools: ['opportunity']},
    {key: 'c_breakout', label: 'C突', tone: 'positive', pools: ['opportunity']},
    {key: 'c_attack', label: 'C爆', tone: 'positive', pools: ['opportunity']},
    {key: 'exit_scale_out', label: '收益保护', tone: 'warning', pools: ['risk']},
    {key: 'exit_sell', label: '离场条件', tone: 'danger', pools: ['risk']}
];
var SCAN_REASON_SIGNAL_ALIASES = {
    c_pullback: {labels: ['C回'], keys: ['v2_pullback']},
    c_breakout: {labels: ['C突'], keys: ['v2_breakout', 'v2_bear_trap_recovery']},
    c_attack: {labels: ['C爆'], keys: ['v2_attack_day', 'v2_ignition']}
};
var SCAN_FILTER_QUERY_DEBOUNCE_MS = 180;
var scanFilterQueryTimer = null;

function normalizeScanSortMode(value) {
    return SCAN_SORT_MODES.indexOf(value) >= 0 ? value : 'system';
}

function getScanManualViewState(filters) {
    filters = filters || scanWorkspaceState.filters || {};
    var sortMode = normalizeScanSortMode(filters.sort);
    var activeCount = 0;
    if (filters.sector) activeCount += 1;
    if (filters.concept) activeCount += 1;
    if (filters.reason) activeCount += 1;
    if (sortMode !== 'system') activeCount += 1;
    return {
        sortMode: sortMode,
        activeCount: activeCount,
        active: activeCount > 0
    };
}

function resetScanContextThemeCache() {
    return null;
}

function getScanContextTheme() {
    return {line: null, source: 'none'};
}

function scanPoolTypeFromItem(item) {
    return item && (item._scan_type || item.scan_type) || scanWorkspaceState.activeType || 'opportunity';
}

function scanV2Model(item) {
    return item && (item.v2_state_model || item.c_signal_v2_state) || {};
}

function scanV2PermissionModel(item) {
    var model = scanV2Model(item);
    var permission = model.v2_permission_model || model.v2PermissionModel || {};
    return permission && typeof permission === 'object' ? permission : {};
}

function scanV2PlanGate(item) {
    var permission = scanV2PermissionModel(item);
    var gate = permission.plan_gate || permission.planGate || {};
    return gate && typeof gate === 'object' ? gate : {};
}

function scanV2ExitGate(item) {
    var model = scanV2Model(item);
    var facts = model.facts || {};
    var gate = facts.exit_gate || facts.exitGate || {};
    return gate && typeof gate === 'object' ? gate : {};
}

function scanV2ReasonTexts(item) {
    item = item || {};
    var model = scanV2Model(item);
    var permission = scanV2PermissionModel(item);
    var gate = scanV2PlanGate(item);
    var texts = [
        item.reason,
        item.v2_macro_veto_reason,
        item.v2MacroVetoReason,
        model.reason,
        model.next_action || model.nextAction,
        permission.reason,
        permission.next_action || permission.nextAction,
        gate.target_label || gate.targetLabel,
        gate.target_source || gate.targetSource
    ];
    [item, model, permission, gate].forEach(function(container) {
        if (!container || typeof container !== 'object') return;
        [
            'block_reasons',
            'blockReasons',
            'required_confirmations',
            'requiredConfirmations',
            'warnings',
            'v2_environment_block_reasons',
            'v2EnvironmentBlockReasons',
            'v2_environment_warnings',
            'v2EnvironmentWarnings'
        ].forEach(function(key) {
            var values = container[key] || [];
            if (!Array.isArray(values)) values = values ? [values] : [];
            texts = texts.concat(values);
        });
    });
    return texts.filter(Boolean).map(String);
}

function scanV2ReasonBlob(item) {
    return scanV2ReasonTexts(item).join(' ');
}

function scanTextContainsAny(text, phrases) {
    return phrases.some(function(phrase) {
        return text.indexOf(phrase) >= 0;
    });
}

function scanSignalMatchesReason(reason, signal, signalKey) {
    var alias = SCAN_REASON_SIGNAL_ALIASES[reason];
    if (!alias) return null;
    return (alias.labels || []).indexOf(signal) >= 0 || (alias.keys || []).indexOf(signalKey) >= 0;
}

function scanReasonFilterOptionsForPool(scanType) {
    scanType = scanType || scanWorkspaceState.activeType || 'opportunity';
    return SCAN_REASON_FILTERS.filter(function(option) {
        return !option.pools || option.pools.indexOf(scanType) >= 0;
    });
}

function scanResultMatchesReasonFilter(item, reason) {
    reason = String(reason || '').trim();
    if (!reason) return true;
    var model = scanV2Model(item);
    var gate = scanV2PlanGate(item);
    var exitGate = scanV2ExitGate(item);
    var signal = scanFirstText(item || {}, ['v2_signal', 'v2Signal', 'signal_label', 'signal']) || model.signal || '';
    var signalKey = item && item.signal_key || '';
    var planStatus = gate.status || model.plan_status || model.planStatus || (item && item.v2_plan_status) || '';
    var state = model.state || '';
    var permission = model.permission || (item && item.v2_permission) || '';
    var markerRole = exitGate.marker_role || exitGate.markerRole || '';
    var text = scanV2ReasonBlob(item);

    if (reason === 'plan_ready') return planStatus === 'ready' || (item && item.v2_priority_group === 'trade_ready');
    if (reason === 'plan_blocked') return planStatus === 'blocked' || state === 'trigger_plan_blocked';
    if (reason === 'macro_veto') return state === 'macro_veto_blocked' || text.indexOf('宏观否决') >= 0 || (permission === 'forbidden' && text.indexOf('大周期') >= 0);
    if (reason === 'ma60') return scanTextContainsAny(text, ['MA60未', 'MA60 未', 'MA60下行', 'MA60 下行', '未满足MA60', '未满足 MA60', '未上行']);
    if (reason === 'ma250') return scanTextContainsAny(text, ['MA250下方', 'MA250 下方', '低于MA250', '低于 MA250', '未站上MA250', '未站上 MA250', '年线下方', '跌破MA250', '跌破 MA250']);
    if (reason === 'rr') return scanTextContainsAny(text, ['收益风险比低于', '收益风险比不足', '低于 2:1', '低于2:1', '2R不足', '不足2R', '未达2R', '未达到2R']);
    if (reason === 'chase') return text.indexOf('追高') >= 0 || text.indexOf('距 MA20') >= 0 || text.indexOf('攻击日涨幅') >= 0;
    if (reason === 'heat') return text.indexOf('过热') >= 0;
    if (reason === 'wide_stop') return text.indexOf('止损距离超过') >= 0 || text.indexOf('止损过宽') >= 0;
    var signalMatch = scanSignalMatchesReason(reason, signal, signalKey);
    if (signalMatch != null) return signalMatch;
    if (reason === 'exit_sell') return markerRole === 'sell';
    if (reason === 'exit_scale_out') return markerRole === 'scale_out';
    return false;
}

function scanCandidateRole(item) {
    if (typeof isScanV2StrategyView === 'function' && isScanV2StrategyView()) {
        var v2Role = scanV2CandidateRole(item);
        if (v2Role) return v2Role;
    }
    var scanType = scanPoolTypeFromItem(item);
    var risk = scanNumericValue(item, 'risk_score', 0);
    var confirm = scanNumericValue(item, 'confirm_score', 0);
    var composite = scanCompositeScore(item);

    if (scanType === 'risk') {
        return {
            kind: 'risk_watch',
            label: risk >= 4 ? '重点风险' : '风险验证',
            tone: risk >= 4 ? 'danger' : 'warning',
            score: 70 + risk * 8,
            detail: '用于确认兑现压力、破位或高位分歧是否扩散。',
            action: risk >= 4 ? '先处理风险，再考虑是否回避。' : '等待风险确认，不按机会票处理。'
        };
    }
    if (scanType === 'bottom_div') {
        var ready = confirm >= 3 && risk <= 2;
        return {
            kind: 'repair_watch',
            label: ready ? '修复候选' : '修复观察',
            tone: ready ? 'positive' : 'warning',
            score: ready ? 84 : 48,
            detail: '低位或背离修复只看确认质量，不提前当作买点。',
            action: ready ? '等待放量或趋势确认后再看机会。' : '先记录，不急于交易。'
        };
    }
    if (risk <= 2 && composite >= 70) {
        return {
            kind: 'opportunity_candidate',
            label: '参与候选',
            tone: 'positive',
            score: 88 + Math.min(18, composite * 0.12),
            detail: '结构、确认和风险组合较好，仍需打开图表确认入场和止损。',
            action: '打开图表确认入场结构、止损距离和仓位。'
        };
    }
    if (composite >= 60) {
        return {
            kind: 'structure_candidate',
            label: '结构候选',
            tone: risk > 2 ? 'warning' : 'muted',
            score: 52,
            detail: '个股存在结构线索，但还需要补确认。',
            action: '回到个股结构与触发条件继续确认。'
        };
    }
    return {
        kind: 'watch_candidate',
        label: '观察候选',
        tone: 'muted',
        score: 0,
        detail: '证据不足，先降低优先级。',
        action: '先观察，不作为优先交易对象。'
    };
}

function scanCandidateQueue(item) {
    if (scanUsesV2Priority() && item && item.v2_priority_group) {
        return {
            key: item.v2_priority_group,
            label: item.v2_priority_label || 'V2状态',
            detail: item.v2_priority_detail || '按 V2 状态模型整理名单。',
            tone: item.v2_priority_tone || 'muted',
            priority: scanNumericValue(item, 'v2_queue_priority', 0)
        };
    }
    var role = scanCandidateRole(item);
    var kind = role && role.kind;
    if (kind === 'opportunity_candidate') {
        return {
            key: 'priority',
            label: '优先跟踪',
            detail: '综合结构较好，等待图表确认入场结构。',
            tone: 'positive',
            priority: 5
        };
    }
    if (kind === 'repair_watch') {
        return {
            key: 'repair',
            label: '修复观察',
            detail: '低位或背离修复，等待右侧确认。',
            tone: 'warning',
            priority: 4
        };
    }
    if (kind === 'risk_watch') {
        return {
            key: 'risk',
            label: '风险验证',
            detail: '用于确认压力是否扩散，不按机会票处理。',
            tone: 'danger',
            priority: 3
        };
    }
    if (kind === 'structure_candidate') {
        return {
            key: 'structure',
            label: '结构备选',
            detail: '个股结构线索存在，但确认不足。',
            tone: 'muted',
            priority: 2
        };
    }
    return {
        key: 'watch',
        label: '观察',
        detail: '证据不足，先降低优先级。',
        tone: 'muted',
        priority: 1
    };
}

function scanSystemRecommendation() {
    var scanType = scanWorkspaceState.activeType;
    if (scanType === 'risk') {
        return {
            title: '先处理风险验证',
            detail: '按 V2 风控状态、个股风险分和事件新近度排序。',
            mode: 'risk'
        };
    }
    if (scanType === 'bottom_div') {
        return {
            title: '先看修复是否成形',
            detail: '按 V2 修复/研究状态、个股确认分和风险排序。',
            mode: 'repair'
        };
    }
    return {
        title: '先看可参与候选',
        detail: '按 V2 许可状态、综合分、个股确认分和风险排序。',
        mode: 'opportunity'
    };
}

function renderScanRecommendation() {
    var title = document.getElementById('scan-recommendation-title');
    var detail = document.getElementById('scan-recommendation-detail');
    if (!title && !detail) return;
    var manualView = getScanManualViewState();
    if (manualView.active) {
        if (title) title.textContent = '手动补充查看';
        if (detail) detail.textContent = '当前有 ' + manualView.activeCount + ' 项手动条件生效。';
        return;
    }
    var recommendation = scanSystemRecommendation();
    if (title) title.textContent = recommendation.title;
    if (detail) detail.textContent = recommendation.detail;
}

function scanSystemRankScore(item) {
    if (scanUsesV2Priority() && item && item.v2_priority_score != null) {
        return scanV2PriorityScore(item);
    }
    var scanType = scanPoolTypeFromItem(item);
    var roleScore = scanCandidateRole(item).score || 0;
    var composite = scanCompositeScore(item);
    var riskScore = scanNumericValue(item, 'risk_score', 0);
    var confirmScore = scanNumericValue(item, 'confirm_score', 0);
    var setupScore = scanNumericValue(item, 'setup_score', 0);
    if (scanType === 'risk') {
        return roleScore
            + riskScore * 18
            + composite * 0.35;
    }
    if (scanType === 'bottom_div') {
        return roleScore
            + Math.max(0, 8 - riskScore) * 8
            + confirmScore * 8
            + setupScore * 3
            + composite * 0.45;
    }
    return roleScore
        + composite
        + confirmScore * 6
        - riskScore * 8;
}

function compareScanResults(a, b) {
    var sort = normalizeScanSortMode(scanWorkspaceState.filters.sort);
    if (sort === 'system') {
        if (scanWorkspaceState.readSource === 'sqlite_index'
            && a && b
            && Number.isFinite(Number(a._read_rank))
            && Number.isFinite(Number(b._read_rank))) {
            return Number(a._read_rank) - Number(b._read_rank);
        }
        return scanSortScore(b) - scanSortScore(a)
            || scanCandidateQueue(b).priority - scanCandidateQueue(a).priority
            || scanStrategyRank(b) - scanStrategyRank(a)
            || String(scanEventDate(b)).localeCompare(String(scanEventDate(a)))
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'event') {
        return scanStrategyRank(b) - scanStrategyRank(a)
            || String(scanEventDate(b)).localeCompare(String(scanEventDate(a)))
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'sector') {
        return String(a && a.sector || '').localeCompare(String(b && b.sector || ''), 'zh-CN')
            || scanSystemRankScore(b) - scanSystemRankScore(a)
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'concept') {
        return String(scanConceptText(a, 1) || '').localeCompare(String(scanConceptText(b, 1) || ''), 'zh-CN')
            || scanSystemRankScore(b) - scanSystemRankScore(a)
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'risk') {
        return scanStrategyRank(b) - scanStrategyRank(a)
            || scanNumericValue(a, 'risk_score', 999) - scanNumericValue(b, 'risk_score', 999)
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    return scanStrategyRank(b) - scanStrategyRank(a)
        || scanCompositeScore(b) - scanCompositeScore(a)
        || String(scanEventDate(b)).localeCompare(String(scanEventDate(a)));
}

function scanResultMatchesFilters(item) {
    var filters = scanWorkspaceState.filters || {};
    var sector = item.sector || '';
    if (filters.sector) {
        if (filters.sector === UNKNOWN_SCAN_SECTOR) {
            if (sector) return false;
        } else if (sector !== filters.sector) {
            return false;
        }
    }
    if (filters.concept && scanConcepts(item).indexOf(filters.concept) < 0) {
        return false;
    }
    if (filters.reason && !scanResultMatchesReasonFilter(item, filters.reason)) {
        return false;
    }

    var query = normalizeFilterText(filters.query);
    if (!query) return true;
    return [
        item.code,
        item.name,
        item.sector,
        scanConceptText(item),
        item.signal_label,
        item.signal,
        item.signal_name,
        item.reason,
        scanV2ReasonBlob(item)
    ].some(function(value) {
        return normalizeFilterText(value).indexOf(query) >= 0;
    });
}

function getVisibleScanResults() {
    var pool = getScanPool(scanWorkspaceState.activeType);
    return (pool.results || [])
        .filter(scanResultMatchesFilters)
        .slice()
        .sort(compareScanResults);
}

function renderScanReasonFilters(poolResults) {
    var container = document.getElementById('scan-reason-filter');
    if (!container) return;
    var filters = scanWorkspaceState.filters || {};
    var options = scanReasonFilterOptionsForPool(scanWorkspaceState.activeType);
    container.innerHTML = '';
    if (!options.length || !scanUsesV2Priority()) {
        container.hidden = true;
        return;
    }
    container.hidden = false;

    var label = document.createElement('span');
    label.className = 'scan-reason-filter__label';
    label.textContent = '原因';
    container.appendChild(label);

    var allButton = document.createElement('button');
    allButton.type = 'button';
    allButton.className = 'scan-reason-chip' + (!filters.reason ? ' active' : '');
    allButton.textContent = '全部';
    allButton.onclick = function() { setScanReasonFilter(''); };
    container.appendChild(allButton);

    options.forEach(function(option) {
        var count = (poolResults || []).filter(function(item) {
            return scanResultMatchesReasonFilter(item, option.key);
        }).length;
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'scan-reason-chip scan-reason-chip--' + (option.tone || 'muted') + (filters.reason === option.key ? ' active' : '');
        button.textContent = option.label + (count ? ' ' + count : '');
        button.onclick = function() { setScanReasonFilter(option.key); };
        container.appendChild(button);
    });
}

function setScanEntryModel(entryModel) {
    var normalized = SCAN_ENTRY_MODELS.some(function (item) { return item.value === entryModel; })
        ? entryModel
        : 'event_close';
    if (scanWorkspaceState.entryModel === normalized) return;
    scanWorkspaceState.entryModel = normalized;
    try {
        window.localStorage.setItem(SCAN_ENTRY_MODEL_STORAGE_KEY, normalized);
    } catch (error) {
        // localStorage 不可用（隐私模式）时仅本次会话生效
    }
    var buttons = document.querySelectorAll('#scan-entry-model-toggle [data-scan-entry-model]');
    buttons.forEach(function (button) {
        var active = button.getAttribute('data-scan-entry-model') === normalized;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    // 口径变更必须重新请求工作台/回放，仅重渲染旧状态毫无意义
    loadScanWorkspace(scanWorkspaceState.activeType, scanWorkspaceState.historyMode ? scanWorkspaceState.historySnapshotDay : '', false);
}

function renderScanEntryModelToggle() {
    var buttons = document.querySelectorAll('#scan-entry-model-toggle [data-scan-entry-model]');
    buttons.forEach(function (button) {
        var active = button.getAttribute('data-scan-entry-model') === scanWorkspaceState.entryModel;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

function renderScanFilters(poolResults) {
    var filters = scanWorkspaceState.filters;
    renderScanEntryModelToggle();
    var search = document.getElementById('scan-search');
    var manualView = getScanManualViewState(filters);

    filters.sort = manualView.sortMode;
    if (search && search.value !== filters.query) search.value = filters.query;

    renderScanReasonFilters(poolResults || []);
    renderScanRecommendation();
}

function renderAfterScanFilterChange() {
    renderActiveScanPool();
    enrichActiveScanProfiles();
}

function clearScanFilterQueryDebounce() {
    if (scanFilterQueryTimer) {
        clearTimeout(scanFilterQueryTimer);
        scanFilterQueryTimer = null;
    }
}

function scheduleScanFilterQueryRender() {
    clearScanFilterQueryDebounce();
    scanFilterQueryTimer = setTimeout(function() {
        scanFilterQueryTimer = null;
        renderAfterScanFilterChange();
    }, SCAN_FILTER_QUERY_DEBOUNCE_MS);
}

function setScanFilterQuery(value) {
    scanWorkspaceState.filters.query = value || '';
    scheduleScanFilterQueryRender();
}

function setScanSectorFilter(value) {
    clearScanFilterQueryDebounce();
    scanWorkspaceState.filters.sector = value || '';
    renderAfterScanFilterChange();
}

function setScanConceptFilter(value) {
    clearScanFilterQueryDebounce();
    scanWorkspaceState.filters.concept = value || '';
    renderAfterScanFilterChange();
}

function setScanReasonFilter(value) {
    clearScanFilterQueryDebounce();
    scanWorkspaceState.filters.reason = value || '';
    renderAfterScanFilterChange();
}

function setScanSort(value) {
    clearScanFilterQueryDebounce();
    scanWorkspaceState.filters.sort = normalizeScanSortMode(value);
    renderAfterScanFilterChange();
}

function resetScanFilters() {
    clearScanFilterQueryDebounce();
    scanWorkspaceState.filters.query = '';
    scanWorkspaceState.filters.sector = '';
    scanWorkspaceState.filters.concept = '';
    scanWorkspaceState.filters.reason = '';
    scanWorkspaceState.filters.sort = 'system';
    renderAfterScanFilterChange();
}
