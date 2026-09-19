function getModeMarkPoints(data) {
    data = data || {};
    return Array.isArray(data.mark_points_v2) ? data.mark_points_v2 : [];
}

function getChartPositionView() {
    if (typeof analysisStore !== 'undefined' && analysisStore && typeof analysisStore.getChartPositionView === 'function') {
        return analysisStore.getChartPositionView();
    }
    return 'flat';
}

function chartPointText(point, keys) {
    point = point || {};
    for (var i = 0; i < keys.length; i++) {
        var value = point[keys[i]];
        if (value != null && String(value).trim()) {
            return String(value).trim();
        }
    }
    return '';
}

function chartPointSignal(point, meta) {
    return chartPointText(point, ['v2_signal', 'v2Signal'])
        || (meta && meta.label)
        || chartPointText(point, ['signalLabel', 'signalCode', 'name']);
}

function chartPointState(point) {
    return chartPointText(point, ['v2_state', 'v2State']);
}

function chartPointReason(point, meta) {
    return [
        chartPointText(point, ['markerReason', 'marker_reason']),
        chartPointText(point, ['reason', 'value']),
        meta && (meta.markerReason || meta.detail)
    ].filter(Boolean).join(' ');
}

function chartPointCandidateLabel(point) {
    return chartPointText(point, ['candidate_display_label', 'candidateDisplayLabel']);
}

function chartPointIsBottomCandidate(point, meta) {
    var category = (meta && meta.category) || point.signalCategory || '';
    var signal = chartPointSignal(point, meta);
    var reason = chartPointReason(point, meta);
    return Boolean(point && (point.same_day_bottom_candidate || point.sameDayBottomCandidate))
        || category === 'bottom'
        || signal === 'C候'
        || chartPointCandidateLabel(point) === '候?'
        || reason.indexOf('底分型') >= 0
        || reason.indexOf('双底') >= 0
        || reason.indexOf('修复') >= 0;
}

function annotateChartDisplayContext(points, contextPoints) {
    if (!Array.isArray(points) || !points.length) return [];
    var sourcePoints = Array.isArray(contextPoints) && contextPoints.length ? contextPoints : points;
    var byDate = {};
    sourcePoints.forEach(function(point) {
        var date = pointDate(point);
        if (!date) return;
        if (!byDate[date]) {
            byDate[date] = {
                hasBottomCandidate: false,
                hasEntry: false
            };
        }
        var meta = getPointMeta(point);
        var role = chartMarkerRole(point, meta);
        byDate[date].hasBottomCandidate = byDate[date].hasBottomCandidate || chartPointIsBottomCandidate(point, meta);
        byDate[date].hasEntry = byDate[date].hasEntry || role === 'buy';
    });
    return points.map(function(point) {
        var date = pointDate(point);
        var dateContext = byDate[date] || {};
        return Object.assign({}, point, {
            _sameDateHasBottomCandidate: Boolean(dateContext.hasBottomCandidate),
            _sameDateHasEntry: Boolean(dateContext.hasEntry)
        });
    });
}

function chartMarkerRole(point, meta) {
    point = point || {};
    meta = meta || {};
    var role = point.markerRole || point.marker_role || meta.markerRole || meta.marker_role || '';
    if (role) return role;
    var category = meta.category || point.signalCategory || 'observe';
    if (category === 'entry') return 'buy';
    if (category === 'exit') return 'sell';
    if (category === 'risk') return 'scale_out';
    return 'observe';
}

function chartMarkerDisplayRole(point, meta) {
    var role = chartMarkerRole(point, meta);
    if (getChartPositionView() === 'position') {
        if (role === 'observe' && ((meta && meta.category) || point.signalCategory) === 'top') return 'scale_out';
        return role;
    }
    if (role === 'sell') return 'scale_out';
    return role;
}

function chartMarkerLevel(point, meta) {
    point = point || {};
    meta = meta || {};
    return point.markerLevel || point.marker_level || meta.markerLevel || meta.marker_level || 'normal';
}

function chartMarkerRoleLabel(role, point, meta) {
    var positionView = getChartPositionView();
    if (positionView !== 'position') {
        if (role === 'sell') return '结构破位';
        if (role === 'scale_out') return '阻力/风险';
    }
    return {
        buy: '入场决策',
        sell: '离场决策',
        scale_out: '减仓建议',
        observe: '观察事实'
    }[role] || '观察事实';
}

