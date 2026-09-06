function renderScanPoolTabs() {
    var activeConfig = getScanConfig(scanWorkspaceState.activeType);
    SCAN_POOL_TYPES.forEach(function(scanType) {
        var config = getScanConfig(scanType);
        var tab = document.getElementById(config.tabId);
        var count = document.getElementById(config.countId);
        var pool = getScanPool(scanType);
        if (tab) tab.classList.toggle('active', scanWorkspaceState.activeType === scanType);
        if (count) count.innerText = pool.count || 0;
    });
    var activePool = getScanPool(scanWorkspaceState.activeType);
    renderMarketResultsHeading(activeConfig, activePool);
    updateScanButtonLabel();
}

function renderCandidateDeskBrief(pool, visibleCount, meta) {
    var node = document.getElementById('candidate-desk-brief');
    var label = document.getElementById('candidate-desk-brief-label');
    var title = document.getElementById('candidate-desk-brief-title');
    var detail = document.getElementById('candidate-desk-brief-detail');
    if (!node || !label || !title || !detail) return;

    var config = getScanConfig(scanWorkspaceState.activeType);
    var snapshotDay = scanWorkspaceState.historyMode
        ? (scanWorkspaceState.historySnapshotDay || scanWorkspaceState.latest_snapshot_day || '-')
        : (scanWorkspaceState.latest_snapshot_day || '-');
    var total = meta && meta.totalCount != null ? meta.totalCount : scanPoolTotalCount(pool);
    var loaded = meta && meta.loadedCount != null ? meta.loadedCount : scanPoolLoadedCount(pool);
    var hasMore = meta ? meta.hasMore : scanPoolHasMore(pool);
    var modeLabel = scanWorkspaceState.historyMode ? '历史快照' : '本地快照';
    var recommendation = typeof scanSystemRecommendation === 'function'
        ? scanSystemRecommendation()
        : {title: '读取结构', detail: '系统按当前语境整理名单。'};

    node.className = 'candidate-desk-brief candidate-desk-brief--' + config.variant;
    label.textContent = modeLabel + ' ' + snapshotDay;
    title.textContent = config.title + ' · 当前可见 ' + (visibleCount || 0) + ' 只';
    detail.textContent = recommendation.title
        + ' · 已载入 ' + loaded + '/' + total
        + (hasMore ? ' · 可继续扩展名单' : ' · 已覆盖当前名单');
}

function getActiveWorkspaceView() {
    return typeof getWorkspaceView === 'function' ? getWorkspaceView() : 'candidates';
}

function setScanActionButtonState(action, disabled, text) {
    if (!action) return;
    document.querySelectorAll('[data-scan-action="' + action + '"]').forEach(function(button) {
        if (!(button instanceof HTMLElement)) return;
        if (!button.dataset.defaultLabel) {
            button.dataset.defaultLabel = button.textContent;
        }
        button.disabled = Boolean(disabled);
        if (text != null) {
            button.textContent = text;
        } else if (button.dataset.defaultLabel) {
            button.textContent = button.dataset.defaultLabel;
        }
    });
}

function renderMarketResultsHeading(activeConfig, activePool) {
    var workspace = getActiveWorkspaceView();
    var label = document.getElementById('market-results-label');
    var heading = document.getElementById('market-results-heading');
    if (!label || !heading) return;

    if (workspace === 'data') {
        label.textContent = 'DATA BACKSTAGE · 治理与运维';
        heading.textContent = '数据后台';
        return;
    }

    var viewName = '执行层';
    if (scanWorkspaceState.activeType === 'risk') viewName = '风险检查名单';
    if (scanWorkspaceState.activeType === 'bottom_div') viewName = '修复观察名单';

    label.textContent = 'CANDIDATE DESK · ' + activeConfig.title;
    if (activePool.legacy_strategy_count) {
        label.textContent += ' · 旧策略 ' + activePool.legacy_strategy_count;
    }
    heading.textContent = activeConfig.title || viewName;
}

