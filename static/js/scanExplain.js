function scanValueText(value, fallback) {
    return value == null || value === '' ? fallback : String(value);
}

function normalizeScanTone(tone) {
    return ['positive', 'warning', 'danger', 'muted'].indexOf(tone) >= 0 ? tone : 'muted';
}

function normalizeScanExplanationItem(item) {
    item = item || {};
    return {
        label: scanValueText(item.label, '-'),
        value: scanValueText(item.value, '-'),
        tone: normalizeScanTone(item.tone),
        hint: scanValueText(item.hint, '')
    };
}

function inferScanPoolStage(item) {
    item = item || {};
    if (item.pool_stage_label) {
        return {
            label: scanValueText(item.pool_stage_label, '-'),
            tone: normalizeScanTone(item.pool_stage_tone),
            detail: scanValueText(item.pool_stage_detail, '池子内阶段判断')
        };
    }

    var scanType = item._scan_type || item.scan_type || '';
    var signalKey = item.signal_key || '';
    var risk = Number(item.risk_score || 0);
    var confirm = Number(item.confirm_score || 0);
    var entrySignals = ['composite_pullback', 'composite_breakout', 'composite_confirm'];

    if (scanType === 'risk' || signalKey.indexOf('composite_top') === 0 || signalKey.indexOf('composite_warning') === 0) {
        if (signalKey === 'composite_stop_loss' || signalKey === 'composite_exit') {
            return {label: '强风险', tone: 'danger', detail: '止损或趋势破坏已触发，优先看风险控制。'};
        }
        if (signalKey === 'composite_take_profit') {
            return {label: '收益保护', tone: 'warning', detail: '已有收益后的回撤或转弱，偏向保护利润。'};
        }
        if (signalKey === 'composite_top_divergence') {
            return {label: '顶部观察', tone: 'warning', detail: '顶背离出现，但尚未形成信号后离场确认。'};
        }
        return risk >= 4
            ? {label: '强预警', tone: 'danger', detail: '风险分较高，需优先确认趋势是否破坏。'}
            : {label: '风险预警', tone: 'warning', detail: '风险条件出现，但尚未升级为强风险。'};
    }

    if (scanType === 'bottom_div' || signalKey === 'composite_bottom_divergence') {
        if (entrySignals.indexOf(signalKey) >= 0) {
            return {label: '已转参与', tone: 'positive', detail: '底背离后已经出现综合买点确认。'};
        }
        if (risk >= 4) {
            return {label: '风险压制', tone: 'danger', detail: '底背离仍被风险条件压制，暂不按买点处理。'};
        }
        if (confirm >= 4 && risk <= 2) {
            return {label: '趋势确认', tone: 'positive', detail: '趋势和量能确认较充分，可继续看是否转入参与候选。'};
        }
        if (confirm >= 2 && risk <= 3) {
            return {label: '观察加强', tone: 'warning', detail: '底背离后有部分确认，但还不是完整买点。'};
        }
        return {label: '未确认', tone: 'muted', detail: '仅出现底背离，尚未得到趋势或量能确认。'};
    }

    return null;
}

function hasBackendScanExplanation(item) {
    var explanation = item && item.explanation;
    return Boolean(
        explanation
        && explanation.headline
        && explanation.summary
        && Array.isArray(explanation.drivers)
    );
}

function normalizeBackendScanExplanation(item) {
    var explanation = item.explanation || {};
    var drivers = (explanation.drivers || []).map(normalizeScanExplanationItem);
    var cautions = (explanation.cautions || []).map(normalizeScanExplanationItem);
    var badges = (explanation.score_badges || []).map(normalizeScanExplanationItem);

    return {
        version: explanation.version || null,
        headline: scanValueText(explanation.headline, '扫描信号'),
        summary: scanValueText(explanation.summary, '-'),
        card_summary: scanValueText(explanation.card_summary, ''),
        drivers: drivers,
        cautions: cautions,
        score_badges: badges
    };
}

