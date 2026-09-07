function scanStrategyRank(item) {
    return item && item.strategy_status === 'current' ? 1 : 0;
}

function scanCompositeScore(item) {
    return scanNumericValue(item, 'final_score', scanNumericValue(item, 'rank_score', 0));
}

function scanV2PriorityScore(item) {
    return scanNumericValue(item, 'v2_priority_score', scanCompositeScore(item));
}

function scanUsesV2Priority() {
    return typeof isScanV2StrategyView === 'function' && isScanV2StrategyView();
}

var SCAN_SORT_MODES = ['system', 'sector', 'concept', 'event', 'win', 'avg', 'risk'];

function normalizeScanSortMode(value) {
    return SCAN_SORT_MODES.indexOf(value) >= 0 ? value : 'system';
}

function getScanManualViewState(filters) {
    filters = filters || scanWorkspaceState.filters || {};
    var sortMode = normalizeScanSortMode(filters.sort);
    var activeCount = 0;
    if (filters.sector) activeCount += 1;
    if (filters.concept) activeCount += 1;
    if (sortMode !== 'system') activeCount += 1;
    return {
        sortMode: sortMode,
        activeCount: activeCount,
        active: activeCount > 0
    };
}

function resetScanContextThemeCache() {
    return null;
}

function getScanContextTheme() {
    return {line: null, source: 'none'};
}

function scanPoolTypeFromItem(item) {
    return item && (item._scan_type || item.scan_type) || scanWorkspaceState.activeType || 'opportunity';
}

function scanCandidateRole(item) {
    if (typeof isScanV2StrategyView === 'function' && isScanV2StrategyView()) {
        var v2Role = scanV2CandidateRole(item);
        if (v2Role) return v2Role;
    }
    var scanType = scanPoolTypeFromItem(item);
    var risk = scanNumericValue(item, 'risk_score', 0);
    var confirm = scanNumericValue(item, 'confirm_score', 0);
    var composite = scanCompositeScore(item);
    var sectorScore = scanNumericValue(item, 'sector_score', 0);
    var conceptScore = scanNumericValue(item, 'concept_score', 0);

    if (scanType === 'risk') {
        return {
            kind: 'risk_watch',
            label: risk >= 4 ? '重点风险' : '风险验证',
            tone: risk >= 4 ? 'danger' : 'warning',
            score: 70 + risk * 8,
            detail: '用于确认兑现压力、破位或高位分歧是否扩散。',
            action: risk >= 4 ? '先处理风险，再考虑是否回避。' : '等待风险确认，不按机会票处理。'
        };
    }
    if (scanType === 'bottom_div') {
        var ready = confirm >= 3 && risk <= 2;
        return {
            kind: 'repair_watch',
            label: ready ? '修复候选' : '修复观察',
            tone: ready ? 'positive' : 'warning',
            score: ready ? 84 : 48,
            detail: '低位或背离修复只看确认质量，不提前当作买点。',
            action: ready ? '等待放量或趋势确认后再看机会。' : '先记录，不急于交易。'
        };
    }
    if (risk <= 2 && composite >= 70) {
        return {
            kind: 'opportunity_candidate',
            label: '参与候选',
            tone: 'positive',
            score: 88 + Math.min(18, composite * 0.12),
            detail: '结构、确认和风险组合较好，仍需打开图表确认入场和止损。',
            action: '打开图表确认入场结构、止损距离和仓位。'
        };
    }
    if (Math.max(sectorScore, conceptScore, composite) >= 60) {
        return {
            kind: 'structure_candidate',
            label: '结构候选',
            tone: risk > 2 ? 'warning' : 'muted',
            score: 52,
            detail: '个股或板块存在结构线索，但还需要补确认。',
            action: '先观察共振是否继续增强。'
        };
    }
    return {
        kind: 'watch_candidate',
        label: '观察候选',
        tone: 'muted',
        score: 0,
        detail: '证据不足，先降低优先级。',
        action: '先观察，不作为优先交易对象。'
    };
}