function renderActiveScanPool() {
    if (typeof resetScanContextThemeCache === 'function') {
        resetScanContextThemeCache();
    }
    var list = document.getElementById('scan-list');
    var panel = document.getElementById('scan-result-panel');
    var scope = panel ? panel.querySelector('.scan-result-scope') : null;
    var config = getScanConfig(scanWorkspaceState.activeType);
    var pool = getScanPool(scanWorkspaceState.activeType);
    var results = pool.results || [];
    var sectorStats = Array.isArray(pool.sector_stats) && pool.sector_stats.length
        ? pool.sector_stats
        : buildScanSectorStats(results);
    renderScanFilters(results, sectorStats);
    var visibleResults = getVisibleScanResults();
    if (!list) return;

    if (panel) panel.classList.add('is-visible');
    if (scope) {
        var historyPrefix = scanWorkspaceState.historyMode
            ? '历史 ' + (scanWorkspaceState.latest_snapshot_day || '-') + ' · '
            : '';
        var filterMeta = typeof getActiveScanFilterLoadMeta === 'function' ? getActiveScanFilterLoadMeta() : null;
        var totalCount = filterMeta ? filterMeta.count : scanPoolTotalCount(pool);
        var loadedCount = filterMeta ? filterMeta.loaded_count : scanPoolLoadedCount(pool);
        var hasMore = filterMeta ? filterMeta.has_more : scanPoolHasMore(pool);
        var summaryParts = [
            historyPrefix + config.title,
            '当前名单 ' + visibleResults.length + ' 只'
        ];
        summaryParts.push(
            hasMore
                ? '已载入 ' + loadedCount + '/' + totalCount
                : '已载入全部 ' + totalCount
        );
        scope.textContent = summaryParts.join(' · ');
    }
    var selectedStillVisible = visibleResults.some(function(item) {
        return isSelectedScanResult(item);
    });
    var previewStillVisible = visibleResults.some(function(item) {
        return isPreviewScanResult(item);
    });
    if (!previewStillVisible) {
        scanWorkspaceState.previewResult = null;
    }
    if (!scanWorkspaceState.selectedResult || scanWorkspaceState.selectedResult._scan_type !== scanWorkspaceState.activeType || !selectedStillVisible) {
        scanWorkspaceState.selectedResult = visibleResults.length
            ? Object.assign({}, visibleResults[0], {
                _variant: config.variant,
                _scan_type: scanWorkspaceState.activeType,
                _visible_rank: 1,
                _history_snapshot_day: scanWorkspaceState.historySnapshotDay || ''
            })
            : null;
    }
    var resultMeta = {
        pool: pool,
        filteredCount: visibleResults.length,
        loadedCount: filterMeta ? filterMeta.loaded_count : scanPoolLoadedCount(pool),
        totalCount: filterMeta ? filterMeta.count : scanPoolTotalCount(pool),
        hasMore: filterMeta ? filterMeta.has_more : scanPoolHasMore(pool),
        hasActiveFilters: typeof hasActiveScanFilters === 'function' ? hasActiveScanFilters() : false,
        loadingMore: Boolean(scanWorkspaceState.loadingMoreResults)
    };
    renderCandidateDeskBrief(pool, visibleResults.length, resultMeta);
    renderScanResults(list, visibleResults, config.variant, resultMeta);
    renderScanCandidateContext();
    renderScanSelection();
}

function renderScanDataWorkspace() {
    var meta = scanWorkspaceState.snapshotMeta || {};
    var strategy = scanWorkspaceState.strategyMeta || {};
    var concept = scanWorkspaceState.conceptCache || {};
    var conceptJob = scanWorkspaceState.conceptJob || null;
    var dataSources = scanWorkspaceState.dataSources || {};
    var sourceOverall = dataSources.overall || {};
    var activePool = getScanPool(scanWorkspaceState.activeType);
    var historyDays = scanWorkspaceState.historyDays || [];
    var currentJob = Array.isArray(scanWorkspaceState.jobs) && scanWorkspaceState.jobs.length
        ? scanWorkspaceState.jobs[0]
        : null;
    var strategyVersion = meta.strategy_version || strategy.strategy_version || '-';
    var decision = getScanDataGovernanceDecision(meta, concept, conceptJob, sourceOverall, historyDays, activePool, currentJob);

    setText('scan-data-loaded-count', scanWorkspaceState.scanned_count || 0);
    setText(
        'scan-data-result-detail',
        '数据 ' + (scanWorkspaceState.latest_data_date || '-')
            + ' · 结果 ' + (scanWorkspaceState.latest_snapshot_day || '-')
            + ' · 当前池 ' + (activePool.count || scanPoolTotalCount(activePool) || 0)
    );
    setText('scan-data-snapshot-health', meta.health_summary || meta.health_label || '等待');
    setText(
        'scan-data-snapshot-detail',
        '策略 ' + strategyVersion
            + ' · 有效 ' + (meta.valid_snapshot_count || scanWorkspaceState.valid_snapshot_count || 0)
            + ' · 过期 ' + (meta.stale_snapshot_count || scanWorkspaceState.stale_snapshot_count || 0)
    );
    setText('scan-data-concept-health', concept.available ? '已构建' : '未构建');
    setText(
        'scan-data-concept-detail',
        '覆盖 ' + (concept.stock_count || 0) + ' 只 · ' + (concept.concept_count || 0) + ' 概念'
    );
    setText('scan-data-source-health-main', sourceOverall.label || '读取中');
    setText('scan-data-source-detail-main', sourceOverall.summary || '等待数据源状态');
    setText('scan-data-history-title', historyDays.length ? '本地快照 ' + historyDays.length + ' 天' : '本地快照');
    setText(
        'scan-data-history-detail',
        historyDays.length
            ? '最新 ' + (historyDays[0].display_day || historyDays[0].snapshot_day || '-')
                + ' · ' + (historyDays[0].snapshot_count || 0) + ' 只'
                + ' · 当前策略 ' + (meta.current_strategy_snapshot_count || 0)
            : '暂无历史快照'
    );
    setText('scan-data-decision-title', decision.title);
    setText('scan-data-decision-detail', decision.detail);
    setText('scan-data-decision-badge', decision.badge);
    setText('scan-data-actions-detail', decision.actionDetail);
    renderScanDataDecisionTags(decision.tags || []);
    var decisionNode = document.getElementById('scan-data-decision');
    if (decisionNode) {
        decisionNode.className = 'scan-data-decision scan-data-decision--' + (decision.tone || 'ready');
    }
}

