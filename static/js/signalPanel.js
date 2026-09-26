function mergeSignalDefinitions(definitions) {
    if (!definitions) return;
    signalMeta = Object.assign({}, signalMeta, definitions);
}

function getPointMeta(point) {
    var key = point.signalKey || point.name;
    var fallback = {
        label: point.signalLabel || point.signalCode || point.name || '?',
        name: point.name || '信号',
        detail: point.signalDetail || point.reason || point.value || '',
        color: point.signalColor || (point.itemStyle && point.itemStyle.color) || '#00897b',
        category: point.signalCategory || 'observe',
        order: point.signalOrder || 999
    };
    var meta = Object.assign({}, fallback, signalMeta[key] || {});
    meta.markerRole = point.markerRole || point.marker_role || meta.markerRole || meta.marker_role || '';
    meta.markerLevel = point.markerLevel || point.marker_level || meta.markerLevel || meta.marker_level || 'normal';
    meta.markerReason = point.markerReason || point.marker_reason || meta.markerReason || meta.marker_reason || '';
    if (typeof scanPointStrategyMeta === 'function') {
        meta = scanPointStrategyMeta(point, meta);
    }
    if (typeof chartPositionDisplayMeta === 'function') {
        meta = chartPositionDisplayMeta(point, meta);
    }
    return meta;
}

function getPointKey(point) {
    return point.signalKey || point.name || 'unknown';
}

function isPointActive(point) {
    var key = getPointKey(point);
    return activeSignalKeys[key] !== false;
}

function markerRoleForPoint(point, meta) {
    point = point || {};
    meta = meta || getPointMeta(point);
    if (typeof chartMarkerDisplayRole === 'function') {
        return chartMarkerDisplayRole(point, meta);
    }
    var role = meta.markerRole || point.markerRole || point.marker_role || '';
    if (role) return role;
    var category = meta.category || point.signalCategory || 'observe';
    if (category === 'entry') return 'buy';
    if (category === 'exit') return 'sell';
    if (category === 'risk') return 'scale_out';
    return 'observe';
}

function shapeClass(category, role) {
    if (role === 'buy') return 'signal-shape--entry';
    if (role === 'sell') return 'signal-shape--exit';
    if (role === 'scale_out') return 'signal-shape--scale-out';
    if (category === 'top') return 'signal-shape--risk';
    if (category === 'bottom') return 'signal-shape--bottom';
    return 'signal-shape--observe';
}

function countPointsByKey(points) {
    return points.reduce(function(acc, point) {
        var key = getPointKey(point);
        acc[key] = (acc[key] || 0) + 1;
        return acc;
    }, {});
}

function formatPrice(value) {
    if (value == null || Number.isNaN(Number(value))) return '-';
    return Number(value).toFixed(2);
}

function resolvePointDate(point) {
    if (!point) return '-';
    return point.date || (point.coord && point.coord[0]) || '-';
}

function findPointByDate(points, date) {
    if (!Array.isArray(points) || !points.length || !date) return null;
    for (var i = points.length - 1; i >= 0; i--) {
        if (resolvePointDate(points[i]) === date) return points[i];
    }
    return null;
}

function signalHealthByCategory(category, role) {
    var positionView = typeof getChartPositionView === 'function' ? getChartPositionView() : 'flat';
    if (positionView !== 'position') {
        if (role === 'sell') return '结构破位';
        if (role === 'scale_out') return '阻力/风险';
    }
    if (role === 'buy') return '入场决策';
    if (role === 'sell') return '离场决策';
    if (role === 'scale_out') return '收益保护';
    if (role === 'observe') return '观察事实';
    if (category === 'entry') return '买入候选';
    if (category === 'risk') return '风险预警';
    if (category === 'exit') return '离场信号';
    if (category === 'top') return '阻力观察';
    if (category === 'bottom') return '底部观察';
    return '观察';
}

function currentInspectorSignalDate() {
    if (typeof getInspectorSignalDate === 'function') {
        return getInspectorSignalDate();
    }
    return activeHoverSignalDate || activeInspectorSignalDate || null;
}

