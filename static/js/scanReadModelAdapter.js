function isScanIndexReadRequested() {
    if (typeof window === 'undefined' || !window.location) return true;
    return new URLSearchParams(window.location.search || '').get('candidate_source') !== 'json';
}

function isScanIndexOptInRequested() {
    return isScanIndexReadRequested();
}

function shouldUseScanIndexRead(options) {
    options = options || {};
    return isScanIndexReadRequested()
        && !options.forceJson
        && scanWorkspaceState.readSourceOverride !== 'json';
}

function scanIndexPriorityLabel(group) {
    return {
        trade_ready: '计划可执行',
        structure_watch: '结构观察',
        risk_control: '风险控制',
        repair_watch: '修复观察'
    }[group] || 'V2 候选';
}

function scanIndexPermissionLabel(permission, scanType) {
    if (scanType === 'risk' || permission === 'risk_only') return '风险验证';
    if (scanType === 'bottom_div') return '修复观察';
    return {
        attack_allowed: 'C爆许可通过',
        breakout_allowed: 'C突许可通过',
        pullback_allowed: 'C回许可通过',
        structure_only: '结构观察',
        watch_only: '等待确认',
        forbidden: '暂不允许参与'
    }[permission] || '许可待核';
}

function scanIndexSummaryToWorkspaceItem(row, scanType) {
    row = row || {};
    var rankContext = row.rank_context || {};
    var priorityScore = rankContext.priority_score == null
        ? row.priority_score
        : rankContext.priority_score;
    var priorityGroup = rankContext.priority_group || row.priority_group || '';
    var displayScore = rankContext.final_score == null
        ? row.final_score
        : rankContext.final_score;
    var isRiskPool = scanType === 'risk';
    var isRepairPool = scanType === 'bottom_div';
    var isActionablePermission = ['attack_allowed', 'breakout_allowed', 'pullback_allowed'].indexOf(row.permission) >= 0;
    var role = isRiskPool ? 'risk' : (isRepairPool ? 'watch' : (isActionablePermission ? 'entry' : 'watch'));
    var roleLabel = isRiskPool ? '风险验证' : (isRepairPool ? '修复观察' : (isActionablePermission ? '参与候选' : '结构观察'));
    var stateModel = {
        state: row.state || '',
        signal: row.signal_label || '',
        signal_name: row.signal_key || '',
        permission: row.permission || '',
        permission_label: scanIndexPermissionLabel(row.permission, scanType),
        role: role,
        role_label: roleLabel,
        tone: isRiskPool ? 'warning' : (isActionablePermission ? 'positive' : 'muted'),
        detail: row.reason_summary || 'SQLite 列表摘要；完整依据按需读取。',
        next_action: row.plan_status === 'ready'
            ? '打开详情核对入场计划、止损与风险。'
            : '打开详情查看缺少的确认项，不将列表候选直接视为买点。',
        plan_status: row.plan_status || '',
        reason: row.reason_summary || '',
        candidate_missing_confirmations: row.missing_confirmations || [],
        candidate_invalidation_price: row.invalidation_price,
        requires_trade_plan: Boolean(row.requires_trade_plan),
        requires_stop_loss: Boolean(row.requires_stop_loss),
        v2_permission_model: {
            plan_status: row.plan_status || '',
            required_confirmations: row.missing_confirmations || [],
            plan_gate: {status: row.plan_status || ''}
        }
    };

    return {
        code: row.code || '',
        name: row.name || row.code || '',
        sector: row.sector || '',
        concepts: row.concepts || [],
        price: row.price,
        date: row.event_date || row.as_of || '',
        event_date: row.event_date || row.as_of || '',
        data_date: row.as_of || '',
        snapshot_day: row.snapshot_day || '',
        snapshot_revision: row.snapshot_revision || '',
        data_source: row.data_source || '',
        data_revision: row.data_revision || '',
        signal: row.signal_label || row.signal_key || '',
        signal_label: row.signal_label || row.signal_key || '',
        signal_name: row.signal_label || row.signal_key || '',
        signal_key: row.signal_key || '',
        v2_signal: row.signal_label || row.signal_key || '',
        v2_state: row.state || '',
        v2_permission: row.permission || '',
        v2_plan_status: row.plan_status || '',
        v2_state_model: stateModel,
        state: row.state || '',
        permission: row.permission || '',
        plan_status: row.plan_status || '',
        reason: row.reason_summary || '',
        reason_tags: row.reason_tags || [],
        missing_confirmations: row.missing_confirmations || [],
        candidate_invalidation_price: row.invalidation_price,
        requires_trade_plan: Boolean(row.requires_trade_plan),
        requires_stop_loss: Boolean(row.requires_stop_loss),
        final_score: displayScore,
        rank_score: displayScore,
        v2_priority_score: priorityScore,
        v2_priority_group: priorityGroup,
        v2_priority_label: scanIndexPriorityLabel(priorityGroup),
        confirm_score: row.confirm_score,
        risk_score: row.risk_score,
        score_confidence_label: row.profile_quality_label || '',
        score_confidence: row.profile_quality_score,
        strategy_status: row.strategy_status || 'unknown',
        strategy_version: row.strategy_version || '',
        _scan_type: scanType,
        scan_type: scanType,
        _compact: true,
        _indexed_summary: true
    };
}

