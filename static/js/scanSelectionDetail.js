function scanChecklistTone(value, positiveThreshold, warningThreshold) {
    var number = Number(value);
    if (!Number.isFinite(number)) return 'muted';
    if (number >= positiveThreshold) return 'positive';
    if (number >= warningThreshold) return 'warning';
    return 'muted';
}

function createScanChecklistItem(label, title, detail, tone) {
    var item = document.createElement('div');
    item.className = 'scan-check-item scan-check-item--' + (tone || 'muted');
    var mark = document.createElement('span');
    mark.className = 'scan-check-item__mark';
    mark.textContent = '';
    var copy = document.createElement('div');
    var labelNode = document.createElement('em');
    labelNode.textContent = label;
    var titleNode = document.createElement('strong');
    titleNode.textContent = title || '-';
    var detailNode = document.createElement('small');
    detailNode.textContent = detail || '-';
    copy.appendChild(labelNode);
    copy.appendChild(titleNode);
    copy.appendChild(detailNode);
    item.appendChild(mark);
    item.appendChild(copy);
    return item;
}

function scanDecisionVerdict(item, explanation) {
    if (typeof isScanV2StrategyView === 'function' && isScanV2StrategyView()) {
        var v2Verdict = scanV2DecisionVerdict(item, explanation);
        if (v2Verdict) return v2Verdict;
    }
    var plan = item.trade_plan || null;
    if (plan) {
        var planTone = plan.status === 'ready'
            ? 'positive'
            : (plan.status === 'risk_control' || plan.status === 'blocked' ? 'danger' : 'warning');
        var forbidden = Array.isArray(plan.forbidden_reasons) && plan.forbidden_reasons.length
            ? ' · ' + plan.forbidden_reasons[0]
            : '';
        var nextActions = Array.isArray(plan.next_actions) ? plan.next_actions : [];
        var permission = plan.permission || {};
        return {
            tone: planTone,
            title: plan.status_label ? (plan.status_label + ' · ' + (plan.plan_type_label || '交易计划')) : (plan.title || '交易计划'),
            detail: (plan.detail || explanation.summary || item.reason || '等待交易计划确认') + forbidden,
            action: permission.risk_action || nextActions[0] || '先确认止损和仓位，再决定动作'
        };
    }

    var scanType = item._scan_type || item.scan_type || scanWorkspaceState.activeType;
    var risk = Number(item.risk_score || 0);
    var confirm = Number(item.confirm_score || 0);
    var confidence = item.score_confidence_level || 'empty';
    var stage = typeof inferScanPoolStage === 'function' ? inferScanPoolStage(item) : null;
    var role = typeof scanCandidateRole === 'function' ? scanCandidateRole(item) : null;
    if (scanType === 'risk') {
        return {
            tone: risk >= 4 ? 'danger' : 'warning',
            title: role ? role.label : (risk >= 4 ? '优先处理风险' : '风险观察'),
            detail: (role ? role.detail + ' · ' : '') + (stage ? stage.detail + ' · ' : '') + (item.reason || explanation.summary || '风险信号待确认'),
            action: role ? role.action : (risk >= 4 ? '先看止盈/止损，再决定是否回避' : '等待图表确认，不追高')
        };
    }
    if (scanType === 'bottom_div') {
        var ready = confirm >= 3 && risk <= 2;
        return {
            tone: ready ? 'positive' : 'warning',
            title: role ? role.label : (ready ? '可转入机会观察' : '底背离先观察'),
            detail: (role ? role.detail + ' · ' : '') + (stage ? stage.detail + ' · ' : '') + '确认 ' + (item.confirm_score == null ? '-' : item.confirm_score) + ' · 风险 ' + (item.risk_score == null ? '-' : item.risk_score),
            action: role ? role.action : (ready ? '等待放量或趋势确认后再看机会' : '先记录，不急于交易')
        };
    }
    var actionable = risk <= 2 && (confidence === 'high' || confidence === 'medium' || confidence === 'low');
    return {
        tone: actionable ? 'positive' : (risk > 2 ? 'warning' : 'muted'),
        title: role && role.kind !== 'watch_candidate' ? role.label : (actionable ? '候选可跟踪' : (risk > 2 ? '信号有压力' : '样本待验证')),
        detail: (role && role.kind !== 'watch_candidate' ? role.detail + ' · ' : '') + (explanation.summary || item.reason || '等待更多确认'),
        action: role && role.kind !== 'watch_candidate' ? role.action : (actionable ? '打开图表确认入场结构和止损位' : '先观察，不直接当作买点')
    };
}

