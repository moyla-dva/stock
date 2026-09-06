function createStockCardMetric(label, value, tone) {
    var metric = document.createElement('span');
    metric.className = 'stock-card__metric stock-card__metric--' + (tone || 'muted');
    var labelNode = document.createElement('em');
    labelNode.textContent = label;
    var valueNode = document.createElement('strong');
    valueNode.textContent = value == null || value === '' ? '-' : value;
    metric.appendChild(labelNode);
    metric.appendChild(valueNode);
    return metric;
}

function createStockCardEvidence(label, value, tone) {
    if (value == null || value === '') return null;
    var item = document.createElement('span');
    item.className = 'stock-card__evidence-item stock-card__evidence-item--' + (tone || 'muted');
    var labelNode = document.createElement('em');
    labelNode.textContent = label;
    var valueNode = document.createElement('strong');
    valueNode.textContent = value;
    item.appendChild(labelNode);
    item.appendChild(valueNode);
    return item;
}

function scanRiskTone(value) {
    var risk = Number(value || 0);
    if (risk >= 4) return 'danger';
    if (risk > 0) return 'warning';
    return 'positive';
}

function scanConfirmTone(value) {
    var confirm = Number(value || 0);
    if (confirm >= 4) return 'positive';
    if (confirm >= 2) return 'warning';
    return 'muted';
}

function scanScoreTone(value, positiveThreshold, warningThreshold) {
    var score = Number(value);
    if (!Number.isFinite(score)) return 'muted';
    if (score >= positiveThreshold) return 'positive';
    if (score >= warningThreshold) return 'warning';
    return 'muted';
}

function scanRepairEvidenceText(item) {
    if (!item || item._scan_type === 'bottom_div' || item.scan_type === 'bottom_div') return '';
    var sectorCount = Number(item.sector_bottom_div_count);
    var conceptCount = Number(item.concept_bottom_div_count);
    var count = Math.max(
        Number.isFinite(sectorCount) ? sectorCount : 0,
        Number.isFinite(conceptCount) ? conceptCount : 0
    );
    return count > 0 ? (count + ' 条') : '';
}

function scanPoolPrimaryMetrics(item, variant) {
    var stage = typeof inferScanPoolStage === 'function' ? inferScanPoolStage(item) : null;
    var finalScore = item.final_score == null ? item.rank_score : item.final_score;
    if (variant === 'risk') {
        return [
            {label: '阶段', value: stage ? stage.label : (item.signal_name || '-'), tone: stage ? stage.tone : 'warning'},
            {label: '风险', value: item.risk_score == null ? '-' : item.risk_score, tone: scanRiskTone(item.risk_score)},
            {label: '强度', value: finalScore == null ? '-' : finalScore, tone: scanScoreTone(finalScore, 70, 40)}
        ];
    }
    if (variant === 'bottom') {
        return [
            {label: '阶段', value: stage ? stage.label : '观察', tone: stage ? stage.tone : 'muted'},
            {label: '确认', value: item.confirm_score == null ? '-' : item.confirm_score, tone: scanConfirmTone(item.confirm_score)},
            {label: '风险', value: item.risk_score == null ? '-' : item.risk_score, tone: scanRiskTone(item.risk_score)}
        ];
    }
    return [
        {label: '综合', value: finalScore == null ? '-' : finalScore, tone: 'positive'},
        {label: '确认', value: item.confirm_score == null ? '-' : item.confirm_score, tone: scanConfirmTone(item.confirm_score)},
        {label: '风险', value: item.risk_score == null ? '-' : item.risk_score, tone: scanRiskTone(item.risk_score)}
    ];
}

function scanPoolCardSummary(item, variant) {
    var stage = typeof inferScanPoolStage === 'function' ? inferScanPoolStage(item) : null;
    var summary = item.view_model && item.view_model.card_summary
        ? item.view_model.card_summary
        : buildScanCardSummary(item);
    if (!stage) return summary;
    if (variant === 'risk') {
        return stage.detail + ' · ' + (item.reason || summary);
    }
    if (variant === 'bottom') {
        return stage.detail + ' · ' + (item.reason || summary);
    }
    return summary;
}