function applySignalBriefState(positionText, signalDate, visibleCount, health, note) {
    setText('latest-signal', positionText || '-');
    setText('latest-signal-date', signalDate || '-');
    setText('visible-signal-count', visibleCount == null ? 0 : visibleCount);
    setText('signal-health', health || '待命');
    setText('latest-signal-note', note || '等待数据载入');
}

function renderSignalFilters(points) {
    var container = document.getElementById('signal-filter-list');
    if (!container) return;
    container.innerHTML = '';
    if (!points.length) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = '当前模式暂无信号';
        container.appendChild(empty);
        return;
    }

    var counts = countPointsByKey(points);
    var keys = Object.keys(counts).sort(function(a, b) {
        var metaA = signalMeta[a] || {};
        var metaB = signalMeta[b] || {};
        return (metaA.order || 999) - (metaB.order || 999);
    });

    keys.forEach(function(key) {
        var sample = points.find(function(point) { return getPointKey(point) === key; }) || {};
        var meta = getPointMeta(sample);
        var role = markerRoleForPoint(sample, meta);
        var active = activeSignalKeys[key] !== false;
        var row = document.createElement('button');
        row.type = 'button';
        row.className = 'filter-row' + (active ? '' : ' is-muted');
        row.setAttribute('aria-pressed', active ? 'true' : 'false');

        var shape = document.createElement('span');
        shape.className = 'signal-shape ' + shapeClass(meta.category, role);
        shape.style.setProperty('--shape-color', meta.color);

        var main = document.createElement('span');
        main.className = 'filter-main';
        var title = document.createElement('strong');
        title.textContent = meta.label + ' ' + meta.name;
        var detail = document.createElement('em');
        detail.textContent = meta.detail || sample.reason || '';
        main.appendChild(title);
        main.appendChild(detail);

        var count = document.createElement('span');
        count.className = 'filter-count';
        count.textContent = counts[key];

        row.appendChild(shape);
        row.appendChild(main);
        row.appendChild(count);
        row.onclick = function() {
            activeSignalKeys[key] = !active;
            var chartData = analysisStore.getCurrentChartData();
            if (chartData) renderChart(chartData);
        };
        container.appendChild(row);
    });
}

function renderEventList(points, allPoints) {
    var list = document.getElementById('event-list');
    if (!list) return;
    list.innerHTML = '';
    setText('event-range-label', points.length + ' / ' + allPoints.length);
    if (!points.length) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = '没有可见事件';
        list.appendChild(empty);
        return;
    }

    points.slice().reverse().slice(0, 80).forEach(function(point) {
        var meta = getPointMeta(point);
        var role = markerRoleForPoint(point, meta);
        var pointDate = resolvePointDate(point);
        var isPreview = Boolean(activeHoverSignalDate && activeHoverSignalDate === pointDate);
        var isActive = !isPreview && Boolean(activeInspectorSignalDate && activeInspectorSignalDate === pointDate);
        var item = document.createElement('button');
        item.type = 'button';
        item.className = 'event-item' + (isPreview ? ' is-preview' : '') + (isActive ? ' is-active' : '');

        var shape = document.createElement('span');
        shape.className = 'signal-shape ' + shapeClass(meta.category, role);
        shape.style.setProperty('--shape-color', meta.color);

        var main = document.createElement('span');
        main.className = 'event-main';
        var title = document.createElement('strong');
        title.textContent = meta.label + ' ' + meta.name;
        var metaLine = document.createElement('span');
        var date = document.createElement('em');
        date.textContent = pointDate;
        var price = document.createElement('em');
        price.textContent = '收 ' + formatPrice(point.price);
        metaLine.appendChild(date);
        metaLine.appendChild(price);
        var reason = document.createElement('em');
        reason.textContent = point.reason || point.value || meta.detail || '';
        main.appendChild(title);
        main.appendChild(metaLine);
        main.appendChild(reason);

        item.appendChild(shape);
        item.appendChild(main);
        item.onclick = function() {
            focusSignal(pointDate);
        };
        list.appendChild(item);
    });
}