function renderScanDecisionVerdict(item, explanation) {
    var verdict = scanDecisionVerdict(item, explanation);
    var panel = document.createElement('section');
    panel.className = 'scan-decision-verdict scan-decision-verdict--' + verdict.tone;
    var copy = document.createElement('div');
    var label = document.createElement('span');
    label.textContent = '决策结论';
    var title = document.createElement('strong');
    title.textContent = verdict.title;
    var detail = document.createElement('small');
    detail.textContent = verdict.detail;
    copy.appendChild(label);
    copy.appendChild(title);
    copy.appendChild(detail);
    var action = document.createElement('em');
    action.textContent = verdict.action;
    panel.appendChild(copy);
    panel.appendChild(action);
    return panel;
}

function formatTradePlanPrice(value) {
    if (value == null || Number.isNaN(Number(value))) return '-';
    return Number(value).toFixed(2);
}

function formatTradePlanPercent(value) {
    if (value == null || Number.isNaN(Number(value))) return '-';
    return Number(value).toFixed(2) + '%';
}

function formatTradePlanRiskReward(plan) {
    var rr = (plan && plan.risk_reward) || {};
    if (rr.ratio != null) {
        return '收益风险比 ' + Number(rr.ratio).toFixed(2) + ':1';
    }
    if (rr.r2_price != null && rr.r3_price != null) {
        return '2R ' + formatTradePlanPrice(rr.r2_price) + ' / 3R ' + formatTradePlanPrice(rr.r3_price);
    }
    return '目标待确认';
}

function formatTradePlanExecutionConstraint(plan) {
    var constraints = Array.isArray(plan && plan.execution_constraints) ? plan.execution_constraints : [];
    if (!constraints.length) return null;
    var primary = constraints[0];
    return {
        title: primary.label || '执行约束',
        detail: primary.detail || '先确认执行价格，不追过热形态',
        tone: primary.severity === 'warning' ? 'warning' : 'muted'
    };
}

function renderScanTradePlanSection(item) {
    var plan = item && item.trade_plan;
    if (!plan) return null;

    var permission = plan.permission || {};
    var entry = plan.entry || {};
    var stop = plan.stop || {};
    var position = plan.position || {};
    var structures = plan.technical_structures || {};
    var clock = structures.williams_clock || {};
    var section = createScanDetailSection(
        '交易计划',
        plan.latest_date || item.date || '-',
        'scan-detail-section--trade-plan'
    );
    var grid = document.createElement('div');
    grid.className = 'scan-detail-basis-grid scan-detail-basis-grid--trade-plan';

    var permissionTone = plan.status === 'ready'
        ? 'positive'
        : (plan.status === 'risk_control' || plan.status === 'blocked' ? 'danger' : 'warning');
    var entryTone = entry.state === 'triggered' ? 'positive' : (entry.state === 'waiting' ? 'warning' : 'muted');
    var stopTone = stop.too_wide || stop.price == null ? 'danger' : 'positive';
    var clockTone = clock.state === 'countdown' || clock.state === 'expanding'
        ? 'warning'
        : (clock.state === 'neutral' ? 'muted' : 'positive');

    var stopTitle = stop.price == null
        ? '止损待定'
        : ('止损 ' + formatTradePlanPrice(stop.price));
    var stopDetail = stop.price == null
        ? '没有止损位就不进入执行'
        : ((stop.basis || '结构止损') + ' · 距离 ' + formatTradePlanPercent(stop.distance_pct));
    var positionDetail = position.risk_per_share == null
        ? (position.formula || '可承受亏损金额 / 每股风险')
        : (position.suggested_shares == null
            ? ('每股风险 ' + Number(position.risk_per_share).toFixed(3) + ' · 再反推股数')
            : ('建议 ' + Number(position.suggested_shares).toFixed(0) + ' 股 · 估算风险 ' + formatTradePlanPrice(position.estimated_risk_amount)));
    var riskReward = plan.risk_reward || {};
    var executionConstraint = formatTradePlanExecutionConstraint(plan);

    var checklistItems = [
        createScanChecklistItem(
            '权限',
            permission.mode_label || plan.status_label || '-',
            permission.action || plan.detail || '-',
            permissionTone
        ),
        createScanChecklistItem(
            '入场',
            entry.label || '等待触发',
            entry.trigger_price == null
                ? (entry.detail || '当前不直接给买点')
                : ('触发价 ' + formatTradePlanPrice(entry.trigger_price) + ' · ' + (entry.detail || '等待图表确认')),
            entryTone
        ),
        createScanChecklistItem(
            '止损',
            stopTitle,
            stopDetail,
            stopTone
        ),
        createScanChecklistItem(
            '仓位',
            position.risk_per_share == null ? '先填风险预算' : '可计算',
            positionDetail,
            stop.price == null ? 'warning' : 'positive'
        ),
        createScanChecklistItem(
            '收益风险',
            riskReward.label || '目标待确认',
            formatTradePlanRiskReward(plan),
            riskReward.status === 'fail' ? 'danger' : (riskReward.status === 'pending' ? 'warning' : 'positive')
        ),
        createScanChecklistItem(
            '威廉时钟',
            clock.state_label || '未计算',
            clock.summary || '只决定是否值得研究，不预测方向',
            clockTone
        ),
        createScanChecklistItem(
            '失效',
            Array.isArray(plan.invalidation_conditions) && plan.invalidation_conditions.length ? plan.invalidation_conditions[0] : '等待失效条件',
            Array.isArray(plan.protection_rules) && plan.protection_rules.length ? plan.protection_rules[0] : '有浮盈后转成利润保护',
            plan.status === 'risk_control' ? 'danger' : 'warning'
        )
    ];
    if (executionConstraint) {
        checklistItems.splice(4, 0, createScanChecklistItem(
            '执行',
            executionConstraint.title,
            executionConstraint.detail,
            executionConstraint.tone
        ));
    }
    checklistItems.forEach(function(node) {
        grid.appendChild(node);
    });

    section.appendChild(grid);
    return section;
}