function renderScanDataDecisionTags(tags) {
    var container = document.getElementById('scan-data-decision-tags');
    if (!container) return;
    container.innerHTML = '';
    (tags || []).slice(0, 4).forEach(function(tag) {
        var node = document.createElement('span');
        node.className = 'scan-data-decision-tag';
        node.textContent = tag;
        container.appendChild(node);
    });
}

function createScanCandidateContextButton(text, onClick, tone) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'scan-candidate-context__button scan-candidate-context__button--' + (tone || 'secondary');
    button.textContent = text;
    button.onclick = onClick;
    return button;
}

function renderScanCandidateContext() {
    var node = document.getElementById('scan-candidate-context');
    var label = document.getElementById('scan-candidate-context-label');
    var title = document.getElementById('scan-candidate-context-title');
    var detail = document.getElementById('scan-candidate-context-detail');
    var actions = document.getElementById('scan-candidate-context-actions');
    if (!node || !label || !title || !detail || !actions) return;

    var recommendation = typeof scanSystemRecommendation === 'function'
        ? scanSystemRecommendation()
        : {title: '等待结构确认', detail: '系统按当前语境整理名单。', mode: 'system'};
    var filters = scanWorkspaceState.filters || {};
    var manualView = typeof getScanManualViewState === 'function'
        ? getScanManualViewState(filters)
        : {active: false, activeCount: 0, sortMode: 'system'};
    var hasManualRange = Boolean(filters.sector || filters.concept || filters.query);
    var queueLabel = scanWorkspaceState.activeType === 'risk'
        ? '风险验证'
        : (scanWorkspaceState.activeType === 'bottom_div' ? '修复观察' : '参与名单');

    label.textContent = '系统语境';
    title.textContent = hasManualRange ? '局部筛选' : ('全池' + queueLabel);
    detail.textContent = manualView.active
        ? '手动条件生效中，系统排序仍保留。'
        : recommendation.title + ' · ' + recommendation.detail;

    node.className = 'scan-candidate-context scan-candidate-context--open';
    actions.innerHTML = '';

    if (hasManualRange || (filters.sort && filters.sort !== 'system')) {
        actions.appendChild(createScanCandidateContextButton('回到系统名单', function() {
            if (typeof resetScanFilters === 'function') resetScanFilters();
        }, 'secondary'));
    }
}