function renderSignalBrief(points, allPoints) {
    var inspectorDate = currentInspectorSignalDate();
    var previewing = Boolean(activeHoverSignalDate && inspectorDate === activeHoverSignalDate);
    var activePoint = findPointByDate(points, inspectorDate) || findPointByDate(allPoints, inspectorDate);
    if (activeScanChartFocus) {
        var focus = activeScanChartFocus;
        var focusHealth = '结构观察';
        if (focus.scanType === 'risk') focusHealth = '风险处理';
        else if (focus.scanType === 'bottom_div') focusHealth = '修复观察';
        else focusHealth = '参与确认';
        if (activePoint && resolvePointDate(activePoint) !== (focus.date || '')) {
            var activeMeta = getPointMeta(activePoint);
            var activeRole = markerRoleForPoint(activePoint, activeMeta);
            applySignalBriefState(
                activeMeta.label + ' ' + (activeMeta.name || ''),
                resolvePointDate(activePoint),
                points.length,
                signalHealthByCategory(activeMeta.category, activeRole),
                (previewing ? '悬停预览 · ' : '已定位信号日 · ') + (activePoint.reason || activePoint.value || activeMeta.detail || '查看这一天的结构与处理。')
            );
            return;
        }
        applySignalBriefState(
            focus.signalLabel || focus.roleLabel || focus.queueLabel || '候选联动',
            focus.date || '-',
            points.length,
            focusHealth,
            focus.reason || focus.queueDetail || '当前定位来自扫描候选名单联动。'
        );
        if (!points.length) return;
    }
    if (!points.length) {
        applySignalBriefState(
            '-',
            '-',
            0,
            allPoints.length ? '已筛空' : '无信号',
            allPoints.length ? '当前筛选隐藏了所有事件' : '当前模式暂无可见事件'
        );
        return;
    }
    var latest = activePoint || points[points.length - 1];
    var meta = getPointMeta(latest);
    var role = markerRoleForPoint(latest, meta);
    var health = signalHealthByCategory(meta.category, role);
    applySignalBriefState(
        meta.label + ' ' + (meta.name || ''),
        resolvePointDate(latest),
        points.length,
        health,
        (activePoint ? (previewing ? '悬停预览 · ' : '已定位信号日 · ') : '') + (latest.reason || latest.value || meta.detail || '-')
    );
}

function renderScoreSummary(summary) {
    summary = summary || {};
    setText('score-setup', summary.setup == null ? '-' : summary.setup);
    setText('score-confirm', summary.confirm == null ? '-' : summary.confirm);
    setText('score-risk', summary.risk == null ? '-' : summary.risk);

    var confirmCell = document.getElementById('score-confirm');
    var riskCell = document.getElementById('score-risk');
    if (confirmCell && confirmCell.parentElement) {
        confirmCell.parentElement.classList.toggle('score-cell--confirm', Number(summary.confirm || 0) >= 4);
    }
    if (riskCell && riskCell.parentElement) {
        riskCell.parentElement.classList.toggle('score-cell--risk', Number(summary.risk || 0) >= 3);
    }
}

function tagProfileNames(group, limit) {
    var tags = group && Array.isArray(group.tags) ? group.tags : [];
    return tags.slice(0, limit || 4).map(function(tag) {
        return tag.name;
    }).filter(Boolean);
}

function appendTagProfileGroup(container, label, names, tone) {
    if (!names || !names.length) return;
    var group = document.createElement('div');
    group.className = 'tag-profile-group tag-profile-group--' + (tone || 'default');
    var title = document.createElement('span');
    title.textContent = label;
    group.appendChild(title);
    var list = document.createElement('div');
    list.className = 'tag-profile-chip-list';
    names.forEach(function(name) {
        var chip = document.createElement('em');
        chip.textContent = name;
        list.appendChild(chip);
    });
    group.appendChild(list);
    container.appendChild(group);
}