function renderScanV2GateSection(item) {
    if (!item || typeof isScanV2StrategyView !== 'function' || !isScanV2StrategyView()) return null;
    if (typeof scanV2DecisionFacts !== 'function') return null;
    var facts = scanV2DecisionFacts(item);
    var model = facts.model || {};
    if (!model || !model.version) return null;

    var planGate = facts.planGate;
    var targetStructure = facts.targetStructure || {};
    var exitGate = facts.exitGate || {};
    var macroTide = facts.macroTide || {};
    var permission = item.v2_permission || model.permission || '-';
    var queue = item.v2_queue_label || model.state_label || '-';
    var permissionTone = typeof scanV2ToneForPermission === 'function' ? scanV2ToneForPermission(permission) : 'muted';
    var planTone = !planGate
        ? 'muted'
        : (typeof scanV2PlanGateTone === 'function' ? scanV2PlanGateTone(planGate.status) : 'warning');
    var targetText = typeof scanV2TargetText === 'function' ? scanV2TargetText(targetStructure, planGate, item) : '';
    var targetDetail = typeof scanV2TargetDetail === 'function' ? scanV2TargetDetail(targetStructure, planGate, item) : '';
    var stopText = typeof scanV2StopText === 'function' ? scanV2StopText(planGate) : '';
    var issueText = typeof scanV2PlanGateIssue === 'function' ? scanV2PlanGateIssue(planGate) : '';
    var markerRole = exitGate.marker_role || exitGate.markerRole || '';
    var markerLabel = typeof scanV2MarkerRoleLabel === 'function'
        ? scanV2MarkerRoleLabel(markerRole)
        : markerRole;
    var exitTone = markerRole === 'sell' ? 'danger' : (markerRole === 'scale_out' ? 'warning' : 'muted');
    var targetFallback = '目标待确认（旧快照无目标结构）';
    if (typeof model.signal === 'string' && model.signal) {
        if (model.signal === 'C回') targetFallback = 'C回目标优先取箱体上沿';
        else if (model.signal === 'C突' || model.signal === 'C爆') targetFallback = 'C突/C爆目标优先取上方结构阻力';
        else targetFallback = model.signal + ' 为观察/风控信号，不生成入场目标';
    }

    var section = createScanDetailSection(
        'V2闸门',
        model.latest_date || item.date || '-',
        'scan-detail-section--v2-gate'
    );
    var grid = document.createElement('div');
    grid.className = 'scan-detail-basis-grid scan-detail-basis-grid--v2-gate';

    [
        createScanChecklistItem(
            '许可',
            permission,
            queue + ' · ' + (model.permission_label || model.state_label || model.reason || '-'),
            permissionTone
        ),
        createScanChecklistItem(
            'Plan',
            planGate ? (scanV2PlanGateText(planGate) || planGate.status_label || planGate.status) : '不生成入场计划',
            issueText || (planGate ? '入场价、止损、目标和 R/R 已进入校验' : '观察/风控语义不要求入场止损价'),
            planTone
        ),
        createScanChecklistItem(
            '目标',
            targetText || '目标待确认',
            targetDetail || ((targetStructure || {}).target_selection_reason || targetFallback),
            targetText ? 'positive' : 'warning'
        ),
        createScanChecklistItem(
            '止损',
            stopText || (model.requires_stop_loss ? '止损待确认' : '不要求入场止损'),
            model.requires_stop_loss ? '入场类必须有结构止损；观察/风控类只给失效或处理条件' : (model.plan_scope || '观察或风控语义'),
            model.requires_stop_loss && !stopText ? 'danger' : 'muted'
        ),
        createScanChecklistItem(
            '宏观',
            macroTide.label || macroTide.permission || '宏观待核',
            macroTide.summary || '大周期只负责许可或否决，不制造买点',
            macroTide.permission === 'forbidden' ? 'danger' : (macroTide.permission === 'watch' ? 'warning' : 'positive')
        ),
        createScanChecklistItem(
            'Exit',
            markerLabel || '观察',
            exitGate.summary || '未触发收益保护或离场条件，继续按结构观察',
            exitTone
        )
    ].forEach(function(node) {
        grid.appendChild(node);
    });

    section.appendChild(grid);
    return section;
}