function scanCandidateQueue(item) {
    if (scanUsesV2Priority() && item && item.v2_priority_group) {
        return {
            key: item.v2_priority_group,
            label: item.v2_priority_label || 'V2状态',
            detail: item.v2_priority_detail || '按 V2 状态模型整理名单。',
            tone: item.v2_priority_tone || 'muted',
            priority: scanNumericValue(item, 'v2_queue_priority', 0)
        };
    }
    var role = scanCandidateRole(item);
    var kind = role && role.kind;
    if (kind === 'opportunity_candidate') {
        return {
            key: 'priority',
            label: '优先跟踪',
            detail: '综合结构较好，等待图表确认入场结构。',
            tone: 'positive',
            priority: 5
        };
    }
    if (kind === 'repair_watch') {
        return {
            key: 'repair',
            label: '修复观察',
            detail: '低位或背离修复，等待右侧确认。',
            tone: 'warning',
            priority: 4
        };
    }
    if (kind === 'risk_watch') {
        return {
            key: 'risk',
            label: '风险验证',
            detail: '用于确认压力是否扩散，不按机会票处理。',
            tone: 'danger',
            priority: 3
        };
    }
    if (kind === 'structure_candidate') {
        return {
            key: 'structure',
            label: '结构备选',
            detail: '有结构或共振线索，但确认不足。',
            tone: 'muted',
            priority: 2
        };
    }
    return {
        key: 'watch',
        label: '观察',
        detail: '证据不足，先降低优先级。',
        tone: 'muted',
        priority: 1
    };
}

function scanSystemRecommendation() {
    var scanType = scanWorkspaceState.activeType;
    if (scanType === 'risk') {
        return {
            title: '先处理风险验证',
            detail: '按 V2 风控状态、风险分、板块风险和事件新近度排序。',
            mode: 'risk'
        };
    }
    if (scanType === 'bottom_div') {
        return {
            title: '先看修复是否成形',
            detail: '按 V2 修复/研究状态、确认分、低风险和共振强度排序。',
            mode: 'repair'
        };
    }
    return {
        title: '先看可参与候选',
        detail: '按 V2 许可状态、综合分、确认分、低风险和行业/概念共振排序。',
        mode: 'opportunity'
    };
}

function renderScanRecommendation() {
    var title = document.getElementById('scan-recommendation-title');
    var detail = document.getElementById('scan-recommendation-detail');
    if (!title && !detail) return;
    var manualView = getScanManualViewState();
    if (manualView.active) {
        if (title) title.textContent = '手动补充查看';
        if (detail) detail.textContent = '当前有 ' + manualView.activeCount + ' 项手动条件生效。';
        return;
    }
    var recommendation = scanSystemRecommendation();
    if (title) title.textContent = recommendation.title;
    if (detail) detail.textContent = recommendation.detail;
}

function scanSystemRankScore(item) {
    if (scanUsesV2Priority() && item && item.v2_priority_score != null) {
        return scanV2PriorityScore(item);
    }
    var scanType = scanPoolTypeFromItem(item);
    var roleScore = scanCandidateRole(item).score || 0;
    var composite = scanCompositeScore(item);
    var conceptScore = scanNumericValue(item, 'concept_score', 0);
    var sectorScore = scanNumericValue(item, 'sector_score', 0);
    var riskScore = scanNumericValue(item, 'risk_score', 0);
    var confirmScore = scanNumericValue(item, 'confirm_score', 0);
    var setupScore = scanNumericValue(item, 'setup_score', 0);
    if (scanType === 'risk') {
        return roleScore
            + riskScore * 18
            + scanNumericValue(item, 'sector_risk_count', 0) * 4
            + scanNumericValue(item, 'concept_risk_count', 0) * 4
            + composite * 0.35;
    }
    if (scanType === 'bottom_div') {
        return roleScore
            + Math.max(0, 8 - riskScore) * 8
            + confirmScore * 8
            + setupScore * 3
            + conceptScore * 0.35
            + sectorScore * 0.2
            + composite * 0.45;
    }
    return roleScore
        + composite
        + conceptScore * 0.35
        + sectorScore * 0.25
        + confirmScore * 6
        - riskScore * 8;
}