function fetchScanIndexCandidatePage(options) {
    options = options || {};
    var params = new URLSearchParams();
    params.set('scan_type', options.scanType || 'opportunity');
    params.set('rank_mode', 'contextual');
    if (options.snapshotDay) params.set('snapshot_day', options.snapshotDay);
    if (options.sector) params.set('sector', options.sector);
    if (options.concept) params.set('concept', options.concept);
    if (options.query) params.set('query', options.query);
    if (options.reason) params.set('reason', options.reason);
    if (options.limit) params.set('limit', options.limit);
    if (options.offset) params.set('offset', options.offset);

    return requestJson('/api/scan_index/candidates?' + params.toString(), {
        signal: options.signal,
        timeoutMs: options.timeoutMs
    }).then(function (payload) {
        if (!payload || payload.source !== 'sqlite_index') {
            throw new Error('SQLite 候选接口返回了非索引数据');
        }
        return Object.assign({}, payload, {
            results: (payload.results || []).map(function (row, index) {
                var item = scanIndexSummaryToWorkspaceItem(row, payload.scan_type || options.scanType);
                item._read_rank = Number(payload.offset || 0) + index + 1;
                return item;
            })
        });
    });
}

function fetchScanIndexCandidateDetail(options) {
    options = options || {};
    var code = String(options.code || '').trim();
    if (!code) return Promise.reject(new Error('缺少候选股票代码'));
    var scanType = options.scanType || 'opportunity';
    var params = new URLSearchParams();
    params.set('scan_type', scanType);
    if (options.snapshotDay) params.set('snapshot_day', options.snapshotDay);
    if (options.eventDate) params.set('event_date', options.eventDate);

    return requestJson('/api/scan_index/candidates/' + encodeURIComponent(code) + '?' + params.toString(), {
        signal: options.signal,
        timeoutMs: options.timeoutMs
    }).then(function (detail) {
        var summary = detail && detail.summary;
        if (!summary || Number(detail.schema_version) !== 2) {
            throw new Error('SQLite 候选详情版本不兼容');
        }
        if (summary.code !== code || summary.pool !== scanType) {
            throw new Error('SQLite 候选详情身份与当前选择不一致');
        }
        if (options.eventDate && summary.event_date !== options.eventDate) {
            throw new Error('SQLite 候选详情事件日与当前选择不一致');
        }
        if (options.snapshotDay) {
            var requestedDay = String(options.snapshotDay).replace(/-/g, '');
            var actualDay = String(summary.snapshot_day || '').replace(/-/g, '');
            if (requestedDay !== actualDay) {
                throw new Error('SQLite 候选详情快照日与当前选择不一致');
            }
        }
        return detail;
    });
}