function renderScanDecisionChecklist(item, explanation, conceptText) {
    var checklist = document.createElement('section');
    checklist.className = 'scan-decision-checklist';
    var stage = typeof inferScanPoolStage === 'function' ? inferScanPoolStage(item) : null;
    var scanType = item._scan_type || item.scan_type || scanWorkspaceState.activeType;

    var head = document.createElement('div');
    head.className = 'scan-check-head';
    var title = document.createElement('strong');
    title.textContent = scanType === 'risk'
        ? '风险处理单'
        : (scanType === 'bottom_div' ? '观察确认单' : '交易检查单');
    var note = document.createElement('span');
    note.textContent = stage ? stage.label : (item.score_confidence_label || '等待样本');
    head.appendChild(title);
    head.appendChild(note);
    checklist.appendChild(head);

    var list = document.createElement('div');
    list.className = 'scan-check-list';
    var risk = Number(item.risk_score || 0);
    var confidenceTone = item.score_confidence_level === 'high' || item.score_confidence_level === 'medium'
        ? 'positive'
        : (item.score_confidence_level === 'low' ? 'warning' : 'muted');
    var riskTone = risk >= 4 ? 'danger' : (risk > 0 ? 'warning' : 'positive');
    var signalTone = scanType === 'risk' ? 'warning' : 'positive';
    var signalLabel = scanType === 'risk'
        ? '风险'
        : (scanType === 'bottom_div' ? '观察' : '信号');
    var sampleLabel = scanType === 'bottom_div' ? '确认' : '样本';
    var riskTitle = scanType === 'risk'
        ? (risk >= 4 ? '优先处理' : '等待确认')
        : (risk > 0 ? '需控制' : '风险低');
    var riskDetail = scanType === 'bottom_div'
        ? '确认分 ' + (item.confirm_score == null ? '-' : item.confirm_score) + ' · 风险分 ' + (item.risk_score == null ? '-' : item.risk_score)
        : '个股风险分 ' + (item.risk_score == null ? '-' : item.risk_score);

    var checklistItems = [
        createScanChecklistItem(
            signalLabel,
            typeof scanDisplaySignalText === 'function'
                ? scanDisplaySignalText(item)
                : ((item.signal_label || item.signal || '-') + ' ' + (item.signal_name || '')),
            item.reason || explanation.summary || '-',
            signalTone
        )
    ];
    if (stage) {
        checklistItems.push(createScanChecklistItem(
            '阶段',
            stage.label,
            stage.detail,
            stage.tone
        ));
    }
    var role = typeof scanCandidateRole === 'function' ? scanCandidateRole(item) : null;
    if (role) {
        checklistItems.push(createScanChecklistItem(
            '角色',
            role.label,
            role.detail,
            role.tone
        ));
    }
    var queue = typeof scanCandidateQueue === 'function' ? scanCandidateQueue(item) : null;
    if (queue) {
        checklistItems.push(createScanChecklistItem(
            '队列',
            queue.label,
            queue.detail,
            queue.tone
        ));
    }
    checklistItems = checklistItems.concat([
        createScanChecklistItem(
            '所属行业',
            item.sector || '未识别板块',
            '概念：' + (conceptText || '暂无'),
            'muted'
        ),
        createScanChecklistItem(
            sampleLabel,
            scanType === 'bottom_div' ? ('确认分 ' + (item.confirm_score == null ? '-' : item.confirm_score)) : (item.score_confidence_label || '-'),
            scanType === 'bottom_div'
                ? ('事件后上涨 ' + formatPercent(item.win_rate) + ' · 平均涨跌 ' + formatSignedPercent(item.avg_ret))
                : ((item.score_confidence && item.score_confidence.basis) || ('事件后上涨 ' + formatPercent(item.win_rate) + ' · 平均涨跌 ' + formatSignedPercent(item.avg_ret))),
            confidenceTone
        ),
        createScanChecklistItem(
            '风险',
            riskTitle,
            riskDetail,
            riskTone
        )
    ]);
    checklistItems.forEach(function(node) {
        list.appendChild(node);
    });
    checklist.appendChild(list);
    return checklist;
}

