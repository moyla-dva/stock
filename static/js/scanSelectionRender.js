function renderScanSelection() {
    var detail = document.getElementById('scan-selected-detail');
    var source = document.getElementById('scan-selected-source');
    if (!detail) return;
    detail.innerHTML = '';

    var previewing = Boolean(scanWorkspaceState.previewResult);
    var item = scanWorkspaceState.previewResult || scanWorkspaceState.selectedResult;
    if (!item) {
        if (source) source.textContent = '未选择';
        detail.dataset.preview = 'false';
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = '暂无候选选中';
        detail.appendChild(empty);
        return;
    }
    detail.dataset.preview = previewing ? 'true' : 'false';

    var config = getScanConfig(item._scan_type || scanWorkspaceState.activeType);
    if (source) source.textContent = config.title + (previewing ? ' · 悬停预览' : ' · 当前选中');

    var state = document.createElement('div');
    state.className = 'scan-selected-status scan-selected-status--' + (previewing ? 'preview' : 'selected');
    if (item._detail_loading) {
        state.textContent = '当前选中 · 正在加载完整详情';
    } else if (item._detail_error) {
        state.textContent = '当前选中 · ' + item._detail_error;
    } else {
        state.textContent = previewing
            ? '临时预览 · 未固定'
            : '当前选中 · 等待图表确认';
    }
    detail.appendChild(state);

    var title = document.createElement('div');
    title.className = 'scan-selected-title';

    var identity = document.createElement('div');
    var name = document.createElement('strong');
    name.textContent = item.name || item.code;
    var code = document.createElement('span');
    var strategyText = item.strategy_source_label ? ' · ' + item.strategy_source_label : '';
    var conceptText = scanConceptText(item, 3);
    code.textContent = (item.code || '-')
        + (item.sector ? ' · ' + item.sector : '')
        + (conceptText ? ' · ' + conceptText : '')
        + strategyText;
    identity.appendChild(name);
    identity.appendChild(code);

    var price = document.createElement('b');
    price.textContent = formatScanPrice(item.price);
    title.appendChild(identity);
    title.appendChild(price);
    detail.appendChild(title);

    var signal = document.createElement('div');
    signal.className = 'scan-selected-signal';
    var selectedSignalText = document.createElement('span');
    selectedSignalText.textContent = typeof scanDisplaySignalText === 'function'
        ? scanDisplaySignalText(item)
        : ((item.signal_label || item.signal || '-') + ' ' + (item.signal_name || ''));
    signal.appendChild(selectedSignalText);
    var selectedStage = typeof inferScanPoolStage === 'function' ? inferScanPoolStage(item) : null;
    if (selectedStage) {
        var selectedStageNode = document.createElement('em');
        selectedStageNode.className = 'stock-card__stage stock-card__stage--' + selectedStage.tone;
        selectedStageNode.textContent = selectedStage.label;
        selectedStageNode.title = selectedStage.detail;
        signal.appendChild(selectedStageNode);
    }
    detail.appendChild(signal);

    var explanation = buildScanExplanation(item);
    detail.appendChild(renderScanDecisionVerdict(item, explanation));
    var v2GateSection = renderScanV2GateSection(item);
    if (v2GateSection) detail.appendChild(v2GateSection);
    var tradePlanSection = renderScanTradePlanSection(item);
    if (tradePlanSection) detail.appendChild(tradePlanSection);
    detail.appendChild(renderScanBasisSection(item, explanation, conceptText));
    detail.appendChild(renderScanRiskSection(item, explanation));
    detail.appendChild(renderScanActionSection(item));

    var supportGroup = document.createElement('div');
    supportGroup.className = 'scan-selection-support-stack';
    var relationSection = renderScanProfileRelationSection(item);
    if (relationSection) supportGroup.appendChild(relationSection);
    if (supportGroup.childNodes.length) {
        detail.appendChild(createScanSelectionDisclosure(
            '画像证据',
            '只读关系证据',
            supportGroup,
            false
        ));
    }

    var explainPanel = document.createElement('section');
    explainPanel.className = 'scan-explain-panel';
    var explainHead = document.createElement('div');
    explainHead.className = 'scan-explain-head';
    var explainTitle = document.createElement('strong');
    explainTitle.textContent = '证据说明 · ' + explanation.headline;
    var explainSummary = document.createElement('span');
    explainSummary.textContent = explanation.summary;
    explainHead.appendChild(explainTitle);
    explainHead.appendChild(explainSummary);
    explainPanel.appendChild(explainHead);

    var driverList = document.createElement('div');
    driverList.className = 'scan-explain-list';
    explanation.drivers.forEach(function(driver) {
        var row = document.createElement('div');
        row.className = 'scan-explain-item scan-explain-item--' + driver.tone;
        var label = document.createElement('span');
        label.textContent = driver.label;
        var value = document.createElement('strong');
        value.textContent = driver.value;
        row.appendChild(label);
        row.appendChild(value);
        driverList.appendChild(row);
    });
    explainPanel.appendChild(driverList);

    var cautionList = document.createElement('div');
    cautionList.className = 'scan-explain-cautions';
    explanation.cautions.forEach(function(caution) {
        var itemNode = document.createElement('div');
        itemNode.className = 'scan-explain-caution scan-explain-caution--' + caution.tone;
        itemNode.textContent = caution.label + ' · ' + caution.value;
        cautionList.appendChild(itemNode);
    });
    explainPanel.appendChild(cautionList);

    var scoreline = document.createElement('div');
    scoreline.className = 'scan-selected-scoreline';
    [
        {label: '排名', value: item._visible_rank ? '#' + item._visible_rank : '-'},
        {label: '综合', value: item.final_score == null ? '-' : item.final_score},
        {label: '强度', value: item.rank_score == null ? '-' : item.rank_score},
        {label: '后续上涨', value: formatPercent(item.win_rate)},
        {label: '风险', value: item.risk_score == null ? '-' : item.risk_score}
    ].forEach(function(part) {
        var cell = document.createElement('div');
        var label = document.createElement('span');
        var value = document.createElement('strong');
        label.textContent = part.label;
        value.textContent = part.value;
        cell.appendChild(label);
        cell.appendChild(value);
        scoreline.appendChild(cell);
    });
    var reviewGroup = document.createElement('div');
    reviewGroup.className = 'scan-selection-support-stack';
    reviewGroup.appendChild(renderScanDecisionChecklist(item, explanation, conceptText));
    reviewGroup.appendChild(scoreline);
    detail.appendChild(createScanSelectionDisclosure(
        '样本与评分',
        item.score_confidence_label || '等待样本',
        reviewGroup,
        false
    ));

    var rule = document.createElement('div');
    rule.className = 'scan-selected-rule';
    var ruleLabel = document.createElement('span');
    ruleLabel.textContent = '策略触发条件';
    var ruleValue = document.createElement('strong');
    ruleValue.textContent = item.reason || '-';
    rule.appendChild(ruleLabel);
    rule.appendChild(ruleValue);

    var grid = document.createElement('div');
    grid.className = 'scan-selected-grid';
    [
        ['事件日', item.event_date || item.date || '-'],
        ['数据日', item.data_date || '-'],
        ['板块', item.sector || '-'],
        ['概念', conceptText || '-'],
        ['历史对比', item.history_delta && item.history_delta.label ? item.history_delta.label : (item._history_snapshot_day ? '历史结果' : '-')],
        ['可信度', item.score_confidence_label || '-'],
        ['均值', formatSignedPercent(item.avg_ret)]
    ].forEach(function(part) {
        var cell = document.createElement('div');
        var label = document.createElement('span');
        var value = document.createElement('strong');
        label.textContent = part[0];
        value.textContent = part[1];
        cell.appendChild(label);
        cell.appendChild(value);
        grid.appendChild(cell);
    });

    var dataPanel = document.createElement('section');
    dataPanel.className = 'scan-selected-data-panel';
    dataPanel.appendChild(rule);
    dataPanel.appendChild(grid);
    var evidenceGroup = document.createElement('div');
    evidenceGroup.className = 'scan-selection-support-stack';
    evidenceGroup.appendChild(explainPanel);
    evidenceGroup.appendChild(dataPanel);
    detail.appendChild(createScanSelectionDisclosure('原始证据', explanation.headline, evidenceGroup, false));
}
