function getModeMarkPoints(data) {
    return data.mark_points_composite || [];
}

function chartSymbolFor(category) {
    if (category === 'entry') return 'triangle';
    if (category === 'exit') return 'triangle';
    if (category === 'risk') return 'diamond';
    if (category === 'top') return 'diamond';
    if (category === 'bottom') return 'circle';
    return 'circle';
}

function chartSymbolSizeFor(category) {
    if (category === 'risk' || category === 'top') return 24;
    if (category === 'bottom') return 22;
    if (category === 'observe') return 12;
    return 32;
}

function compactChartSymbolSizeFor(category) {
    if (category === 'entry') return 20;
    if (category === 'exit') return 18;
    if (category === 'risk' || category === 'top') return 16;
    if (category === 'bottom') return 13;
    return 9;
}

function chartSymbolOffsetFor(category) {
    if (category === 'entry') return [0, 16];
    if (category === 'exit') return [0, -16];
    if (category === 'risk' || category === 'top') return [0, -13];
    if (category === 'bottom') return [0, 14];
    return [0, 8];
}

function styleChartPoint(point, view) {
    var meta = getPointMeta(point);
    var category = point.signalCategory || meta.category || 'observe';
    var compact = view === 'full';
    var styled = Object.assign({}, point);
    styled.symbol = chartSymbolFor(category);
    styled.symbolSize = compact ? compactChartSymbolSizeFor(category) : chartSymbolSizeFor(category);
    styled.symbolOffset = chartSymbolOffsetFor(category);
    styled.symbolRotate = category === 'exit' ? 180 : 0;
    styled.itemStyle = Object.assign({}, point.itemStyle || {}, {
        color: meta.color,
        opacity: compact && category === 'observe' ? 0.5 : 0.92
    });
    styled.label = Object.assign({}, point.label || {}, {
        show: !compact && category !== 'observe',
        formatter: meta.label,
        position: 'inside',
        color: '#fff',
        fontSize: meta.label.length > 2 ? 10 : 11,
        fontWeight: 'bold'
    });
    if (category === 'observe') {
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
    var idx = pointDateIndex(point, indexes);
    var categoryWeight = {
        exit: 88,
        risk: 82,
        top: 78,
        entry: 70,
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