function createScanDetailSection(title, meta, className) {
    var section = document.createElement('section');
    section.className = 'scan-detail-section ' + (className || '');
    var head = document.createElement('div');
    head.className = 'scan-detail-section__head';
    var titleNode = document.createElement('strong');
    titleNode.textContent = title;
    var metaNode = document.createElement('span');
    metaNode.textContent = meta || '';
    head.appendChild(titleNode);
    head.appendChild(metaNode);
    section.appendChild(head);
    return section;
}

function renderScanBasisSection(item, explanation, conceptText) {
    var scanType = item._scan_type || item.scan_type || scanWorkspaceState.activeType;
    var sectionMeta = scanType === 'risk'
        ? '第一层先看风险是否扩散'
        : (scanType === 'bottom_div' ? '第一层先看修复是否成形' : '第一层先看参与依据');
    var section = createScanDetailSection('依据', sectionMeta, 'scan-detail-section--basis');
    var grid = document.createElement('div');
    grid.className = 'scan-detail-basis-grid';
    var stage = typeof inferScanPoolStage === 'function' ? inferScanPoolStage(item) : null;
    var signalTone = scanType === 'risk' ? 'warning' : (scanType === 'bottom_div' ? 'muted' : 'positive');
    var basisItems = [];
    basisItems.push(
        createScanChecklistItem(
            scanType === 'risk' ? '风险' : (scanType === 'bottom_div' ? '观察' : '信号'),
            typeof scanDisplaySignalText === 'function'
                ? scanDisplaySignalText(item)
                : ((item.signal_label || item.signal || '-') + ' ' + (item.signal_name || '')),
            item.reason || (stage ? stage.detail : explanation.summary) || '-',
            signalTone
        )
    );
    basisItems.push(
        createScanChecklistItem(
            '所属行业',
            item.sector || '未识别板块',
            '概念：' + (conceptText || '暂无'),
            'muted'
        )
    );
    var confidenceTone = item.score_confidence_level === 'high' || item.score_confidence_level === 'medium'
        ? 'positive'
        : (item.score_confidence_level === 'low' ? 'warning' : 'muted');
    basisItems.push(
        createScanChecklistItem(
            '样本',
            item.score_confidence_label || '-',
            (item.score_confidence && item.score_confidence.basis) || ('事件后上涨 ' + formatPercent(item.win_rate) + ' · 平均涨跌 ' + formatSignedPercent(item.avg_ret)),
            confidenceTone
        )
    );
    basisItems.slice(0, 3).forEach(function(node) {
        grid.appendChild(node);
    });
    section.appendChild(grid);
    return section;
}

