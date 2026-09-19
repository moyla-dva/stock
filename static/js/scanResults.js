function scanResultStrategyStatus(item) {
    return item && item.strategy_status === 'current' ? 'current' : 'legacy';
}

function scanResultStrategyGroupLabel(status) {
    return status === 'current' ? '当前策略结果' : '旧策略结果';
}

function createScanResultGroupHeader(status, count) {
    var header = document.createElement('div');
    header.className = 'scan-result-group scan-result-group--' + status;
    var title = document.createElement('strong');
    title.textContent = scanResultStrategyGroupLabel(status);
    var meta = document.createElement('span');
    meta.textContent = '当前展示 ' + count + ' 只' + (status === 'legacy' ? ' · 重算后会被替换' : '');
    header.appendChild(title);
    header.appendChild(meta);
    return header;
}

function createScanResultLoadMore(meta) {
    var footer = document.createElement('div');
    footer.className = 'scan-load-more';

    var copy = document.createElement('div');
    copy.className = 'scan-load-more__copy';
    var loaded = meta.loadedCount || 0;
    var total = meta.totalCount || loaded;
    var filtered = meta.filteredCount == null ? loaded : meta.filteredCount;
    copy.textContent = '已载入 ' + loaded + '/' + total + ' 只，当前名单看到 ' + filtered + ' 只';
    if (meta.hasActiveFilters && meta.hasMore) {
        copy.textContent += ' · 下一步会扩大到全池继续找';
    }

    var button = document.createElement('button');
    button.type = 'button';
    button.textContent = meta.loadingMore
        ? '扩展中'
        : (meta.hasActiveFilters ? '扩大查找' : '扩展名单');
    button.disabled = Boolean(meta.loadingMore);
    button.onclick = function() {
        if (typeof loadMoreScanResults === 'function') {
            loadMoreScanResults();
        }
    };

    footer.appendChild(copy);
    footer.appendChild(button);
    return footer;
}

function renderScanResultSummary(meta) {
    var summary = document.getElementById('scan-result-summary');
    if (!summary) return;
    meta = meta || {};
    var loaded = meta.loadedCount || 0;
    var total = meta.totalCount || loaded;
    var filtered = meta.filteredCount == null ? loaded : meta.filteredCount;
    var hiddenByFilter = Math.max(0, loaded - filtered);
    var unloaded = Math.max(0, total - loaded);

    summary.innerHTML = '';
    var copy = document.createElement('div');
    copy.className = 'scan-result-summary__copy';
    [
        ['当前名单', filtered],
        ['已载入', loaded + '/' + total],
        ['待扩展', unloaded]
    ].filter(Boolean).forEach(function(part) {
        var metric = document.createElement('span');
        metric.textContent = part[0] + ' ' + part[1];
        copy.appendChild(metric);
    });
    if ((typeof normalizeScanSortMode === 'function' ? normalizeScanSortMode(scanWorkspaceState.filters.sort) : (scanWorkspaceState.filters.sort || 'system')) !== 'system') {
        var sortNote = document.createElement('small');
        sortNote.textContent = '当前为手动补充查看';
        copy.appendChild(sortNote);
    }
    if (hiddenByFilter) {
        var filterNote = document.createElement('small');
        filterNote.textContent = '筛选暂时隐藏 ' + hiddenByFilter + ' 只';
        copy.appendChild(filterNote);
    }
    if (meta.queueCounts) {
        var queueNote = document.createElement('small');
        queueNote.textContent = Object.keys(meta.queueCounts).map(function(label) {
            return label + ' ' + meta.queueCounts[label];
        }).join(' · ');
        copy.appendChild(queueNote);
    }
    summary.appendChild(copy);

    var action = document.createElement('button');
    action.type = 'button';
    action.className = 'scan-result-summary__action';
    action.textContent = meta.loadingMore
        ? '扩展中'
        : (meta.hasMore ? (meta.hasActiveFilters ? '扩大查找' : '扩展名单') : '已加载全部');
    action.disabled = !meta.hasMore || Boolean(meta.loadingMore);
    action.onclick = function() {
        if (typeof loadMoreScanResults === 'function') {
            loadMoreScanResults();
        }
    };
    summary.appendChild(action);
}

function renderScanResults(list, results, variant, meta) {
    meta = meta || {};
    var queueCounts = {};
    (results || []).forEach(function(item) {
        var queue = typeof scanCandidateQueue === 'function' ? scanCandidateQueue(item) : null;
        if (!queue) return;
        queueCounts[queue.label] = (queueCounts[queue.label] || 0) + 1;
    });
    meta.queueCounts = queueCounts;
    renderScanResultSummary(meta);
    list.innerHTML = '';
    if (!results.length) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = meta.loadedCount ? '当前筛选暂无命中' : '暂无命中';
        list.appendChild(empty);
        if (meta.hasMore) {
            list.appendChild(createScanResultLoadMore(meta));
        }
        return;
    }
    // System order is score-descending; queue grouping would split that order.
    var groupCounts = results.reduce(function(counts, item) {
        var key = scanResultStrategyStatus(item);
        counts[key] = (counts[key] || 0) + 1;
        return counts;
    }, {});
    var previousGroup = null;
    results.forEach(function(item, index) {
        var groupKey = scanResultStrategyStatus(item);
        if (groupKey !== previousGroup) {
            list.appendChild(createScanResultGroupHeader(groupKey, groupCounts[groupKey] || 0));
            previousGroup = groupKey;
        }
        list.appendChild(createStockCard(item, variant, index));
    });
    if (meta.hasMore) {
        list.appendChild(createScanResultLoadMore(meta));
    }
}