function chartFlatDisplayMeta(point, meta, role, signal) {
    var candidateLabel = chartPointCandidateLabel(point);
    var state = chartPointState(point);
    var reason = chartPointReason(point, meta);
    var sameDateBottom = Boolean(point && (
        point._sameDateHasBottomCandidate
        || point.same_day_bottom_candidate
        || point.sameDayBottomCandidate
    ));

    if (signal === 'C候') {
        return {
            label: candidateLabel || '候',
            name: chartPointText(point, ['candidate_substate_label', 'candidateSubstateLabel'])
                || meta.name
                || '结构候选',
            detail: meta.detail || ''
        };
    }
    if (signal === 'C修') {
        return { label: '候?', name: '修复观察', detail: '破位后出现修复事实，等待右侧确认' };
    }
    if (signal === 'C研') {
        if ((meta.category || point.signalCategory) === 'top') {
            return { label: '阻', name: '顶部观察', detail: '局部阻力或动能停顿，空仓视角不追高' };
        }
        return { label: '看', name: meta.name || '研究观察', detail: meta.detail || '' };
    }
    if (signal === 'C盈' || role === 'scale_out') {
        if (sameDateBottom && (reason.indexOf('破位') >= 0 || signal === 'C风')) {
            return { label: '候?', name: '破位修复观察', detail: '破位区同时出现底部结构，先观察修复质量' };
        }
        return { label: '阻', name: '强阻观察', detail: '触及阻力或过热区，空仓视角只提示不追高' };
    }
    if (signal === 'C风' || role === 'sell') {
        if (sameDateBottom) {
            return { label: '候?', name: '破位修复观察', detail: '破位区同时出现底部结构，先观察修复质量' };
        }
        if (role === 'sell' || state.indexOf('exit') >= 0 || reason.indexOf('trailing_stop') >= 0 || reason.indexOf('破位') >= 0) {
            return { label: '破', name: '结构破位', detail: '结构或防守线失效，空仓视角只提示风险' };
        }
        return { label: '警', name: '风险预警', detail: '风险升高，空仓视角避免追价' };
    }
    if (role === 'buy') {
        return { label: '触', name: meta.name || '触发确认', detail: meta.detail || '' };
    }
    return {
        label: meta.chartLabel || meta.label || signal || '看',
        name: meta.name || '',
        detail: meta.detail || ''
    };
}

function chartPositionDisplayMeta(point, meta) {
    point = point || {};
    meta = meta || {};
    var role = chartMarkerRole(point, meta);
    var signal = chartPointSignal(point, meta);
    var originalLabel = meta.label || signal || '';
    var originalName = meta.name || '';
    var display = getChartPositionView() === 'position'
        ? null
        : chartFlatDisplayMeta(point, meta, role, signal);

    if (getChartPositionView() === 'position') {
        if (role === 'sell') display = { label: '卖', name: '防守离场', detail: meta.detail || '' };
        else if (role === 'scale_out') display = { label: '减', name: '强阻/过热', detail: meta.detail || '' };
        else if ((meta.category || point.signalCategory) === 'top') display = { label: '撤', name: '顶部观察', detail: meta.detail || '' };
        else if (role === 'buy') display = { label: '持', name: meta.name || '趋势确认', detail: meta.detail || '' };
        else display = {
            label: meta.chartLabel || meta.label || signal || '看',
            name: meta.name || '',
            detail: meta.detail || ''
        };
    }

    var next = Object.assign({}, meta, {
        label: display.label,
        name: display.name,
        chartLabel: display.label,
        detail: display.detail || meta.detail || '',
        originalLabel: originalLabel,
        originalName: originalName
    });
    if (originalLabel && originalLabel !== display.label) {
        next.displaySource = originalLabel + (originalName ? ' ' + originalName : '');
    }
    return next;
}

function chartSymbolFor(role, category) {
    if (role === 'buy') return 'triangle';
    if (role === 'sell') return 'triangle';
    if (role === 'scale_out') return 'diamond';
    if (category === 'candidate') return 'pin';
    return 'circle';
}

function chartSymbolSizeFor(role, category, level) {
    if (role === 'buy') return level === 'strong' ? 34 : 30;
    if (role === 'sell') return level === 'strong' ? 34 : 30;
    if (role === 'scale_out') return 26;
    if (category === 'candidate') return 20;
    if (category === 'bottom') return 17;
    if (category === 'top') return 15;
    return 14;
}

function compactChartSymbolSizeFor(role, category, level) {
    if (role === 'buy') return level === 'strong' ? 21 : 18;
    if (role === 'sell') return level === 'strong' ? 21 : 18;
    if (role === 'scale_out') return 17;
    if (category === 'candidate') return 13;
    if (category === 'bottom' || category === 'top') return 11;
    return 9;
}

