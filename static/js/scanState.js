var SCAN_POOL_TYPES = ['opportunity', 'risk', 'bottom_div'];
var SCAN_SIDE_VIEWS = ['detail'];
var SCAN_RESULT_PAGE_SIZE = 120;
var SCAN_RESULT_MAX_LIMIT = 6000;

var SCAN_STRATEGY_VIEW_STORAGE_KEY = 'scanStrategyView';

function readStoredScanStrategyView() {
    return 'v2';
}

var SCAN_ENTRY_MODEL_STORAGE_KEY = 'scanEntryModel';
var SCAN_ENTRY_MODELS = [
    { value: 'event_close', label: '信号日收盘入场' },
    { value: 'next_open', label: '次日开盘入场' }
];

function readStoredScanEntryModel() {
    try {
        var stored = window.localStorage.getItem(SCAN_ENTRY_MODEL_STORAGE_KEY);
        return SCAN_ENTRY_MODELS.some(function (item) { return item.value === stored; }) ? stored : 'event_close';
    } catch (error) {
        return 'event_close';
    }
}

var scanWorkspaceState = {
    activeType: 'opportunity',
    entryModel: readStoredScanEntryModel(),
    strategyView: readStoredScanStrategyView(),
    refreshPolicy: 'auto',
    sideView: 'detail',
    resultLimit: SCAN_RESULT_PAGE_SIZE,
    workspaceMaxItems: SCAN_RESULT_PAGE_SIZE,
    loadingMoreResults: false,
    loadingCandidateDetail: false,
    candidateDetailRequestKey: '',
    filteredCandidateLoads: {},
    selectedResult: null,
    previewResult: null,
    scanned_count: 0,
    valid_snapshot_count: 0,
    stale_snapshot_count: 0,
    latest_data_date: '-',
    latest_snapshot_day: '-',
    snapshotMeta: null,
    strategyMeta: null,
    strategyHealth: null,
    conceptCache: null,
    dataSources: null,
    conceptJob: null,
    pendingScanPlan: null,
    historyMode: false,
    historySnapshotDay: '',
    historyDays: [],
    historyLoading: false,
    historyError: '',
    cacheStatus: null,
    pools: {},
    sectorOverview: [],
    conceptOverview: [],
    marketStructureMeta: null,
    jobs: [],
    resonanceCalibration: null,
    replayCalibration: null,
    filters: {
        query: '',
        sector: '',
        concept: '',
        reason: '',
        sort: 'system'
    }
};
var scanProfileRequestState = {};
var SCAN_PROFILE_ENRICH_LIMIT = 80;
var UNKNOWN_SCAN_SECTOR = '未识别板块';

function normalizeScanPoolType(scanType) {
    return SCAN_POOL_TYPES.indexOf(scanType) >= 0 ? scanType : 'opportunity';
}

function getScanConfig(scanType) {
    if (scanType === 'risk') {
        return {
            title: '风险验证',
            action: '更新风险验证',
            tabId: 'scan-pool-risk',
            countId: 'scan-count-risk',
            variant: 'risk',
            unit: '只风险验证'
        };
    }
    if (scanType === 'bottom_div') {
        return {
            title: '修复观察',
            action: '更新修复观察',
            tabId: 'scan-pool-bottom-div',
            countId: 'scan-count-bottom-div',
            variant: 'bottom',
            unit: '只修复线索'
        };
    }
    return {
        title: '参与候选',
        action: '更新参与候选',
        tabId: 'scan-pool-opportunity',
        countId: 'scan-count-opportunity',
        variant: 'opportunity',
        unit: '只参与候选'
    };
}

function getEmptyPool(scanType) {
    var config = getScanConfig(scanType);
    return {
        title: config.title,
        count: 0,
        loaded_count: 0,
        max_items: SCAN_RESULT_PAGE_SIZE,
        has_more: false,
        results: []
    };
}

