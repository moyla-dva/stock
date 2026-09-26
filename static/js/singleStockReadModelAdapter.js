function shouldUseSingleStockReadModel() {
    if (typeof window === 'undefined' || !window.location) return false;
    return new URLSearchParams(window.location.search || '').get('single_stock_source') !== 'legacy';
}

function singleStockAnalysisToChartPayload(model) {
    model = model || {};
    var identity = model.identity || {};
    var profile = model.profile || {};
    var marketData = model.market_data || {};
    var chart = model.chart || {};
    var series = chart.series || {};
    var observations = model.signal_observations || {};
    var quality = model.data_quality || {};

    if (Number(model.schema_version) !== 2 || !identity.code) {
        throw new Error('SingleStockAnalysis 响应版本不兼容');
    }
    if (!Array.isArray(chart.dates) || !Array.isArray(chart.candles)) {
        throw new Error('SingleStockAnalysis 缺少 K 线序列');
    }

    var events = Array.isArray(observations.events) ? observations.events : [];
    return {
        stock_code: identity.code,
        stock_name: profile.display_name || identity.code,
        stock_sector: profile.sector || '',
        stock_concepts: Array.isArray(profile.concepts) ? profile.concepts : [],
        tag_profile: profile.tag_profile || null,
        dates: chart.dates,
        k_data: chart.candles,
        candle_fields: chart.candle_fields || ['open', 'close', 'low', 'high'],
        ma20_data: series.ma20 || [],
        vwap_data: series.vwap || [],
        bull_power_data: series.bull_power || [],
        bear_power_data: series.bear_power || [],
        williams_r_data: series.williams_r || [],
        custom_data: series.custom || [],
        dif_data: series.dif || [],
        dea_data: series.dea || [],
        macd_data: series.macd || [],
        mark_points: Array.isArray(observations.mark_points) ? observations.mark_points : events,
        mark_points_v2: events,
        mark_points_old: observations.mark_points_old || [],
        mark_points_new: observations.mark_points_new || [],
        mark_points_opt: observations.mark_points_opt || [],
        v2_event_lookback: observations.event_lookback,
        score_summary: observations.score_summary || {},
        signal_definitions: observations.definitions || {},
        c_signal_v2_state: model.current_state || {},
        trade_plan: model.conditional_plan || {},
        multi_timeframes: model.timeframes || {},
        event_stats: (model.event_study || {}).results || {},
        data_identity: {
            bar_state: identity.bar_state || quality.bar_state || 'unknown',
            data_source: identity.data_source || quality.data_source || 'unknown',
            data_revision: identity.data_revision || 'unknown',
            generated_at: identity.generated_at || 'unknown',
            calendar_id: identity.calendar_id || quality.calendar_id || 'unknown',
            calendar_revision: identity.calendar_revision || quality.calendar_revision || 'unknown',
            calendar_evidence_level: identity.calendar_evidence_level || quality.calendar_evidence_level || 'unknown',
            cache_status: quality.cache_status || 'unknown',
            cache_written_at: quality.cache_written_at || 'unknown',
            latest_at: marketData.latest_at || identity.as_of || null,
            refresh_requested: Boolean(quality.refresh_requested)
        },
        market_data: marketData,
        data_quality: quality,
        single_stock_analysis: model,
        _single_stock_read_model_source: 'single_stock_analysis_v2'
    };
}