function renderStockTagProfile(profile) {
    var summary = document.getElementById('tag-profile-summary');
    var groups = document.getElementById('tag-profile-groups');
    var flags = document.getElementById('tag-profile-flags');
    if (!summary || !groups || !flags) return;
    groups.innerHTML = '';
    flags.innerHTML = '';

    if (!profile) {
        summary.textContent = '等待画像载入';
        return;
    }

    var governance = profile.governance || {};
    summary.textContent = (governance.quality_label || '待核对') + ' · 标签分层已拆开';

    var profileGroups = profile.groups || {};
    appendTagProfileGroup(groups, '静态行业', tagProfileNames(profileGroups.official_industry, 1), 'fact');
    appendTagProfileGroup(groups, '事件', tagProfileNames(profileGroups.event_driven, 3), 'event');
    appendTagProfileGroup(groups, '市场标签', tagProfileNames(profileGroups.market_tag, 5), 'market');
    appendTagProfileGroup(groups, '弱关联', tagProfileNames(profileGroups.weak_association, 4).concat(tagProfileNames(profileGroups.expired_watch, 2)), 'weak');

    (governance.flags || []).slice(0, 3).forEach(function(flag) {
        var item = document.createElement('div');
        item.className = 'tag-profile-flag tag-profile-flag--' + (flag.severity || 'muted');
        var title = document.createElement('strong');
        title.textContent = flag.label || '待核对';
        var detail = document.createElement('span');
        detail.textContent = flag.detail || '';
        item.appendChild(title);
        item.appendChild(detail);
        flags.appendChild(item);
    });
}

function timeframeCardDetailText(item) {
    item = item || {};
    if (item.event && typeof scanDisplaySignalText === 'function') {
        var signalText = scanDisplaySignalText(item.event);
        if (signalText && signalText !== '-') {
            return signalText + (item.event.reason ? ' · ' + item.event.reason : '');
        }
    }
    return item.detail || '等待更多确认。';
}

function renderMultiTimeframeBoard(timeframes) {
    var note = document.getElementById('timeframe-note');
    var grid = document.getElementById('timeframe-grid');
    if (!note || !grid) return;

    grid.innerHTML = '';
    timeframes = timeframes || {};
    var ordered = [timeframes.daily, timeframes.hour_1, timeframes.hour_4].filter(Boolean);
    if (!ordered.length) {
        note.textContent = '当前没有可用的辅助确认结果。';
        return;
    }

    var hour1Available = !!(timeframes.hour_1 && timeframes.hour_1.available !== false);
    note.textContent = hour1Available
        ? '日线负责方向，60m 确认回踩、放量与转强；4h 由 60m 合成做结构确认。'
        : '日线结论可用，60m 当前未就绪，先按日线结构确认，再结合事件流处理。';

    ordered.forEach(function(item) {
        var periodKey = item.period === '60m' ? '60m' : (item.period === '4h' ? '4h' : 'daily');
        var rootData = analysisStore.getCurrentChartData();
        var currentPeriod = analysisStore.getActivePeriod();
        var chartReady = periodKey === 'daily' || !!item.chart;
        var chartLoadable = !chartReady
            && typeof chartPeriodLoadable === 'function'
            && chartPeriodLoadable(rootData, periodKey);
        var chartLoading = typeof chartPeriodLoading === 'function' && chartPeriodLoading(periodKey);
        var card = document.createElement('div');
        card.className = 'timeframe-card timeframe-card--' + (item.tone || 'watch');
        card.classList.toggle('active', currentPeriod === periodKey);
        card.classList.toggle('is-deferred', chartLoadable);
        card.classList.toggle('is-loading', chartLoading);
        if ((chartReady || chartLoadable) && typeof setChartPeriod === 'function') {
            card.classList.add('timeframe-card--clickable');
            card.setAttribute('role', 'button');
            card.tabIndex = 0;
            card.onclick = function() { setChartPeriod(periodKey); };
            card.onkeydown = function(event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    setChartPeriod(periodKey);
                }
            };
        }

        var head = document.createElement('div');
        head.className = 'timeframe-card-head';
        var titleWrap = document.createElement('div');
        var label = document.createElement('span');
        label.textContent = item.label || item.period || '-';
        var role = document.createElement('strong');
        role.textContent = item.role || '';
        titleWrap.appendChild(label);
        titleWrap.appendChild(role);
        head.appendChild(titleWrap);

        var status = document.createElement('em');
        status.textContent = chartLoading
            ? '加载中'
            : (item.available === false ? (chartLoadable ? '可加载' : '未就绪') : (item.latest_at || item.title || ''));
        head.appendChild(status);
        card.appendChild(head);

        var verdict = document.createElement('strong');
        verdict.className = 'timeframe-card-title';
        verdict.textContent = item.title || ((item.label || item.period || '-') + ' 暂无判断');
        card.appendChild(verdict);

        var detail = document.createElement('p');
        detail.className = 'timeframe-card-detail';
        detail.textContent = timeframeCardDetailText(item);
        card.appendChild(detail);

        if (item.scores) {
            var stats = document.createElement('div');
            stats.className = 'timeframe-card-stats';
            [
                ['建仓', item.scores.setup],
                ['确认', item.scores.confirm],
                ['风险', item.scores.risk]
            ].forEach(function(entry) {
                var pill = document.createElement('span');
                pill.textContent = entry[0] + ' ' + (entry[1] == null ? '-' : entry[1]);
                stats.appendChild(pill);
            });
            card.appendChild(stats);
        }

        grid.appendChild(card);
    });
}