function getScanPool(scanType) {
    scanType = normalizeScanPoolType(scanType);
    if (!scanWorkspaceState.pools[scanType]) {
        scanWorkspaceState.pools[scanType] = getEmptyPool(scanType);
    }
    return scanWorkspaceState.pools[scanType];
}

function scanPoolTotalCount(pool) {
    var value = pool && pool.count;
    var number = Number(value);
    if (Number.isFinite(number)) return number;
    return pool && Array.isArray(pool.results) ? pool.results.length : 0;
}

function scanPoolLoadedCount(pool) {
    var value = pool && pool.loaded_count;
    var number = Number(value);
    if (Number.isFinite(number)) return number;
    return pool && Array.isArray(pool.results) ? pool.results.length : 0;
}

function scanPoolHasMore(pool) {
    return Boolean(pool && (pool.has_more || scanPoolLoadedCount(pool) < scanPoolTotalCount(pool)));
}

function resetScanResultLimit() {
    scanWorkspaceState.resultLimit = SCAN_RESULT_PAGE_SIZE;
}

function increaseScanResultLimit() {
    var current = Number(scanWorkspaceState.resultLimit);
    if (!Number.isFinite(current) || current < SCAN_RESULT_PAGE_SIZE) current = SCAN_RESULT_PAGE_SIZE;
    scanWorkspaceState.resultLimit = Math.min(SCAN_RESULT_MAX_LIMIT, current + SCAN_RESULT_PAGE_SIZE);
    return scanWorkspaceState.resultLimit;
}

function hasActiveScanFilters() {
    var filters = scanWorkspaceState.filters || {};
    return Boolean(
        normalizeFilterText(filters.query || '')
        || filters.sector
        || filters.concept
        || filters.reason
    );
}

function increaseScanResultLimitForCurrentView(pool) {
    if (hasActiveScanFilters()) {
        var total = scanPoolTotalCount(pool);
        if (total) {
            scanWorkspaceState.resultLimit = Math.min(SCAN_RESULT_MAX_LIMIT, Math.max(total, scanWorkspaceState.resultLimit || 0));
            return scanWorkspaceState.resultLimit;
        }
    }
    return increaseScanResultLimit();
}

function formatNumber(value, digits) {
    if (value == null || Number.isNaN(Number(value))) return '-';
    var number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits == null ? 1 : digits) : '-';
}

function formatScanPrice(value) {
    return formatNumber(value, 2);
}

function formatPercent(value) {
    if (value == null || Number.isNaN(Number(value))) return '-';
    return formatNumber(value, 1) + '%';
}

function formatSignedPercent(value) {
    if (value == null || Number.isNaN(Number(value))) return '-';
    var number = Number(value);
    return (number > 0 ? '+' : '') + formatNumber(number, 2) + '%';
}

function scanConcepts(item, limit) {
    var concepts = item && Array.isArray(item.concepts) ? item.concepts : [];
    var clean = concepts
        .map(function(value) { return String(value || '').trim(); })
        .filter(Boolean);
    return limit == null ? clean : clean.slice(0, limit);
}

function scanConceptText(item, limit) {
    var concepts = scanConcepts(item, limit);
    return concepts.length ? concepts.join(' / ') : '';
}

function normalizeFilterText(value) {
    return String(value == null ? '' : value).trim().toLowerCase();
}

function scanEventDate(item) {
    return item.event_date || item.date || '';
}

function scanNumericValue(item, field, fallback) {
    var value = Number(item[field]);
    return Number.isFinite(value) ? value : fallback;
}

function scanStatNumber(stat, snakeField, camelField, fallback) {
    if (!stat) return fallback;
    var value = stat[snakeField];
    if (value == null && camelField) value = stat[camelField];
    value = Number(value);
    return Number.isFinite(value) ? value : fallback;
}

function scanStatText(stat, snakeField, camelField, fallback) {
    if (!stat) return fallback;
    var value = stat[snakeField];
    if (value == null && camelField) value = stat[camelField];
    return value == null || value === '' ? fallback : value;
}

function setScanStatus(text) {
    setText('scan-status', text);
}