function chartSymbolOffsetFor(role, category) {
    if (role === 'buy') return [0, 17];
    if (role === 'sell') return [0, -17];
    if (role === 'scale_out') return [0, -15];
    if (category === 'top') return [0, -11];
    if (category === 'candidate' || category === 'bottom') return [0, 12];
    return [0, 8];
}

function styleChartPoint(point, view) {
    var meta = getPointMeta(point);
    var category = meta.category || point.signalCategory || 'observe';
    var role = chartMarkerDisplayRole(point, meta);
    var level = chartMarkerLevel(point, meta);
    var chartLabel = meta.chartLabel || meta.label || '';
    var compact = view === 'full';
    var styled = Object.assign({}, point);
    styled.symbol = chartSymbolFor(role, category);
    styled.symbolSize = compact ? compactChartSymbolSizeFor(role, category, level) : chartSymbolSizeFor(role, category, level);
    styled.symbolOffset = chartSymbolOffsetFor(role, category);
    styled.symbolRotate = role === 'sell' ? 180 : 0;
    styled.itemStyle = Object.assign({}, point.itemStyle || {}, {
        color: meta.color,
        borderColor: role === 'observe' ? meta.color : '#ffffff',
        borderWidth: role === 'observe' ? 1.6 : 0,
        opacity: role === 'observe' ? (compact ? 0.38 : 0.68) : 0.94
    });
    styled.label = Object.assign({}, point.label || {}, {
        show: !compact && role !== 'observe',
        formatter: chartLabel,
        position: 'inside',
        color: '#fff',
        fontSize: chartLabel.length > 2 ? 10 : 11,
        fontWeight: 'bold'
    });
    if (role === 'observe') {
        styled.label = { show: false };
    }
    return styled;
}

function dateIndexMap(dates) {
    return dates.reduce(function(acc, date, index) {
        acc[date] = index;
        return acc;
    }, {});
}

function pointDate(point) {
    return point.date || (point.coord && point.coord[0]) || '';
}

function pointDateIndex(point, indexes) {
    var date = pointDate(point);
    return indexes[date] == null ? -1 : indexes[date];
}

function pointDisplayPriority(point, indexes, totalDays) {
    var meta = getPointMeta(point);
    var category = point.signalCategory || meta.category || 'observe';
    var role = chartMarkerRole(point, meta);
    var idx = pointDateIndex(point, indexes);
    var roleWeight = {
        sell: 92,
        buy: 82,
        scale_out: 76,
        observe: 35
    }[role];
    var categoryWeight = roleWeight || {
        exit: 88,
        risk: 82,
        top: 78,
        entry: 70,
        candidate: 62,
        bottom: 54,
        observe: 35
    }[category] || 40;
    var orderBonus = Math.max(0, 220 - Number(meta.order || 220)) * 0.08;
    var recencyBonus = idx < 0 ? 0 : (idx / Math.max(1, totalDays - 1)) * 18;
    return categoryWeight + orderBonus + recencyBonus;
}

function selectFocusChartPoints(points, dates) {
    if (!points.length) return [];

    var dateList = dates || [];
    var target = window.innerWidth < 720 ? 14 : 24;
    if (points.length <= target) return points;

    var indexes = dateIndexMap(dateList);
    var totalDays = Math.max(1, dateList.length || points.length);
    var bucketSize = Math.max(1, Math.ceil(totalDays / target));
    var latestPoints = points.slice(-3);
    var byBucket = {};

    points.forEach(function(point) {
        var idx = pointDateIndex(point, indexes);
        if (idx < 0) return;
        var bucket = Math.floor(idx / bucketSize);
        var score = pointDisplayPriority(point, indexes, totalDays);
        var current = byBucket[bucket];
        if (!current || score > current.score) {
            byBucket[bucket] = { score: score, point: point };
        }
    });

    var selectedMap = {};
    Object.keys(byBucket).forEach(function(bucket) {
        var point = byBucket[bucket].point;
        selectedMap[getPointKey(point) + '|' + pointDate(point)] = point;
    });
    latestPoints.forEach(function(point) {
        selectedMap[getPointKey(point) + '|' + pointDate(point)] = point;
    });

    return Object.keys(selectedMap)
        .map(function(key) { return selectedMap[key]; })
        .sort(function(a, b) {
            return pointDateIndex(a, indexes) - pointDateIndex(b, indexes);
        })
        .slice(-target);
}