function createAnalysisDecisionAction(text, onClick, tone) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'analysis-decision-action analysis-decision-action--' + (tone || 'secondary');
    button.textContent = text;
    button.onclick = onClick;
    return button;
}

function createAnalysisDecisionPathStep(step, label, detail, tone, active) {
    var node = document.createElement('div');
    node.className = 'analysis-decision-path-step analysis-decision-path-step--' + (tone || 'muted') + (active ? ' is-active' : '');
    var stepNode = document.createElement('span');
    stepNode.textContent = step;
    var labelNode = document.createElement('strong');
    labelNode.textContent = label || '-';
    var detailNode = document.createElement('small');
    detailNode.textContent = detail || '';
    node.appendChild(stepNode);
    node.appendChild(labelNode);
    node.appendChild(detailNode);
    return node;
}

function renderAnalysisDecisionTags(tags) {
    var container = document.getElementById('analysis-decision-tags');
    if (!container) return;
    container.innerHTML = '';
    (tags || []).filter(Boolean).slice(0, 4).forEach(function(text) {
        var tag = document.createElement('span');
        tag.className = 'analysis-decision-tag';
        tag.textContent = text;
        container.appendChild(tag);
    });
}

function renderAnalysisStrategyDelta(source) {
    var panel = document.getElementById('analysis-v2-delta-panel');
    var list = document.getElementById('analysis-v2-delta-list');
    if (!panel || !list) return;

    list.innerHTML = '';
    if (!source) {
        var empty = document.createElement('div');
        empty.className = 'analysis-v2-delta-empty';
        empty.textContent = typeof scanStrategyScopeText === 'function'
            ? scanStrategyScopeText()
            : '等待信号后展示策略视角差异';
        list.appendChild(empty);
        return;
    }

    var items = typeof scanStrategyDeltaItems === 'function'
        ? scanStrategyDeltaItems(source)
        : [
            { label: '显示口径', value: '当前信号显示' },
            { label: '指标口径', value: '沿用当前策略指标与评分' }
        ];

    items.forEach(function(item) {
        var row = document.createElement('div');
        row.className = 'analysis-v2-delta-item';
        var label = document.createElement('span');
        label.textContent = item.label || '-';
        var value = document.createElement('strong');
        value.textContent = item.value || '-';
        row.appendChild(label);
        row.appendChild(value);
        list.appendChild(row);
    });
}

function tradePlanTone(plan) {
    if (!plan) return 'watch';
    if (plan.status === 'risk_control' || plan.status === 'blocked') return 'risk';
    if (plan.status === 'ready') return 'entry';
    if (plan.status === 'waiting') return 'watch';
    return 'muted';
}

function tradePlanStepTone(plan, step) {
    if (!plan) return 'muted';
    if (plan.status === 'risk_control' || plan.status === 'blocked') return step === 'permission' ? 'risk' : 'warning';
    if (plan.status === 'ready') return step === 'permission' || step === 'entry' ? 'positive' : 'muted';
    if (plan.status === 'waiting') return step === 'entry' ? 'warning' : 'muted';
    return 'muted';
}