function createStockCard(item, variant, index) {
    var explanation = buildScanExplanation(item);
    var verdict = typeof scanDecisionVerdict === 'function'
        ? scanDecisionVerdict(item, explanation)
        : null;
    var div = document.createElement('button');
    div.type = 'button';
    div.className = 'stock-card stock-card--' + variant;
    if (item.strategy_status === 'legacy') {
        div.className += ' stock-card--legacy';
    }
    if (isSelectedScanResult(item)) {
        div.className += ' active';
    }
    if (typeof isPreviewScanResult === 'function' && isPreviewScanResult(item)) {
        div.className += ' is-preview';
    }

    var rank = document.createElement('div');
    rank.className = 'stock-card__rank';
    var rankLabel = document.createElement('span');
    rankLabel.textContent = 'RANK';
    var rankValue = document.createElement('strong');
    rankValue.textContent = index == null ? '-' : '#' + (index + 1);
    rank.appendChild(rankLabel);
    rank.appendChild(rankValue);

    var identity = document.createElement('div');
    identity.className = 'stock-card__identity';

    var name = document.createElement('strong');
    name.className = 'stock-card__name';
    name.textContent = item.name || item.code;

    var code = document.createElement('span');
    code.className = 'stock-card__code';
    code.textContent = item.code;
    identity.appendChild(name);
    identity.appendChild(code);
    if (item.sector) {
        var sector = document.createElement('span');
        sector.className = 'stock-card__sector';
        sector.textContent = item.sector;
        identity.appendChild(sector);
    }
    var conceptText = scanConceptText(item, 1);
    if (conceptText) {
        var concepts = document.createElement('span');
        concepts.className = 'stock-card__concepts';
        concepts.textContent = conceptText;
        identity.appendChild(concepts);
    }

    var signal = document.createElement('div');
    signal.className = 'stock-card__signal';
    var signalText = document.createElement('span');
    signalText.textContent = typeof scanDisplaySignalText === 'function'
        ? scanDisplaySignalText(item)
        : ((item.signal_label || item.signal || '-') + ' ' + (item.signal_name || ''));
    signal.appendChild(signalText);
    var stage = typeof inferScanPoolStage === 'function' ? inferScanPoolStage(item) : null;
    if (stage) {
        var stageNode = document.createElement('em');
        stageNode.className = 'stock-card__stage stock-card__stage--' + stage.tone;
        stageNode.textContent = stage.label;
        stageNode.title = stage.detail;
        signal.appendChild(stageNode);
    }
    var role = typeof scanCandidateRole === 'function' ? scanCandidateRole(item) : null;
    if (role) {
        var roleNode = document.createElement('em');
        roleNode.className = 'stock-card__role stock-card__role--' + (role.tone || 'muted');
        roleNode.textContent = role.label;
        roleNode.title = role.detail;
        signal.appendChild(roleNode);
    }
    var primary = document.createElement('div');
    primary.className = 'stock-card__primary';
    scanPoolPrimaryMetrics(item, variant).forEach(function(metric) {
        primary.appendChild(createStockCardMetric(metric.label, metric.value, metric.tone));
    });

    var context = document.createElement('div');
    context.className = 'stock-card__context';
    var price = document.createElement('strong');
    price.className = 'stock-card__price';
    price.textContent = formatScanPrice(item.price);
    context.appendChild(price);
    if (item.strategy_status === 'legacy') {
        var strategy = document.createElement('span');
        strategy.className = 'stock-card__strategy stock-card__strategy--' + (item.strategy_status || 'legacy');
        strategy.textContent = item.strategy_source_label || '旧策略结果';
        context.appendChild(strategy);
    }

    var eventDate = item.event_date || item.date || '-';
    var historyDelta = item.history_delta && item.history_delta.label
        ? item.history_delta.label
        : '';

    var reason = document.createElement('div');
    reason.className = 'stock-card__reason';
    var summaryText = explanation.summary || scanPoolCardSummary(item, variant);
    if (role && role.kind !== 'watch_candidate') {
        summaryText = role.detail + ' · ' + summaryText;
    }
    reason.textContent = summaryText;
    reason.title = item.reason || summaryText;

    var decision = document.createElement('div');
    var decisionTone = verdict ? verdict.tone : (role ? role.tone : 'muted');
    decision.className = 'stock-card__decision stock-card__decision--' + decisionTone;
    var decisionTitle = document.createElement('strong');
    decisionTitle.textContent = verdict ? verdict.title : (role ? role.label : '等待系统结论');
    var decisionDetail = document.createElement('small');
    decisionDetail.textContent = verdict ? verdict.detail : (role ? role.detail : '等待系统按当前语境整理结论');
    decision.appendChild(decisionTitle);
    decision.appendChild(decisionDetail);

    var actionline = document.createElement('div');
    actionline.className = 'stock-card__actionline stock-card__actionline--' + decisionTone;
    var actionLabel = document.createElement('span');
    actionLabel.textContent = '当前动作';
    var actionValue = document.createElement('strong');
    actionValue.textContent = verdict ? verdict.action : '打开单股确认，继续看图表结构和止损位';
    actionline.appendChild(actionLabel);
    actionline.appendChild(actionValue);

    var evidence = document.createElement('div');
    evidence.className = 'stock-card__evidence';
    [
        createStockCardEvidence('事件', eventDate, 'date'),
        createStockCardEvidence('板块', item.sector || UNKNOWN_SCAN_SECTOR, item.sector ? 'context' : 'muted'),
        createStockCardEvidence('修复', scanRepairEvidenceText(item), 'context'),
        createStockCardEvidence('历史', historyDelta, 'context')
    ].forEach(function(node) {
        if (node) evidence.appendChild(node);
    });

    var scores = document.createElement('div');
    scores.className = 'stock-card__scores';
    buildScanScoreBadges(item).filter(function(part) {
        if (variant === 'risk') return ['阶段', '风险', '结构', '确认', '共振', '板指', '概指'].indexOf(part.label) >= 0;
        if (variant === 'bottom') return ['阶段', '确认', '风险', '共振', '板指', '概指', '胜率'].indexOf(part.label) >= 0;
        return ['结构', '确认', '风险', '共振', '板指', '概指', '胜率', '均值'].indexOf(part.label) >= 0;
    }).slice(0, 4).forEach(function(part) {
        var badge = document.createElement('span');
        badge.className = 'stock-card__score stock-card__score--' + part.tone;
        badge.textContent = part.label + ' ' + (part.value == null ? '-' : part.value);
        badge.title = part.hint;
        scores.appendChild(badge);
    });

    div.appendChild(rank);
    div.appendChild(identity);
    div.appendChild(signal);
    div.appendChild(primary);
    div.appendChild(context);
    div.appendChild(decision);
    div.appendChild(actionline);
    div.appendChild(reason);
    div.appendChild(evidence);
    div.appendChild(scores);
    div.onclick = function() {
        selectScanResult(item, variant, false, index == null ? null : index + 1);
    };
    div.ondblclick = function() {
        selectScanResult(item, variant, true, index == null ? null : index + 1);
    };
    div.onmouseenter = function() {
        if (typeof previewScanResult === 'function') {
            previewScanResult(item, variant, index == null ? null : index + 1);
        }
    };
    div.onmouseleave = function() {
        if (typeof clearPreviewScanResult === 'function') {
            clearPreviewScanResult();
        }
    };
    div.onfocus = div.onmouseenter;
    div.onblur = div.onmouseleave;

    return div;
}
