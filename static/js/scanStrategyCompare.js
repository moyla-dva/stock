function normalizeScanStrategyView(value) {
    return 'v2';
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

function scanLegacySignalText(item) {
    item = item || {};
    var label = scanFirstText(item, ['signal_label', 'signalLabel', 'signalCode', 'signal', 'label']) || '-';
    var name = scanFirstText(item, ['signal_name', 'signalName']);
    return (label + ' ' + name).trim();
}

function scanV2SignalText(item) {
    item = item || {};
    var signal = scanFirstText(item, ['v2_signal', 'v2Signal']);
    if (!signal) return scanLegacySignalText(item);
    var model = scanV2StateModel(item) || {};
    var candidateLabel = scanFirstText(item, ['candidate_display_label', 'candidateDisplayLabel'])
        || scanFirstText(model, ['candidate_display_label', 'candidateDisplayLabel']);
    var candidateName = scanFirstText(item, ['candidate_substate_label', 'candidateSubstateLabel'])
        || scanFirstText(model, ['candidate_substate_label', 'candidateSubstateLabel']);
    if (signal === 'C候' && candidateLabel) {
        return (candidateLabel + ' ' + (candidateName || scanFirstText(item, ['v2_signal_name', 'v2SignalName']))).trim();
    }
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

function scanV2DecisionFacts(item) {
    var model = scanV2StateModel(item) || {};
    var facts = model.facts || {};
    var permissionModel = model.v2_permission_model || model.v2PermissionModel || {};
    var planGate = permissionModel.plan_gate || permissionModel.planGate || null;
    var targetStructure = facts.target_structure || facts.targetStructure || {};
    var exitGate = facts.exit_gate || facts.exitGate || {};
    var macroTide = facts.macro_tide || facts.macroTide || {};
    return {
        model: model,
        facts: facts,
        permissionModel: permissionModel,
        planGate: planGate,
        targetStructure: targetStructure,
        exitGate: exitGate,
        macroTide: macroTide
    };
}

function scanV2ToneForPermission(permission) {
    if (permission === 'attack_allowed' || permission === 'pullback_allowed' || permission === 'breakout_allowed') return 'positive';
    if (permission === 'forbidden' || permission === 'risk_only') return 'danger';
    if (permission === 'watch_only') return 'warning';
    return 'muted';
}

function scanV2PlanGateTone(status) {
    if (status === 'ready') return 'positive';
    if (status === 'blocked') return 'danger';
    return 'warning';
}

function scanV2MarkerRoleLabel(role) {
    return {
        buy: '买入',
        sell: '卖出',
        scale_out: '减仓',
        observe: '观察'
    }[role] || '';
}

function scanV2PlanGateText(planGate) {
    if (!planGate) return '';
    var label = planGate.status_label || planGate.status || '计划';
    var fragments = [];
    if (planGate.risk_reward_ratio != null) fragments.push(Number(planGate.risk_reward_ratio).toFixed(2) + 'R');
    if (planGate.stop_distance_pct != null) fragments.push('止损' + Number(planGate.stop_distance_pct).toFixed(2) + '%');
    if (planGate.target_label) fragments.push(planGate.target_label);
    return fragments.length ? label + ' · ' + fragments.join(' / ') : label;
}

function scanV2PlanGateIssue(planGate) {
    if (!planGate) return '';
    var issues = planGate.block_reasons || planGate.blockReasons || planGate.required_confirmations || planGate.requiredConfirmations || planGate.warnings || [];
    if (!Array.isArray(issues)) issues = [issues];
    return issues.filter(Boolean).slice(0, 2).join(' / ');
}

function scanV2PreferredTarget(targetStructure, planGate, item) {
    targetStructure = targetStructure || {};
    var model = scanV2StateModel(item) || {};
    var signal = scanFirstText(item, ['v2_signal', 'v2Signal']) || model.signal || '';
    var isPullback = signal === 'C回' || (planGate && planGate.entry_type === 'pullback');
    var pullbackTarget = targetStructure.pullback_target || targetStructure.pullbackTarget || {};
    var breakoutTarget = targetStructure.selected_breakout_target || targetStructure.selectedBreakoutTarget || {};
    return isPullback
        ? (pullbackTarget.price != null ? pullbackTarget : breakoutTarget)
        : (breakoutTarget.price != null ? breakoutTarget : pullbackTarget);
}

function scanV2TargetText(targetStructure, planGate, item) {
    var target = scanV2PreferredTarget(targetStructure, planGate, item);
    if (planGate && planGate.target_price != null) {
        return (planGate.target_label || target.label || '目标') + ' ' + Number(planGate.target_price).toFixed(2);
    }
    if (target.price != null) {
        return (target.label || '目标') + ' ' + Number(target.price).toFixed(2);
    }
    return '';
}

function scanV2TargetDetail(targetStructure, planGate, item) {
    var target = scanV2PreferredTarget(targetStructure, planGate, item);
    var detail = [];
    if (target.source || target.label) detail.push(target.label || target.source);
    if (target.strength_score != null) detail.push('强度 ' + target.strength_score);
    if (target.distance_pct != null) detail.push('距离 ' + target.distance_pct + '%');
    return detail.join(' · ');
}

function scanV2StopText(planGate) {
    if (!planGate || planGate.stop_price == null) return '';
    var text = '止损 ' + Number(planGate.stop_price).toFixed(2);
    if (planGate.stop_distance_pct != null) text += ' / ' + Number(planGate.stop_distance_pct).toFixed(2) + '%';
    return text;
}

function scanV2CandidateTriggerPlan(item) {
    item = item || {};
    var model = scanV2StateModel(item) || {};
    return item.candidate_trigger_plan
        || item.candidateTriggerPlan
        || model.candidate_trigger_plan
        || model.candidateTriggerPlan
        || null;
}

function scanV2PlanPrice(value) {
    if (value == null || Number.isNaN(Number(value))) return '';
    return Number(value).toFixed(2);
}

function scanV2CandidateTriggerText(plan) {
    if (!plan) return '';
    var label = plan.confirmation_label || plan.confirmationLabel || '确认价';
    var price = scanV2PlanPrice(plan.confirmation_price != null ? plan.confirmation_price : plan.confirmationPrice);
    var distance = plan.distance_to_confirmation_pct != null
        ? plan.distance_to_confirmation_pct
        : plan.distanceToConfirmationPct;
    var suffix = distance != null && Number.isFinite(Number(distance))
        ? ' / 差 ' + Number(distance).toFixed(2) + '%'
        : '';
    return price ? label + ' ' + price + suffix : '';
}

function scanV2CandidateInvalidationText(plan) {
    if (!plan) return '';
    var price = scanV2PlanPrice(plan.invalidation_price != null ? plan.invalidation_price : plan.invalidationPrice);
    return price ? '失效 ' + price : '';
}

function scanV2CardEvidenceItems(item) {
    if (!isScanV2StrategyView()) return [];
    var facts = scanV2DecisionFacts(item);
    var model = facts.model || {};
    var planGate = facts.planGate;
    var exitGate = facts.exitGate || {};
    var triggerPlan = scanV2CandidateTriggerPlan(item);
    var permission = scanFirstText(item, ['v2_permission', 'v2Permission']) || model.permission || '';
    var queue = scanFirstText(item, ['v2_queue_label', 'v2QueueLabel']);
    var items = [];
    if (permission) {
        items.push({
            label: '许可',
            value: queue ? permission + ' / ' + queue : permission,
            tone: scanV2ToneForPermission(permission)
        });
    }
    var candidateLabel = scanFirstText(item, ['candidate_substate_label', 'candidateSubstateLabel'])
        || scanFirstText(model, ['candidate_substate_label', 'candidateSubstateLabel']);
    var candidateDisplay = scanFirstText(item, ['candidate_display_label', 'candidateDisplayLabel'])
        || scanFirstText(model, ['candidate_display_label', 'candidateDisplayLabel']);
    if (candidateLabel || candidateDisplay) {
        items.push({
            label: '子态',
            value: [candidateDisplay, candidateLabel].filter(Boolean).join(' / '),
            tone: candidateDisplay === '待触' || candidateDisplay === '触' ? 'warning' : 'muted'
        });
    }
    var confirmPrice = item.candidate_confirmation_price != null
        ? item.candidate_confirmation_price
        : model.candidate_confirmation_price;
    if (
        confirmPrice != null
        && Number.isFinite(Number(confirmPrice))
        && !(triggerPlan && triggerPlan.status === 'pending_trigger')
    ) {
        items.push({
            label: '确认',
            value: typeof formatScanPrice === 'function' ? formatScanPrice(confirmPrice) : Number(confirmPrice).toFixed(2),
            tone: 'context'
        });
    }
    var triggerText = scanV2CandidateTriggerText(triggerPlan);
    if (triggerText && triggerPlan && triggerPlan.status === 'pending_trigger') {
        items.push({
            label: '触发',
            value: triggerText,
            tone: 'warning'
        });
    }
    var invalidationText = scanV2CandidateInvalidationText(triggerPlan);
    if (invalidationText && triggerPlan && triggerPlan.status !== 'entry_ready') {
        items.push({
            label: '失效',
            value: invalidationText,
            tone: 'muted'
        });
    }
    if (planGate) {
        items.push({
            label: '计划',
            value: scanV2PlanGateText(planGate),
            tone: scanV2PlanGateTone(planGate.status)
        });
    }
    var targetText = scanV2TargetText(facts.targetStructure, planGate, item);
    if (targetText) {
        items.push({
            label: '目标',
            value: targetText,
            tone: 'context'
        });
    }
    var markerRole = exitGate.marker_role || exitGate.markerRole || '';
    if (markerRole && markerRole !== 'observe') {
        items.push({
            label: 'Exit',
            value: scanV2MarkerRoleLabel(markerRole) || markerRole,
            tone: markerRole === 'sell' ? 'danger' : 'warning'
        });
    }
    return items;
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
        var triggerPlan = scanV2CandidateTriggerPlan(item);
        var triggerText = scanV2CandidateTriggerText(triggerPlan);
        var triggerSuffix = triggerText
            ? ' · ' + triggerText + '，未突破前不是买点'
            : '';
        return {
            tone: model.tone || 'muted',
            title: (model.role_label || model.permission_label || 'V2定位') + ' · ' + (scanV2StateSignalText(model) || model.state_label || '状态模型'),
            detail: (model.reason || model.detail || (explanation && explanation.summary) || item.reason || '等待更多结构确认')
                + ' · ' + modelPlanText + ' / ' + modelStopText + triggerSuffix,
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
    var markerRole = scanFirstText(item, ['markerRole', 'marker_role']);
    if (markerRole === 'buy') return 'entry';
    if (markerRole === 'sell') return 'exit';
    if (markerRole === 'scale_out') return 'risk';
    if (markerRole === 'observe') return fallbackCategory === 'bottom' || fallbackCategory === 'top' || fallbackCategory === 'candidate'
        ? fallbackCategory
        : 'observe';
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
        var v2Facts = scanV2DecisionFacts(item);
        var planGate = v2Facts.planGate;
        var exitGate = v2Facts.exitGate || {};
        var targetText = scanV2TargetText(v2Facts.targetStructure, planGate, item);
        var markerRole = exitGate.marker_role || exitGate.markerRole || '';
        var triggerPlan = scanV2CandidateTriggerPlan(item);
        var triggerText = scanV2CandidateTriggerText(triggerPlan);
        var invalidationText = scanV2CandidateInvalidationText(triggerPlan);
        var items = [
            {
                label: '信号映射',
                value: (legacyText && legacyText !== '-' && legacyText !== modelSignalText)
                    ? (legacyText + ' -> ' + modelSignalText)
                    : modelSignalText
            },
            {
                label: '许可',
                value: (scanFirstText(item, ['v2_permission', 'v2Permission']) || model.permission || '-')
                    + ' / ' + (scanFirstText(item, ['v2_queue_label', 'v2QueueLabel']) || model.permission_label || '-')
            },
            {
                label: 'Plan',
                value: planGate
                    ? (scanV2PlanGateText(planGate) + (scanV2PlanGateIssue(planGate) ? ' / ' + scanV2PlanGateIssue(planGate) : ''))
                    : modelPlanText + ' / ' + modelStopText
            },
            {
                label: '目标/止损',
                value: [
                    targetText || '目标待确认',
                    scanV2StopText(planGate) || (model.requires_stop_loss || model.requiresStopLoss ? '止损待确认' : '不要求入场止损')
                ].join(' · ')
            },
            {
                label: 'Exit',
                value: markerRole
                    ? ((scanV2MarkerRoleLabel(markerRole) || markerRole) + ' · ' + (exitGate.summary || '按 Exit Gate 管理'))
                    : '未触发减仓/卖出'
            },
            { label: '指标口径', value: 'V2 负责许可与动作语义，旧 C 保留为单股分析证据' }
        ];
        var factsText = scanV2FactsText(model);
        if (factsText) {
            items.splice(2, 0, { label: '事实层', value: factsText });
        }
        if (triggerPlan) {
            items.splice(2, 0, {
                label: '待触计划',
                value: [
                    triggerPlan.summary || triggerPlan.status_label || '',
                    triggerText,
                    invalidationText
                ].filter(Boolean).join(' · ') || '等待右侧确认'
            });
            items.splice(3, 0, {
                label: '盘中/次日',
                value: [
                    triggerPlan.intraday_rule || '',
                    triggerPlan.next_session_rule || ''
                ].filter(Boolean).join(' / ') || '确认规则待补齐'
            });
            if (triggerPlan.failure_rule) {
                items.splice(4, 0, {
                    label: '失效处理',
                    value: triggerPlan.failure_rule
                });
            }
        }
        return items;
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

function scanV2FactsText(model) {
    var facts = model && model.facts ? model.facts : null;
    var supportedSources = ['c_signal_v2_phase_2_3', 'c_signal_v2_p4_facts', 'c_signal_v2_p5_macro_facts', 'c_signal_v2_p7_target_facts', 'c_signal_v2_p8_macro_veto_facts', 'c_signal_v2_p9a_normalized_bars_facts', 'c_signal_v2_p9b_multi_rectangle_facts', 'c_signal_v2_p9c_bear_trap_facts', 'c_signal_v2_p10_resistance_zones_facts', 'c_signal_v2_p11_exit_gate_facts', 'c_signal_v2_p19_repair_watch_facts'];
    if (!facts || supportedSources.indexOf(facts.source) === -1) return '';
    var structure = facts.structure || {};
    var fractals = structure.fractals || {};
    var rectangle = structure.rectangle || {};
    var activeRectangle = structure.active_rectangle || {};
    var macroRectangle = structure.macro_rectangle || {};
    var bearTrap = structure.bear_trap_recovery || {};
    var normalizedBars = structure.normalized_bars || {};
    var trigger = facts.trigger || {};
    var ignition = trigger.ignition || {};
    var macroTide = facts.macro_tide || {};
    var targetStructure = facts.target_structure || {};
    var breakoutTarget = targetStructure.selected_breakout_target || {};
    var exitGate = facts.exit_gate || {};
    var legacyExperience = facts.legacy_experience || facts.legacyExperience || {};
    var scores = facts.v2_scores || {};
    var fragments = [];
    var familyLabels = { short: '短线', swing: '波段', macro: '一年' };
    if (fractals.double_bottom_higher_low) {
        fragments.push('双底抬高');
    } else if (fractals.latest_bottom) {
        fragments.push('底分型');
    }
    if (rectangle.available) {
        var family = activeRectangle.family || rectangle.family || '短线';
        fragments.push((familyLabels[family] || family) + '矩形' + (rectangle.width_pct != null ? rectangle.width_pct + '%' : ''));
    }
    if (macroRectangle.available) {
        fragments.push('一年矩形' + (macroRectangle.width_pct != null ? macroRectangle.width_pct + '%' : ''));
    }
    if (normalizedBars.merge_count) {
        fragments.push('K线合并' + normalizedBars.merge_count + '根');
    }
    if (bearTrap.breakout_after_recovery) {
        fragments.push('破底翻突破');
    } else if (bearTrap.recovered) {
        fragments.push('破底翻观察');
    }
    if (trigger.attack_day) fragments.push('攻击日');
    if (ignition.triggered) fragments.push('起爆' + (ignition.trigger_price != null ? ignition.trigger_price : ''));
    if (breakoutTarget.price != null) {
        var targetText = '目标' + (breakoutTarget.label || '') + breakoutTarget.price;
        if (breakoutTarget.strength_score != null) targetText += '/强度' + breakoutTarget.strength_score;
        fragments.push(targetText);
    }
    if (exitGate.action === 'sell') {
        fragments.push('Exit Gate离场');
    } else if (exitGate.action === 'scale_out') {
        fragments.push('强阻减仓');
    } else if ((exitGate.position_lifecycle || {}).position_state === 'active') {
        fragments.push('持仓防守线');
    }
    if (legacyExperience.available && Array.isArray(legacyExperience.items)) {
        legacyExperience.items.slice(0, 3).forEach(function(item) {
            var label = item && item.label ? item.label : '';
            if (label) fragments.push(label + '素材');
        });
    }
    if (macroTide.permission) fragments.push('大周期' + (macroTide.label || macroTide.permission));
    var scoreText = '研究' + (scores.research_score != null ? scores.research_score : '-')
        + ' / 结构' + (scores.structure_score != null ? scores.structure_score : '-')
        + ' / 触发' + (scores.trigger_quality != null ? scores.trigger_quality : '-')
        + ' / 风险' + (scores.execution_risk != null ? scores.execution_risk : '-');
    return (fragments.length ? fragments.join(' · ') + ' · ' : '') + scoreText;
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
        category: scanV2PointCategory(point, meta.category),
        markerRole: point.markerRole || point.marker_role || meta.markerRole || '',
        markerLevel: point.markerLevel || point.marker_level || meta.markerLevel || 'normal',
        markerReason: point.markerReason || point.marker_reason || meta.markerReason || ''
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
    try {
        window.localStorage.setItem(SCAN_STRATEGY_VIEW_STORAGE_KEY, scanWorkspaceState.strategyView);
    } catch (error) {
        // localStorage can be unavailable under private mode or file protocol
    }
    renderScanStrategyViewToggle();
    refreshActiveScanChartFocusStrategyView();
    var chartData = analysisStore.getCurrentChartData();
    if (chartData && typeof renderChart === 'function') {
        renderChart(chartData);
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
window.scanDisplaySignalText = scanDisplaySignalText;
window.scanV2StateModel = scanV2StateModel;
window.scanV2DecisionFacts = scanV2DecisionFacts;
window.scanV2PlanGateText = scanV2PlanGateText;
window.scanV2PlanGateIssue = scanV2PlanGateIssue;
window.scanV2TargetText = scanV2TargetText;
window.scanV2TargetDetail = scanV2TargetDetail;
window.scanV2StopText = scanV2StopText;
window.scanV2CandidateTriggerPlan = scanV2CandidateTriggerPlan;
window.scanV2CandidateTriggerText = scanV2CandidateTriggerText;
window.scanV2CandidateInvalidationText = scanV2CandidateInvalidationText;
window.scanV2MarkerRoleLabel = scanV2MarkerRoleLabel;
window.scanV2CardEvidenceItems = scanV2CardEvidenceItems;
window.scanV2ToneForPermission = scanV2ToneForPermission;
window.scanV2PlanGateTone = scanV2PlanGateTone;
window.scanStrategyScopeText = scanStrategyScopeText;
window.scanV2CandidateRole = scanV2CandidateRole;
window.scanV2DecisionVerdict = scanV2DecisionVerdict;
window.scanV2PointChartLabel = scanV2PointChartLabel;
window.scanStrategyDeltaItems = scanStrategyDeltaItems;
window.scanV2FactsText = scanV2FactsText;
window.scanPointStrategyMeta = scanPointStrategyMeta;
window.refreshActiveScanChartFocusStrategyView = refreshActiveScanChartFocusStrategyView;
window.renderScanStrategyViewToggle = renderScanStrategyViewToggle;
window.setScanStrategyView = setScanStrategyView;