function tradePlanStopText(stop) {
    stop = stop || {};
    if (stop.price == null) return '止损位待确认';
    var text = '止损 ' + formatPrice(stop.price);
    if (stop.distance_pct != null) text += ' · ' + Number(stop.distance_pct).toFixed(2) + '%';
    if (stop.too_wide) text += ' · 距离过宽';
    return text;
}

function tradePlanPositionText(plan) {
    var position = (plan && plan.position) || {};
    if (position.suggested_shares != null) {
        var text = '建议 ' + Number(position.suggested_shares).toFixed(0) + ' 股';
        if (position.estimated_risk_amount != null) {
            text += ' · 估算风险 ' + Number(position.estimated_risk_amount).toFixed(2);
        }
        return text;
    }
    if (position.risk_per_share != null) {
        return '每股风险 ' + Number(position.risk_per_share).toFixed(3) + '，再按资金预算反推股数';
    }
    return position.formula || '先确定单笔风险金额，再反推仓位';
}

function tradePlanRiskRewardText(plan) {
    var rr = (plan && plan.risk_reward) || {};
    if (rr.ratio != null) {
        return '收益风险比 ' + Number(rr.ratio).toFixed(2) + ':1 · ' + (rr.label || '');
    }
    if (rr.r2_price != null && rr.r3_price != null) {
        return '2R ' + formatPrice(rr.r2_price) + ' · 3R ' + formatPrice(rr.r3_price);
    }
    return '确认至少 2R 的目标空间';
}

function appendTradePlanTags(tags, plan) {
    if (!plan) return;
    if (plan.status_label) tags.push(plan.status_label);
    if (plan.plan_type_label) tags.push(plan.plan_type_label);
    var permission = plan.permission || {};
    if (permission.mode_label) tags.push('权限 ' + permission.mode_label);
    var clock = (((plan.technical_structures || {}).williams_clock) || {});
    if (clock.state_label && clock.state !== 'neutral') tags.push(clock.state_label);
}