function scanIndexCandidateDetailToWorkspaceItem(compactItem, detail) {
    compactItem = compactItem || {};
    detail = detail || {};
    var summary = detail.summary || {};
    var decision = detail.decision_state || {};
    var permission = detail.permission || {};
    var structure = detail.structure_facts || {};
    var risk = detail.risk_conditions || {};
    var environment = detail.environment_context || {};
    var scoreContext = detail.score_context || {};
    var profile = detail.profile || {};
    var ruleResults = detail.rule_results || {};
    var scanType = summary.pool || compactItem._scan_type || compactItem.scan_type || 'opportunity';
    var actionable = ['attack_allowed', 'breakout_allowed', 'pullback_allowed'].indexOf(summary.permission) >= 0;
    var stateModel = {
        version: decision.v2_state_schema_version || decision.version || ('candidate-detail.v' + detail.schema_version),
        latest_date: summary.event_date || '',
        signal: decision.signal || summary.signal_label || '',
        signal_name: decision.signal_name || '',
        state: decision.state || summary.state || '',
        state_label: decision.state_label || summary.state || '',
        permission: decision.permission || summary.permission || '',
        permission_label: decision.permission_label || permission.permission_label || '',
        role: decision.role || (scanType === 'risk' ? 'risk' : (scanType === 'bottom_div' ? 'watch' : (actionable ? 'entry' : 'watch'))),
        role_label: decision.role_label || (scanType === 'risk' ? '风险验证' : (scanType === 'bottom_div' ? '修复观察' : (actionable ? '参与候选' : '结构观察'))),
        tone: decision.tone || (scanType === 'risk' ? 'warning' : (actionable ? 'positive' : 'muted')),
        reason: decision.reason || summary.reason_summary || '',
        detail: decision.detail || summary.reason_summary || '',
        next_action: decision.next_action || permission.next_action || ruleResults.next_action || '',
        plan_scope: decision.plan_scope || '',
        requires_trade_plan: Boolean(decision.requires_trade_plan == null ? summary.requires_trade_plan : decision.requires_trade_plan),
        requires_stop_loss: Boolean(decision.requires_stop_loss == null ? summary.requires_stop_loss : decision.requires_stop_loss),
        candidate_display_label: decision.candidate_display_label || '',
        candidate_substate: decision.candidate_substate || '',
        candidate_substate_label: decision.candidate_substate_label || '',
        candidate_trigger_plan: decision.candidate_trigger_plan || null,
        candidate_confirmation_price: decision.candidate_confirmation_price,
        candidate_invalidation_price: decision.candidate_invalidation_price == null ? summary.invalidation_price : decision.candidate_invalidation_price,
        candidate_missing_confirmations: decision.candidate_missing_confirmations || summary.missing_confirmations || [],
        event_mapping: ruleResults.event_mapping || {},
        scores: ruleResults.scores || {},
        v2_permission_model: permission,
        facts: Object.assign({}, structure, {
            risk: risk.risk || {},
            exit_gate: risk.exit_gate || {},
            macro_tide: environment.macro_tide || {}
        })
    };
    var item = Object.assign({}, compactItem, {
        code: summary.code || compactItem.code || '',
        name: profile.name || summary.name || compactItem.name || summary.code || '',
        sector: profile.sector || summary.sector || compactItem.sector || '',
        concepts: profile.concepts || summary.concepts || compactItem.concepts || [],
        price: summary.price == null ? compactItem.price : summary.price,
        date: summary.event_date || compactItem.date || '',
        event_date: summary.event_date || compactItem.event_date || '',
        data_date: detail.related_snapshot && detail.related_snapshot.data_date || compactItem.data_date || '',
        snapshot_day: summary.snapshot_day || compactItem.snapshot_day || '',
        snapshot_revision: summary.snapshot_revision || compactItem.snapshot_revision || '',
        data_source: summary.data_source || compactItem.data_source || '',
        data_revision: summary.data_revision || compactItem.data_revision || '',
        signal: decision.signal || summary.signal_label || compactItem.signal || '',
        signal_label: summary.signal_label || compactItem.signal_label || '',
        signal_name: decision.signal_name || compactItem.signal_name || '',
        signal_key: summary.signal_key || compactItem.signal_key || '',
        v2_signal: decision.signal || summary.signal_label || compactItem.v2_signal || '',
        v2_signal_name: decision.signal_name || compactItem.v2_signal_name || '',
        v2_state: decision.state || summary.state || '',
        v2_state_label: decision.state_label || summary.state || '',
        v2_permission: summary.permission || '',
        v2_permission_label: permission.permission_label || '',
        v2_effective_permission: summary.permission || '',
        v2_plan_status: summary.plan_status || '',
        v2_plan_status_label: permission.plan_status_label || '',
        v2_state_model: stateModel,
        state: decision.state || summary.state || '',
        permission: summary.permission || '',
        plan_status: summary.plan_status || '',
        reason: decision.reason || summary.reason_summary || '',
        reason_summary: summary.reason_summary || '',
        reason_tags: summary.reason_tags || [],
        candidate_display_label: decision.candidate_display_label || '',
        candidate_substate: decision.candidate_substate || '',
        candidate_substate_label: decision.candidate_substate_label || '',
        candidate_trigger_plan: decision.candidate_trigger_plan || null,
        candidate_confirmation_price: decision.candidate_confirmation_price,
        candidate_invalidation_price: stateModel.candidate_invalidation_price,
        candidate_missing_confirmations: stateModel.candidate_missing_confirmations,
        missing_confirmations: summary.missing_confirmations || [],
        requires_trade_plan: Boolean(summary.requires_trade_plan),
        requires_stop_loss: Boolean(summary.requires_stop_loss),
        trade_plan: detail.conditional_plan || null,
        explanation: detail.decision_explanation || {},
        profile_relation_groups: profile.profile_relation_groups || [],
        profile_relation_count: profile.profile_relation_count || 0,
        profile_relation_group_summary: profile.profile_relation_group_summary || '',
        _scan_type: scanType,
        scan_type: scanType,
        _compact: false,
        _detail_loading: false,
        _detail_error: '',
        _candidate_detail_source: 'sqlite_candidate_detail'
    });

    Object.keys(scoreContext).forEach(function (key) {
        if (item[key] == null) item[key] = scoreContext[key];
    });
    return item;
}

