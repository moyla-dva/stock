function renderScanProgress(job) {
    var strip = document.getElementById('scan-progress-strip');
    if (!strip) return;
    var fill = document.getElementById('scan-progress-fill');
    var title = document.getElementById('scan-progress-title');
    var detail = document.getElementById('scan-progress-detail');
    var detailPanel = document.querySelector('.scan-job-progress');
    if (!job) {
        strip.hidden = true;
        if (detailPanel) detailPanel.hidden = true;
        if (fill) fill.style.width = '0%';
        return;
    }
    var progress = Math.max(0, Math.min(100, Number(job.progress || 0)));
    strip.className = 'scan-progress-strip scan-progress-strip--' + (job.status || 'queued');
    strip.hidden = false;
    if (detailPanel) detailPanel.hidden = false;
    if (fill) fill.style.width = progress + '%';
    if (title) {
        title.textContent = getScanJobLabel(job) + ' · ' + getRefreshPolicyText(job.refresh_policy) + ' · ' + getScanStatusText(job.status) + ' · ' + progress + '%';
    }
    if (detail) detail.textContent = formatProgressStripDetail(job);
}

function formatProgressStripDetail(job) {
    if (!job) return '-';
    var parts = [
        formatJobCoverage(job),
        '命中 ' + (job.matched || 0)
    ];
    if (job.status === 'completed') {
        parts.push('跳过 ' + (job.skipped_count || 0));
    } else if (!isScanJobTerminal(job.status)) {
        parts.push('速度 ' + formatJobSpeed(job));
    } else if (job.status === 'failed' && job.error) {
        parts.push(job.error);
    }
    return parts.join(' · ');
}

function renderPendingScanJob(scanType, refreshPolicy, title) {
    renderScanJobSummary({
        scan_type: scanType,
        refresh_policy: refreshPolicy,
        status: 'queued',
        progress: 0,
        completed: 0,
        total: 0,
        matched: 0,
        skipped_count: 0,
        remaining_count: 0,
        duration_seconds: 0,
        eta_seconds: null,
        rate_per_minute: null,
        current_code: '',
        pending_title: title || ''
    });
}

function renderScanJobSummary(job) {
    if (!job) {
        setText('scan-job-current', '-');
        setText('scan-job-duration', '-');
        setText('scan-data-job-current', '-');
        setText('scan-data-job-duration', '-');
        renderScanProgress(null);
        if (typeof renderScanDataWorkspace === 'function') renderScanDataWorkspace();
        return;
    }
    renderScanProgress(job);
    var current = getScanJobLabel(job) + ' · ' + getRefreshPolicyText(job.refresh_policy) + ' · ' + getScanStatusText(job.status) + ' · ' + formatJobCoverage(job);
    var duration = '耗时 ' + formatDuration(job.duration_seconds) + ' · 预计 ' + formatJobEta(job);
    setText('scan-job-current', current);
    setText('scan-job-duration', duration);
    setText('scan-data-job-current', current);
    setText('scan-data-job-duration', duration);
    if (typeof renderScanDataWorkspace === 'function') renderScanDataWorkspace();
}

function createScanJobItem(job) {
    var item = document.createElement('div');
    item.className = 'scan-job-item scan-job-item--' + job.status;
    item.setAttribute('role', 'button');
    item.tabIndex = 0;

    var main = document.createElement('div');
    main.className = 'scan-job-item__main';

    var label = document.createElement('span');
    label.textContent = getScanJobLabel(job) + ' · ' + getRefreshPolicyText(job.refresh_policy) + ' · ' + (job.created_at || '-').replace('T', ' ');

    var detail = document.createElement('strong');
    detail.textContent = formatJobDetail(job) + ' · 耗时 ' + formatDuration(job.duration_seconds);

    var status = document.createElement('div');
    status.className = 'scan-job-item__status';
    status.textContent = getScanStatusText(job.status);

    main.appendChild(label);
    main.appendChild(detail);
    item.appendChild(main);
    item.appendChild(status);
    if (job.restart_interrupted || job.resume_supported) {
        var action = document.createElement('button');
        action.type = 'button';
        action.className = 'scan-job-item__action';
        action.textContent = '续扫';
        action.onclick = function(event) {
            event.stopPropagation();
            resumeScanJob(job);
        };
        item.appendChild(action);
    }
    item.onclick = function() {
        setScanPool(job.scan_type);
    };
    item.onkeydown = function(event) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            setScanPool(job.scan_type);
        }
    };
    return item;
}

function renderScanJobHistory(jobs) {
    scanWorkspaceState.jobs = jobs || [];
    var lists = [
        document.getElementById('scan-job-list'),
        document.getElementById('scan-data-job-list')
    ].filter(Boolean);
    if (!lists.length) return;
    lists.forEach(function(list) {
        list.innerHTML = '';
    });
    if (!scanWorkspaceState.jobs.length) {
        renderScanJobSummary(null);
        lists.forEach(function(list) {
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = '暂无任务记录';
            list.appendChild(empty);
        });
        return;
    }
    renderScanJobSummary(scanWorkspaceState.jobs[0]);
    lists.forEach(function(list) {
        scanWorkspaceState.jobs.slice(0, 8).forEach(function(job) {
            list.appendChild(createScanJobItem(job));
        });
    });
}

function renderScanJob(job) {
    if (!job) return;
    var config = getScanConfig(job.scan_type);
    renderScanJobSummary(job);
    applyRunningScanJobToWorkspace(job);
    renderScanWorkspace();
    if (job.status === 'queued') {
        setScanStatus('任务排队');
    } else if (job.status === 'running') {
        setScanStatus(config.title + '扫描中');
    } else if (job.status === 'cancelling') {
        setScanStatus('停止中');
    } else if (job.status === 'cancelled') {
        setScanStatus('已停止');
    } else if (job.status === 'failed') {
        setScanStatus('扫描失败');
    } else if (job.status === 'interrupted') {
        setScanStatus('扫描中断');
    } else {
        setScanStatus('结果已更新');
    }
}