function renderAnalysisDecision(visiblePoints, allPoints) {
    var panel = document.getElementById('analysis-decision-panel');
    var verdict = document.getElementById('analysis-decision-verdict');
    var title = document.getElementById('analysis-decision-title');
    var detail = document.getElementById('analysis-decision-detail');
    var path = document.getElementById('analysis-decision-path');
    var actions = document.getElementById('analysis-decision-actions');
    if (!panel || !verdict || !title || !detail || !path || !actions) return;

    visiblePoints = Array.isArray(visiblePoints) ? visiblePoints : [];
    allPoints = Array.isArray(allPoints) ? allPoints : [];
    var inspectorDate = currentInspectorSignalDate();
    var previewing = Boolean(activeHoverSignalDate && inspectorDate === activeHoverSignalDate);
    var selectedPoint = findPointByDate(visiblePoints, inspectorDate) || findPointByDate(allPoints, inspectorDate);
    var latest = selectedPoint || (visiblePoints.length ? visiblePoints[visiblePoints.length - 1] : null);
    var latestMeta = latest ? getPointMeta(latest) : null;
    var focus = activeScanChartFocus || null;
    var currentData = analysisStore.getViewData();
    var tradePlan = currentData && currentData.trade_plan ? currentData.trade_plan : null;
    var tone = 'watch';
    var tags = [];

    path.innerHTML = '';
    actions.innerHTML = '';

    if (focus) {
        if (focus.queueLabel) tags.push(focus.queueLabel);
        if (focus.sector) tags.push('板块 ' + focus.sector);
        if (focus.signalLabel) tags.push(focus.signalLabel);
        if (focus.date) tags.push('事件 ' + focus.date);

        if (focus.scanType === 'risk') {
            tone = 'risk';
            title.textContent = focus.roleLabel || '先确认风险是否扩散';
            detail.textContent = (focus.queueDetail || focus.reason || '当前这只票更适合用来判断风险，而不是直接参与。')
                + ' · ' + (focus.roleAction || '先看支撑、止盈和止损，再决定是否回避。');
        } else if (focus.scanType === 'bottom_div') {
            tone = 'repair';
            title.textContent = focus.roleLabel || '先观察低位修复';
            detail.textContent = (focus.queueDetail || focus.reason || '当前更适合作为修复观察对象。')
                + ' · ' + (focus.roleAction || '等放量、趋势或回踩确认后再考虑参与。');
        } else {
            tone = 'entry';
            title.textContent = focus.roleLabel || '候选可跟踪';
            detail.textContent = (focus.queueDetail || focus.reason || '这只票来自当前扫描候选。')
                + ' · ' + (focus.roleAction || '先看回踩、放量和止损位，不追连续加速。');
        }
        path.appendChild(createAnalysisDecisionPathStep('01', '候选联动', focus.queueDetail || '来自扫描名单联动', 'positive', false));
        path.appendChild(createAnalysisDecisionPathStep('02', focus.queueLabel || '执行名单', focus.roleLabel || focus.signalLabel || '系统已给出当前角色', focus.scanType === 'risk' ? 'risk' : (focus.scanType === 'bottom_div' ? 'warning' : 'positive'), false));
        path.appendChild(createAnalysisDecisionPathStep('03', focus.name || focus.code || '当前股票', focus.roleAction || '现在进入图表与止损确认', 'muted', true));

        actions.appendChild(createAnalysisDecisionAction('回到相关名单', function() {
            if (typeof navigateScanWorkspace === 'function') {
                navigateScanWorkspace({
                    workspace: 'candidates',
                    activeType: focus.scanType || 'opportunity',
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
        }, 'primary'));
        if (focus.date) {
            actions.appendChild(createAnalysisDecisionAction('定位信号日', function() {
                focusSignal(focus.date);
            }, 'secondary'));
        }
    } else if (tradePlan) {
        var permission = tradePlan.permission || {};
        var entry = tradePlan.entry || {};
        var stop = tradePlan.stop || {};
        tone = tradePlanTone(tradePlan);
        appendTradePlanTags(tags, tradePlan);

        title.textContent = tradePlan.title || '等待交易计划';
        detail.textContent = tradePlan.detail || '系统正在把单股信号转成触发、止损和仓位约束。';

        path.appendChild(createAnalysisDecisionPathStep(
            '01',
            '交易权限',
            (permission.mode_label || '-') + ' · ' + (permission.action || permission.risk_action || '等待权限确认'),
            tradePlanStepTone(tradePlan, 'permission'),
            false
        ));
        path.appendChild(createAnalysisDecisionPathStep(
            '02',
            entry.label || '入场触发',
            entry.detail || '等待明确触发后再进入仓位校验',
            tradePlanStepTone(tradePlan, 'entry'),
            tradePlan.status === 'waiting'
        ));
        path.appendChild(createAnalysisDecisionPathStep(
            '03',
            tradePlanStopText(stop),
            tradePlanPositionText(tradePlan) + ' · ' + tradePlanRiskRewardText(tradePlan),
            tradePlanStepTone(tradePlan, 'risk'),
            tradePlan.status === 'ready' || tradePlan.status === 'blocked'
        ));

        if (entry.signal_date) {
            actions.appendChild(createAnalysisDecisionAction('定位计划信号日', function() {
                focusSignal(entry.signal_date);
            }, 'secondary'));
        }
    } else if (latestMeta) {
        tags.push((latestMeta.label || '信号') + ' ' + (latestMeta.name || ''));
        if (latest && (latest.date || (latest.coord && latest.coord[0]))) {
            tags.push('事件 ' + (latest.date || (latest.coord && latest.coord[0])));
        }
        if (selectedPoint) {
            tags.push(previewing ? '预览中' : '已定位');
        }
        if (latestMeta.category === 'entry') {
            tone = 'entry';
            title.textContent = selectedPoint
                ? (previewing ? '预览参与信号，先看确认与风险' : '已定位参与信号，先看确认与风险')
                : '当前有参与信号，先看确认与风险';
            detail.textContent = (selectedPoint ? (previewing ? '悬停预览 · ' : '已定位信号日 · ') : '') + (latestMeta.label || '') + ' ' + (latestMeta.name || '')
                + ' · ' + (latest.reason || latest.value || latestMeta.detail || '打开图表确认结构与止损位。');
        } else if (latestMeta.category === 'risk' || latestMeta.category === 'exit') {
            tone = 'risk';
            title.textContent = selectedPoint
                ? (previewing ? '预览风险信号，先处理风险' : '已定位风险信号，先处理风险')
                : '当前以风险处理为主';
            detail.textContent = (selectedPoint ? (previewing ? '悬停预览 · ' : '已定位信号日 · ') : '') + (latestMeta.label || '') + ' ' + (latestMeta.name || '')
                + ' · ' + (latest.reason || latest.value || latestMeta.detail || '先确认风险是否继续扩散。');
        } else {
            tone = 'watch';
            title.textContent = selectedPoint
                ? (previewing ? '预览观察信号，先看结构变化' : '已定位观察信号，先看结构变化')
                : '当前先观察结构';
            detail.textContent = (selectedPoint ? (previewing ? '悬停预览 · ' : '已定位信号日 · ') : '') + (latestMeta.label || '') + ' ' + (latestMeta.name || '')
                + ' · ' + (latest.reason || latest.value || latestMeta.detail || '等待更强确认，不急于参与。');
        }
        path.appendChild(createAnalysisDecisionPathStep('01', '单股直达', '当前不是从扫描名单联动进入', 'muted', false));
        path.appendChild(createAnalysisDecisionPathStep('02', selectedPoint ? (previewing ? '悬停预览' : '已定位信号') : '当前可见信号', (latestMeta.label || '') + ' ' + (latestMeta.name || ''), latestMeta.category === 'entry' ? 'positive' : ((latestMeta.category === 'risk' || latestMeta.category === 'exit') ? 'risk' : 'warning'), false));
        path.appendChild(createAnalysisDecisionPathStep('03', latest.date || (latest.coord && latest.coord[0]) || '当前股票', previewing ? '先预览这一天，再决定是否锁定' : '继续看结构、事件和风险位', 'muted', true));
        if (latest && (latest.date || (latest.coord && latest.coord[0]))) {
            actions.appendChild(createAnalysisDecisionAction('定位当前信号日', function() {
                focusSignal(latest.date || (latest.coord && latest.coord[0]));
            }, 'secondary'));
        }
    } else {
        tone = allPoints.length ? 'watch' : 'muted';
        title.textContent = allPoints.length ? '当前信号被筛空，先回到图例确认范围' : '等待结构确认';
        detail.textContent = allPoints.length
            ? '当前模式下没有可见事件，先检查图例筛选，再确认这只票是否还有参与依据。'
            : '如果这只票来自扫描候选，系统会在这里解释为什么打开它。';
        path.appendChild(createAnalysisDecisionPathStep('01', '等待信号', '先让图表与事件流可见', 'muted', true));
        path.lastChild.classList.add('is-active');
        path.appendChild(createAnalysisDecisionPathStep('02', '确认结构', '看趋势、确认和风险分是否有方向', 'muted', false));
        path.appendChild(createAnalysisDecisionPathStep('03', '再决定参与', '现在还不适合直接下动作结论', 'muted', false));
    }

    actions.appendChild(createAnalysisDecisionAction('查看事件流', function() {
        if (typeof setInspectorView === 'function') setInspectorView('events');
    }, 'secondary'));

    verdict.className = 'analysis-decision-verdict analysis-decision-verdict--' + tone;
    panel.className = 'analysis-decision-panel analysis-decision-panel--' + tone;
    renderAnalysisDecisionTags(tags);
    var stateModel = currentData && currentData.c_signal_v2_state ? currentData.c_signal_v2_state : null;
    var deltaSource = focus || latest || null;
    if (stateModel) {
        deltaSource = Object.assign({}, deltaSource || {}, { c_signal_v2_state: stateModel });
    }
    renderAnalysisStrategyDelta(deltaSource);
}

function renderSignalBoard(allPoints, visiblePoints) {
    renderSignalFilters(allPoints);
    renderEventList(visiblePoints, allPoints);
    renderSignalBrief(visiblePoints, allPoints);
    renderAnalysisDecision(visiblePoints, allPoints);
}