function fetchScanIndexWorkspace(options) {
    options = options || {};
    var scanTypes = SCAN_POOL_TYPES.slice();
    var requestedLimit = Math.max(1, Math.min(Number(options.limit) || SCAN_RESULT_PAGE_SIZE, 1000));
    return Promise.all(scanTypes.map(function (scanType) {
        return fetchScanIndexCandidatePage({
            scanType: scanType,
            snapshotDay: options.snapshotDay,
            limit: requestedLimit,
            signal: options.signal,
            timeoutMs: options.timeoutMs
        });
    })).then(function (pages) {
        var first = pages[0] || {};
        var health = first.index_health || {};
        if (!health.index_complete) {
            throw new Error('SQLite 候选索引尚未完成全量构建');
        }
        pages.forEach(function (page) {
            if (!page.ranking || !page.ranking.context_applied) {
                var reason = page.ranking && page.ranking.fallback_reason;
                throw new Error(reason || 'SQLite 当前候选排序上下文不可用');
            }
            if (page.latest_snapshot_day !== first.latest_snapshot_day) {
                throw new Error('SQLite 候选池快照日不一致');
            }
        });

        var pools = {};
        pages.forEach(function (page, index) {
            var scanType = scanTypes[index];
            var config = getScanConfig(scanType);
            pools[scanType] = {
                title: config.title,
                count: page.count || 0,
                loaded_count: page.loaded_count || 0,
                max_items: page.limit || requestedLimit,
                has_more: Boolean(page.has_more),
                results: page.results || []
            };
        });

        var activePage = pages[scanTypes.indexOf(options.activeType) >= 0
            ? scanTypes.indexOf(options.activeType)
            : 0] || first;
        var ranking = activePage.ranking || {};
        var strategyVersion = (activePage.results || [])[0]
            ? activePage.results[0].strategy_version
            : 'current';
        var snapshotCount = Number(health.valid_snapshot_count || 0);
        var latestDay = activePage.latest_snapshot_day || first.latest_snapshot_day || '-';
        var readSourceMeta = {
            index_health: health,
            ranking: ranking,
            candidate_count: activePage.pool_count || activePage.count || 0
        };
        var healthDetail = '完整索引 · ' + snapshotCount + ' 份快照'
            + ' · 排序 ' + (ranking.mode || 'contextual');
        return {
            read_source: 'sqlite_index',
            read_source_meta: readSourceMeta,
            read_source_error: '',
            scanned_count: 0,
            valid_snapshot_count: snapshotCount,
            stale_snapshot_count: 0,
            latest_data_date: activePage.latest_data_date || '-',
            latest_snapshot_day: latestDay,
            snapshot_meta: {
                read_source: 'sqlite_index',
                health: 'ready',
                health_label: 'SQLite 候选索引',
                health_summary: 'SQLite 索引完整',
                health_detail: healthDetail,
                strategy_version: strategyVersion
            },
            strategy_meta: {strategy_version: strategyVersion},
            strategy_health: null,
            max_items: requestedLimit,
            history_mode: Boolean(options.snapshotDay),
            history_snapshot_day: activePage.history_snapshot_day || '',
            pools: pools,
            sector_overview: [],
            concept_overview: []
        };
    });
}