function compareScanResults(a, b) {
    var sort = normalizeScanSortMode(scanWorkspaceState.filters.sort);
    if (sort === 'system') {
        return scanStrategyRank(b) - scanStrategyRank(a)
            || scanCandidateQueue(b).priority - scanCandidateQueue(a).priority
            || (scanUsesV2Priority() ? scanV2PriorityScore(b) - scanV2PriorityScore(a) : 0)
            || scanSystemRankScore(b) - scanSystemRankScore(a)
            || String(scanEventDate(b)).localeCompare(String(scanEventDate(a)))
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'event') {
        return scanStrategyRank(b) - scanStrategyRank(a)
            || String(scanEventDate(b)).localeCompare(String(scanEventDate(a)))
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'sector') {
        return scanStrategyRank(b) - scanStrategyRank(a)
            || scanNumericValue(b, 'sector_score', 0) - scanNumericValue(a, 'sector_score', 0)
            || scanNumericValue(b, 'sector_market_score', 0) - scanNumericValue(a, 'sector_market_score', 0)
            || scanNumericValue(b, 'concept_score', 0) - scanNumericValue(a, 'concept_score', 0)
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'concept') {
        return scanStrategyRank(b) - scanStrategyRank(a)
            || scanNumericValue(b, 'concept_score', 0) - scanNumericValue(a, 'concept_score', 0)
            || scanNumericValue(b, 'concept_market_score', 0) - scanNumericValue(a, 'concept_market_score', 0)
            || scanNumericValue(b, 'sector_score', 0) - scanNumericValue(a, 'sector_score', 0)
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'win') {
        return scanStrategyRank(b) - scanStrategyRank(a)
            || scanNumericValue(b, 'win_rate', -999) - scanNumericValue(a, 'win_rate', -999)
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'avg') {
        return scanStrategyRank(b) - scanStrategyRank(a)
            || scanNumericValue(b, 'avg_ret', -999) - scanNumericValue(a, 'avg_ret', -999)
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    if (sort === 'risk') {
        return scanStrategyRank(b) - scanStrategyRank(a)
            || scanNumericValue(a, 'risk_score', 999) - scanNumericValue(b, 'risk_score', 999)
            || scanCompositeScore(b) - scanCompositeScore(a);
    }
    return scanStrategyRank(b) - scanStrategyRank(a)
        || scanCompositeScore(b) - scanCompositeScore(a)
        || String(scanEventDate(b)).localeCompare(String(scanEventDate(a)));
}

function scanResultMatchesFilters(item) {
    var filters = scanWorkspaceState.filters || {};
    var sector = item.sector || '';
    if (filters.sector) {
        if (filters.sector === UNKNOWN_SCAN_SECTOR) {
            if (sector) return false;
        } else if (sector !== filters.sector) {
            return false;
        }
    }
    if (filters.concept && scanConcepts(item).indexOf(filters.concept) < 0) {
        return false;
    }

    var query = normalizeFilterText(filters.query);
    if (!query) return true;
    return [
        item.code,
        item.name,
        item.sector,
        scanConceptText(item),
        item.signal_label,
        item.signal,
        item.signal_name,
        item.reason
    ].some(function(value) {
        return normalizeFilterText(value).indexOf(query) >= 0;
    });
}

function getVisibleScanResults() {
    var pool = getScanPool(scanWorkspaceState.activeType);
    return (pool.results || [])
        .filter(scanResultMatchesFilters)
        .slice()
        .sort(compareScanResults);
}

function buildScanSectorStats(results) {
    var stats = {};
    (results || []).forEach(function(item) {
        var sector = item.sector || UNKNOWN_SCAN_SECTOR;
        if (!stats[sector]) {
            stats[sector] = {
                sector: sector,
                count: 0,
                totalRank: 0,
                totalSectorScore: 0,
                sectorScoreCount: 0,
                riskCount: 0,
                signalCount: 0,
                latestEvent: ''
            };
        }
        stats[sector].count += 1;
        stats[sector].totalRank += scanNumericValue(item, 'rank_score', 0);
        if (item.sector_score != null) {
            stats[sector].totalSectorScore += scanNumericValue(item, 'sector_score', 0);
            stats[sector].sectorScoreCount += 1;
        }
        stats[sector].riskCount = Math.max(stats[sector].riskCount, scanNumericValue(item, 'sector_risk_count', 0));
        stats[sector].signalCount = Math.max(stats[sector].signalCount, scanNumericValue(item, 'sector_signal_count', 0));
        var eventDate = scanEventDate(item);
        if (eventDate && eventDate > stats[sector].latestEvent) {
            stats[sector].latestEvent = eventDate;
        }
    });
    return Object.keys(stats).map(function(sector) {
        var item = stats[sector];
        item.avgRank = item.count ? item.totalRank / item.count : 0;
        item.sectorScore = item.sectorScoreCount ? item.totalSectorScore / item.sectorScoreCount : 0;
        return item;
    }).sort(function(a, b) {
        return b.sectorScore - a.sectorScore || b.count - a.count || b.avgRank - a.avgRank || a.sector.localeCompare(b.sector);
    });
}

function buildScanConceptStats(results) {
    var stats = {};
    (results || []).forEach(function(item) {
        scanConcepts(item).forEach(function(concept) {
            if (!stats[concept]) {
                stats[concept] = {
                    concept: concept,
                    count: 0,
                    totalRank: 0,
                    totalConceptScore: 0,
                    conceptScoreCount: 0,
                    riskCount: 0,
                    signalCount: 0,
                    latestEvent: ''
                };
            }
            stats[concept].count += 1;
            stats[concept].totalRank += scanNumericValue(item, 'rank_score', 0);
            if (item.concept_score != null) {
                stats[concept].totalConceptScore += scanNumericValue(item, 'concept_score', 0);
                stats[concept].conceptScoreCount += 1;
            }
            stats[concept].riskCount = Math.max(stats[concept].riskCount, scanNumericValue(item, 'concept_risk_count', 0));
            stats[concept].signalCount = Math.max(stats[concept].signalCount, scanNumericValue(item, 'concept_signal_count', 0));
            var eventDate = scanEventDate(item);
            if (eventDate && eventDate > stats[concept].latestEvent) {
                stats[concept].latestEvent = eventDate;
            }
        });
    });
    return Object.keys(stats).map(function(concept) {
        var item = stats[concept];
        item.avgRank = item.count ? item.totalRank / item.count : 0;
        item.conceptScore = item.conceptScoreCount ? item.totalConceptScore / item.conceptScoreCount : 0;
        return item;
    }).sort(function(a, b) {
        return b.conceptScore - a.conceptScore || b.count - a.count || b.avgRank - a.avgRank || a.concept.localeCompare(b.concept);
    });
}

function renderScanFilters(poolResults, sectorStats) {
    var filters = scanWorkspaceState.filters;
    var search = document.getElementById('scan-search');
    var sectorSelect = document.getElementById('scan-sector-filter');
    var conceptSelect = document.getElementById('scan-concept-filter');
    var sortSelect = document.getElementById('scan-sort-filter');
    var advancedSummary = document.getElementById('scan-filter-advanced-summary');
    var advanced = document.querySelector('.scan-filter-advanced');
    var activePool = getScanPool(scanWorkspaceState.activeType);
    var conceptStats = Array.isArray(activePool.concept_stats) && activePool.concept_stats.length
        ? activePool.concept_stats
        : buildScanConceptStats(poolResults || []);
    var manualView = getScanManualViewState(filters);

    filters.sort = manualView.sortMode;

    if (search && search.value !== filters.query) search.value = filters.query;
    if (sectorSelect) {
        sectorSelect.innerHTML = '';
        var allOption = document.createElement('option');
        allOption.value = '';
        allOption.textContent = '全部行业';
        sectorSelect.appendChild(allOption);
        sectorStats.forEach(function(stat) {
            var option = document.createElement('option');
            option.value = stat.sector;
            option.textContent = stat.sector + ' (' + stat.count + ')';
            sectorSelect.appendChild(option);
        });
        sectorSelect.value = filters.sector;
        if (sectorSelect.value !== filters.sector) {
            filters.sector = '';
            sectorSelect.value = '';
        }
    }
    if (conceptSelect) {
        conceptSelect.innerHTML = '';
        var allConceptOption = document.createElement('option');
        allConceptOption.value = '';
        allConceptOption.textContent = '全部概念';
        conceptSelect.appendChild(allConceptOption);
        conceptStats.slice(0, 120).forEach(function(stat) {
            var option = document.createElement('option');
            option.value = stat.concept;
            option.textContent = stat.concept + ' (' + stat.count + ')';
            conceptSelect.appendChild(option);
        });
        conceptSelect.value = filters.concept;
        if (conceptSelect.value !== filters.concept) {
            filters.concept = '';
            conceptSelect.value = '';
        }
    }
    if (sortSelect && sortSelect.value !== manualView.sortMode) {
        sortSelect.value = manualView.sortMode;
    }
    if (advancedSummary) {
        advancedSummary.textContent = manualView.active
            ? '手动查看 · ' + manualView.activeCount + '项'
            : '手动查看';
    }
    if (advanced) {
        advanced.open = manualView.active;
    }

    renderScanRecommendation();
}

function renderAfterScanFilterChange() {
    renderActiveScanPool();
    enrichActiveScanProfiles();
}

function setScanFilterQuery(value) {
    scanWorkspaceState.filters.query = value || '';
    renderAfterScanFilterChange();
}

function setScanSectorFilter(value) {
    scanWorkspaceState.filters.sector = value || '';
    renderAfterScanFilterChange();
}

function setScanConceptFilter(value) {
    scanWorkspaceState.filters.concept = value || '';
    renderAfterScanFilterChange();
}

function setScanSort(value) {
    scanWorkspaceState.filters.sort = normalizeScanSortMode(value);
    renderAfterScanFilterChange();
}

function resetScanFilters() {
    scanWorkspaceState.filters.query = '';
    scanWorkspaceState.filters.sector = '';
    scanWorkspaceState.filters.concept = '';
    scanWorkspaceState.filters.sort = 'system';
    renderAfterScanFilterChange();
}
