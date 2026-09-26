function isScanJobTerminal(status) {
    return ['completed', 'cancelled', 'failed', 'interrupted'].indexOf(status) >= 0;
}

function getScanStatusText(status) {
    if (status === 'queued') return '排队';
    if (status === 'running') return '运行中';
    if (status === 'cancelling') return '停止中';
    if (status === 'cancelled') return '已停止';
    if (status === 'failed') return '失败';
    if (status === 'interrupted') return '已中断';
    return '完成';
}

function getRefreshPolicyText(policy) {
    if (policy === 'cache') return '仅读本地';
    if (policy === 'force') return '全量重扫';
    return '增量更新';
}

function isStrategyMigrationJob(job) {
    return Boolean(job && (job.scope === 'legacy_strategy' || job.code_source === 'legacy_strategy'));
}

function getScanJobLabel(job) {
    return isStrategyMigrationJob(job) ? '策略迁移' : getScanConfig(job.scan_type).title;
}

function formatDuration(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return '-';
    var value = Math.max(0, Number(seconds));
    if (value < 60) return Math.round(value) + 's';
    var minutes = Math.floor(value / 60);
    var rest = Math.round(value % 60);
    return minutes + 'm ' + rest + 's';
}

function formatJobEta(job) {
    if (!job || isScanJobTerminal(job.status)) return '-';
    if (job.eta_seconds == null || Number.isNaN(Number(job.eta_seconds))) return '计算中';
    return formatDuration(job.eta_seconds);
}

function formatJobSpeed(job) {
    if (!job || job.rate_per_minute == null || Number.isNaN(Number(job.rate_per_minute))) return '-';
    return Number(job.rate_per_minute).toFixed(1) + '/分';
}

function formatJobCoverage(job) {
    var skipped = Number(job.skipped_count || 0);
    var legacy = Number(job.legacy_strategy_count || 0);
    var remaining = Number(job.remaining_count || 0);
    var batchIndex = Number(job.current_batch_index || 0);
    var batchCount = Number(job.batch_count || 0);
    var text = (job.completed || 0) + '/' + (job.total || 0);
    if (batchCount > 0) {
        text += ' · 批次 ' + (batchIndex || 1) + '/' + batchCount;
    }
    if (legacy > 0) text += ' · 旧策略 ' + legacy;
    if (skipped > 0) text += ' · 跳过 ' + skipped;
    if (!isScanJobTerminal(job.status) && remaining > 0) text += ' · 剩余 ' + remaining;
    if (job.resume_supported && job.status !== 'completed') text += ' · 可续跑';
    return text;
}

function formatMarketDataCoverage(job) {
    var coverage = job && job.data_coverage;
    if (!coverage || !Number(coverage.checked_count || 0)) return '';
    var parts = [];
    if (job.universe_as_of) parts.push('股票池 ' + job.universe_as_of);
    parts.push('行情核对 ' + coverage.checked_count + ' 只');
    if (coverage.current_session_closed_count) parts.push('当日收盘 ' + coverage.current_session_closed_count);
    if (coverage.intraday_preview_count) parts.push('盘中预览 ' + coverage.intraday_preview_count);
    if (coverage.stale_or_no_new_bar_count) {
        parts.push('旧数据/无新K线 ' + coverage.stale_or_no_new_bar_count);
    }
    var detailedNoDataCount = Number(coverage.provider_empty_count || 0) +
        Number(coverage.provider_error_count || 0) +
        Number(coverage.provider_partial_failure_count || 0);
    if (coverage.provider_empty_count) parts.push('源无数据 ' + coverage.provider_empty_count);
    if (coverage.provider_error_count) parts.push('源请求失败 ' + coverage.provider_error_count);
    if (coverage.provider_partial_failure_count) {
        parts.push('源部分异常 ' + coverage.provider_partial_failure_count);
    }
    if (coverage.no_data_count && !detailedNoDataCount) {
        parts.push('无数据/源未返回 ' + coverage.no_data_count);
    } else if (coverage.no_data_count > detailedNoDataCount) {
        parts.push('其他无数据 ' + (coverage.no_data_count - detailedNoDataCount));
    }
    if (coverage.stale_cache_count) parts.push('陈旧缓存 ' + coverage.stale_cache_count);
    if (coverage.analysis_error_count) parts.push('分析失败 ' + coverage.analysis_error_count);
    if (coverage.unknown_count) parts.push('状态未知 ' + coverage.unknown_count);
    if (coverage.stale_or_no_new_bar_count || coverage.no_data_count || coverage.stale_cache_count) {
        parts.push('未更新不等于停牌');
    }
    return parts.join(' · ');
}

function formatJobDetail(job) {
    if (!job) return '-';
    var parts = [
        '完成 ' + (job.completed || 0) + '/' + (job.total || 0),
        '命中 ' + (job.matched || 0)
    ];
    if (job.failed) parts.push('失败 ' + job.failed);
    if (!isScanJobTerminal(job.status)) {
        parts.push('剩余 ' + (job.remaining_count || 0));
        parts.push('预计 ' + formatJobEta(job));
        parts.push('速度 ' + formatJobSpeed(job));
    } else if (job.status === 'completed') {
        parts.push('跳过 ' + (job.skipped_count || 0));
    } else if (job.error) {
        parts.push(job.error);
    }
    if (job.recovery_hint) {
        parts.push(job.recovery_hint);
    }
    return parts.join(' · ');
}