function buildLegacyScanExplanation(item) {
    item = item || {};
    var signalName = scanValueText(item.signal_name || item.signal_label || item.signal, '扫描信号');
    var reason = scanValueText(item.reason, signalName);
    var conceptText = typeof scanConceptText === 'function' ? scanConceptText(item, 3) : '';
    var sectorContext = scanValueText(item.sector, '未识别板块') + (conceptText ? ' · ' + conceptText : '');
    var stage = inferScanPoolStage(item);
    var drivers = [
        {label: '事件触发', value: reason, tone: 'positive'},
        {
            label: '分数概览',
            value: '强度 ' + scanValueText(item.rank_score, '-')
                + ' · 风险 ' + scanValueText(item.risk_score, '-'),
            tone: 'muted',
            hint: ''
        },
        {label: '结构背景', value: sectorContext, tone: 'muted', hint: ''}
    ];
    var badges = [
        {label: '强度', value: scanValueText(item.rank_score, '-'), tone: 'muted', hint: '旧结果原始强度'},
        {label: '风险', value: scanValueText(item.risk_score, '-'), tone: 'muted', hint: '旧结果原始风险'},
        {label: '后续上涨', value: typeof formatPercent === 'function' ? formatPercent(item.win_rate) : '-', tone: 'muted', hint: '旧结果的事件后上涨比例'}
    ];
    if (stage) {
        drivers.unshift({label: '池子定位', value: stage.label + ' · ' + stage.detail, tone: stage.tone, hint: ''});
        badges.unshift({label: '阶段', value: stage.label, tone: stage.tone, hint: stage.detail});
    }

    return {
        version: null,
        headline: (stage ? stage.label + ' · ' : '旧结果 · ') + signalName,
        summary: '旧结果缺少后端解释，当前仅显示原始字段',
        card_summary: (stage ? stage.label + ' · ' : '') + reason,
        drivers: drivers,
        cautions: [
            {label: '兼容提示', value: '重算后可获得完整后端解释', tone: 'warning', hint: ''}
        ],
        score_badges: badges
    };
}

function buildIndexedScanExplanation(item) {
    item = item || {};
    var signalName = scanValueText(item.signal_label || item.signal || item.signal_key, '候选摘要');
    var reason = scanValueText(item.reason, signalName);
    var planStatus = scanValueText(item.v2_plan_status || item.plan_status, '待读取');
    var permission = scanValueText(item.v2_permission || item.permission, '待读取');
    var missing = Array.isArray(item.missing_confirmations) ? item.missing_confirmations : [];
    var drivers = [
        {label: '许可', value: permission, tone: 'muted'},
        {label: '计划状态', value: planStatus, tone: planStatus === 'ready' ? 'positive' : 'warning'},
        {label: '状态', value: scanValueText(item.v2_state || item.state, '-'), tone: 'muted'}
    ];
    return {
        version: 'CandidateSummary',
        headline: signalName + ' · SQLite 候选摘要',
        summary: reason + ' · 点选后读取原始快照详情',
        card_summary: reason,
        drivers: drivers,
        cautions: missing.map(function(value) {
            return {label: '待确认', value: String(value), tone: 'warning'};
        }),
        score_badges: [
            {label: '综合', value: scanValueText(item.final_score, '-'), tone: 'muted'},
            {label: '确认', value: scanValueText(item.confirm_score, '-'), tone: 'muted'},
            {label: '风险', value: scanValueText(item.risk_score, '-'), tone: 'muted'}
        ]
    };
}

function buildScanExplanation(item) {
    if (hasBackendScanExplanation(item)) {
        return normalizeBackendScanExplanation(item);
    }
    if (item && item._indexed_summary) {
        return buildIndexedScanExplanation(item);
    }
    return buildLegacyScanExplanation(item);
}

function buildScanScoreBadges(item) {
    var badges = buildScanExplanation(item).score_badges || [];
    var stage = inferScanPoolStage(item);
    if (stage && !badges.some(function(part) { return part.label === '阶段'; })) {
        return [{label: '阶段', value: stage.label, tone: stage.tone, hint: stage.detail}].concat(badges);
    }
    return badges;
}

function buildScanCardSummary(item) {
    var explanation = buildScanExplanation(item);
    var summary = explanation.card_summary || explanation.summary || scanValueText((item || {}).reason, '-');
    var stage = inferScanPoolStage(item);
    if (stage && summary.indexOf(stage.label) < 0) {
        return stage.label + ' · ' + summary;
    }
    return summary;
}