function getScanDataGovernanceDecision(meta, concept, conceptJob, sourceOverall, historyDays, activePool, currentJob) {
    meta = meta || {};
    concept = concept || {};
    conceptJob = conceptJob || {};
    sourceOverall = sourceOverall || {};
    historyDays = historyDays || [];
    activePool = activePool || {};
    currentJob = currentJob || {};

    var tags = [];
    var actionDetail = '当前稳定时不需要频繁操作，只有提示异常、过期或缺失时再展开治理动作。';
    var snapshotHealth = meta.health || 'empty';
    var sourceStatus = sourceOverall.status || 'empty';
    var conceptRunning = Boolean(conceptJob && ['queued', 'running'].indexOf(conceptJob.status) >= 0);
    var conceptFailed = Boolean(conceptJob && ['failed', 'interrupted'].indexOf(conceptJob.status) >= 0);
    var jobRunning = Boolean(currentJob && ['queued', 'running', 'cancelling'].indexOf(currentJob.status) >= 0);
    var totalSnapshots = meta.valid_snapshot_count || scanWorkspaceState.valid_snapshot_count || 0;

    if (historyDays.length) tags.push('快照 ' + historyDays.length + ' 天');
    if (sourceStatus === 'warning') tags.push('数据源部分需治理');
    if (sourceStatus === 'empty') tags.push('数据底座未建立');
    if (conceptRunning) tags.push('概念库刷新中');
    if (conceptFailed) tags.push('概念库刷新失败');
    if (!concept.available && !conceptRunning) tags.push('概念库未建立');
    if (meta.stale_snapshot_count) tags.push('过期 ' + meta.stale_snapshot_count);
    if (meta.legacy_snapshot_count) tags.push('旧策略 ' + meta.legacy_snapshot_count);

    if (jobRunning) {
        var jobLabel = typeof getScanJobLabel === 'function' ? getScanJobLabel(currentJob) : '扫描任务';
        var policyLabel = typeof getRefreshPolicyText === 'function' ? getRefreshPolicyText(currentJob.refresh_policy) : '处理中';
        return {
            tone: 'busy',
            badge: '处理中',
            title: '后台正在整理结果，先等本轮任务完成',
            detail: jobLabel + ' · ' + policyLabel + ' · 已处理 ' + (currentJob.completed || 0) + '/' + (currentJob.total || 0) + '，结果落盘后再看结构和名单更稳。',
            tags: tags,
            actionDetail: '任务运行中不用重复触发刷新，等本轮结果完成后再决定是否补治理。'
        };
    }
    if (conceptRunning) {
        return {
            tone: 'busy',
            badge: '处理中',
            title: '概念库正在刷新，先等待画像补齐',
            detail: '概念库进度 ' + (conceptJob.completed || 0) + '/' + (conceptJob.total || 0) + '，完成后标签关系和结构画像会更完整。',
            tags: tags,
            actionDetail: '概念库刷新时无需重复点击，等完成后再判断是否需要补数据源或清理结果。'
        };
    }
    if (snapshotHealth === 'empty' || (!totalSnapshots && !scanWorkspaceState.scanned_count)) {
        return {
            tone: 'action',
            badge: '需建立',
            title: '还没有本地结果，先更新参与候选',
            detail: '先跑一遍当前池，生成本地结果后再看候选名单和历史回看，判断才有落点。',
            tags: tags.length ? tags : ['先生成本地结果'],
            actionDetail: '当前优先级最高的是更新参与候选，其它治理动作先不用管。'
        };
    }
    if (snapshotHealth === 'expired') {
        return {
            tone: 'action',
            badge: '需重建',
            title: '当前本地结果已过期，建议直接重建当前池',
            detail: meta.health_detail || '有效结果为空，当前页面看到的内容已经不够可靠。',
            tags: tags,
            actionDetail: '先重建当前池，再处理概念库或数据源的补充动作。'
        };
    }
    if (snapshotHealth === 'legacy') {
        return {
            tone: 'watch',
            badge: '建议重算',
            title: '当前结果还能看，但旧策略待重算',
            detail: meta.health_detail || '旧策略样本还在混用，建议补齐当前策略结果后再做横向比较。',
            tags: tags,
            actionDetail: '优先用增量补齐或重建当前池，其它治理动作放在后面。'
        };
    }
    if (snapshotHealth === 'partial') {
        return {
            tone: 'watch',
            badge: '需补齐',
            title: '本地结果部分可用，建议先补齐缺口',
            detail: meta.health_detail || '当前结构和名单可能只反映部分样本，先补齐后再看强弱更稳。',
            tags: tags,
            actionDetail: '优先做增量补齐，避免结构强弱和参与名单被缺失样本带偏。'
        };
    }
    if (sourceStatus === 'warning' || sourceStatus === 'empty' || !concept.available || conceptFailed) {
        return {
            tone: 'watch',
            badge: '需治理',
            title: '决策结果可用，但底层数据还没完全收口',
            detail: '今天可以先看候选名单，但概念底座或数据源仍建议补齐，避免标签解释不完整。',
            tags: tags,
            actionDetail: '先处理提示里的异常项，再考虑概念行情刷新或过期清理。'
        };
    }
    return {
        tone: 'ready',
        badge: '稳定',
        title: '本地结果稳定，可直接查看结构与参与名单',
        detail: '当前结果、概念底座和数据源都在可用区间，治理动作可以退到后台，按需再处理。',
        tags: tags.length ? tags : ['当前无需额外治理'],
        actionDetail: '当前更适合回到候选池和单股确认，不需要频繁刷新后台。'
    };
}

function renderScanWorkspace(workspace) {
    if (workspace) {
        applyScanWorkspacePayload(workspace);
    }
    renderScanCacheStrip();
    renderScanSnapshotMeta();
    renderScanPoolTabs();
    renderScanRefreshPolicy();
    renderActiveScanPool();
    renderScanDataWorkspace();
    if (typeof renderScanHistoryPanel === 'function') {
        renderScanHistoryPanel();
    }
    renderScanSideView();
}