function renderScanProfileRelationSection(item) {
    var groups = Array.isArray(item.profile_relation_groups) ? item.profile_relation_groups : [];
    if (!groups.length) return null;
    var section = createScanDetailSection(
        '画像证据',
        '只读 · ' + (item.profile_relation_group_summary || ('共 ' + (item.profile_relation_count || 0) + ' 条')),
        'scan-detail-section--profile-relations'
    );
    var grid = document.createElement('div');
    grid.className = 'scan-detail-basis-grid';
    groups.forEach(function(group) {
        var relations = Array.isArray(group.relations) ? group.relations : [];
        var names = relations.slice(0, 4).map(function(relation) {
            return relation.relation_name || relation.name || '';
        }).filter(Boolean).join(' / ');
        var sources = relations.map(function(relation) {
            return relation.source || '';
        }).filter(Boolean).filter(function(value, index, array) {
            return array.indexOf(value) === index;
        }).slice(0, 2).join(' / ');
        var tone = group.key === 'core_business' || group.key === 'event_driven'
            ? 'positive'
            : (group.key === 'manual' || group.key === 'weak_association' || group.key === 'expired_watch' ? 'warning' : 'muted');
        grid.appendChild(createScanChecklistItem(
            group.label || group.key || '关系',
            names || '-',
            '证据 ' + (group.count || relations.length || 0) + ' 条' + (sources ? ' · ' + sources : ''),
            tone
        ));
    });
    section.appendChild(grid);
    return section;
}

function renderScanRiskSection(item, explanation) {
    var risk = Number(item.risk_score || 0);
    var section = createScanDetailSection(
        '风险',
        risk >= 4 ? '优先处理' : (risk > 0 ? '需要控制' : '当前较低'),
        'scan-detail-section--risk'
    );
    var list = document.createElement('div');
    list.className = 'scan-detail-risk-list';
    var riskTone = risk >= 4 ? 'danger' : (risk > 0 ? 'warning' : 'positive');
    [
        createScanChecklistItem(
            '风险分',
            item.risk_score == null ? '-' : item.risk_score,
            '仅消费个股结构与风险事实',
            riskTone
        ),
        createScanChecklistItem(
            '注意项',
            explanation.cautions && explanation.cautions.length ? explanation.cautions[0].label : '暂无额外风险',
            explanation.cautions && explanation.cautions.length ? explanation.cautions[0].value : '仍需结合图表确认',
            explanation.cautions && explanation.cautions.length ? explanation.cautions[0].tone : 'positive'
        )
    ].forEach(function(node) {
        list.appendChild(node);
    });
    section.appendChild(list);
    return section;
}

function renderScanActionSection(item) {
    var section = createScanDetailSection('操作', item.event_date || item.date || '-', 'scan-detail-section--actions');
    var actions = document.createElement('div');
    actions.className = 'scan-action-grid';
    var scanType = item._scan_type || item.scan_type || scanWorkspaceState.activeType;

    var chart = document.createElement('button');
    chart.type = 'button';
    chart.className = 'scan-open-chart scan-open-chart--primary';
    chart.textContent = '打开单股图表';
    chart.onclick = function() {
        openScanResultChart(item);
    };
    actions.appendChild(chart);

    var list = document.createElement('button');
    list.type = 'button';
    list.className = 'scan-open-chart scan-open-chart--secondary';
    list.textContent = '回到相关名单';
    list.onclick = function() {
        if (typeof navigateScanWorkspace === 'function') {
            navigateScanWorkspace({
                workspace: 'candidates',
                activeType: scanType || 'opportunity',
                sideView: 'detail',
                filters: {
                    query: '',
                    sector: '',
                    concept: '',
                    sort: 'system'
                },
                clearSelection: false
            });
        }
    };
    actions.appendChild(list);

    var copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'scan-open-chart scan-open-chart--secondary scan-open-chart--quiet';
    copy.textContent = '复制代码';
    copy.onclick = function() {
        if (navigator.clipboard && item.code) {
            navigator.clipboard.writeText(item.code);
        }
    };
    actions.appendChild(copy);

    section.appendChild(actions);
    return section;
}

function createScanSelectionDisclosure(title, meta, contentNode, open) {
    var disclosure = document.createElement('details');
    disclosure.className = 'scan-selected-disclosure';
    disclosure.open = Boolean(open);

    var summary = document.createElement('summary');
    var titleNode = document.createElement('strong');
    titleNode.textContent = title;
    var metaNode = document.createElement('span');
    metaNode.textContent = meta || '';
    summary.appendChild(titleNode);
    summary.appendChild(metaNode);
    disclosure.appendChild(summary);
    disclosure.appendChild(contentNode);
    return disclosure;
}
