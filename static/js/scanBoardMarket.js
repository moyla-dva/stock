var scanBoardMarketCache = {};

function scanBoardMarketKey(type, name, indexCode) {
    return [type || 'industry', indexCode || '', name || ''].join(':');
}

function shouldSkipScanBoardMarket(type, name) {
    var value = String(name || '').trim();
    if (!value) return true;
    return value === '未识别板块' || value === '未识别概念';
}

function formatScanBoardReturn(value) {
    if (typeof formatSignedPercent === 'function') {
        return formatSignedPercent(value);
    }
    if (value == null || Number.isNaN(Number(value))) return '-';
    var number = Number(value);
    return (number > 0 ? '+' : '') + number.toFixed(2) + '%';
}

function renderAfterScanBoardMarketLoad() {
    if (typeof renderActiveScanPool === 'function') {
        renderActiveScanPool();
    }
}

function ensureScanBoardMarket(type, name, indexCode) {
    if (shouldSkipScanBoardMarket(type, name)) return null;
    var key = scanBoardMarketKey(type, name, indexCode);
    var cached = scanBoardMarketCache[key];
    if (cached) return cached;

    cached = {
        status: 'loading',
        type: type,
        name: name,
        indexCode: indexCode || ''
    };
    scanBoardMarketCache[key] = cached;

    if (typeof fetchBoardMarket !== 'function') {
        cached.status = 'error';
        cached.error = '板块行情接口不可用';
        return cached;
    }

    fetchBoardMarket(type, name, indexCode)
        .then(function(payload) {
            cached.status = payload && payload.available === false ? 'unavailable' : 'ready';
            cached.payload = payload || {};
        })
        .catch(function(error) {
            cached.status = 'error';
            cached.error = error && error.message ? error.message : '板块行情加载失败';
        })
        .finally(renderAfterScanBoardMarketLoad);

    return cached;
}

function scanBoardMarketText(type, name, indexCode) {
    var entry = ensureScanBoardMarket(type, name, indexCode);
    if (!entry) return '';
    var prefix = type === 'concept' ? '概指' : '板指';
    if (entry.status === 'loading') return prefix + ' 加载中';
    if (entry.status === 'error') return prefix + ' 暂缺';

    var payload = entry.payload || {};
    if (entry.status === 'unavailable' || payload.available === false) {
        return prefix + ' 暂不可用';
    }
    var trend = payload.trend_label || '-';
    var ret5 = payload.ret_5 != null ? payload.ret_5 : payload.change_pct;
    var retText = formatScanBoardReturn(ret5);
    var score = payload.strength_score == null ? '' : ' · 强 ' + formatNumber(payload.strength_score, 1);
    var fallback = payload.cache_fallback ? ' · 缓存' : '';
    var stale = payload.cache_stale ? '旧' : '';
    return prefix + ' ' + trend + ' · 5日 ' + retText + score + fallback + stale;
}
