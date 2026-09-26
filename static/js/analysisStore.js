var analysisStore = (function() {
    var state = {
        rootData: null,
        viewData: null,
        activePeriod: 'daily',
        analysisSeq: 0,
        activeAnalysisRequest: null,
        analysisLoading: false,
        chartPositionView: 'flat',
        timeframeSeq: 0,
        timeframeRequests: {}
    };

    function normalizeCode(code) {
        if (typeof normalizeChartStockCode === 'function') {
            return normalizeChartStockCode(code);
        }
        var match = String(code || '').match(/\d{6}/);
        return match ? match[0] : String(code || '').trim();
    }

    function normalizePeriod(period) {
        if (period === '60m' || period === '4h') return period;
        return 'daily';
    }

    function normalizeChartPositionView(view) {
        return view === 'position' ? 'position' : 'flat';
    }

    function currentChartData() {
        return state.rootData || state.viewData;
    }

    function syncState() {
        return state;
    }

    function beginAnalysis(code) {
        var request = {
            id: ++state.analysisSeq,
            code: normalizeCode(code)
        };
        state.activeAnalysisRequest = request;
        state.analysisLoading = true;
        state.activePeriod = 'daily';
        state.timeframeRequests = {};
        syncState();
        return request;
    }

    function isAnalysisRequestCurrent(request) {
        return Boolean(
            request
            && state.activeAnalysisRequest
            && request.id === state.activeAnalysisRequest.id
            && request.code === state.activeAnalysisRequest.code
        );
    }

    function completeAnalysis(request, payload) {
        if (!isAnalysisRequestCurrent(request)) return false;
        state.analysisLoading = false;
        state.rootData = payload || null;
        state.viewData = payload || null;
        state.activePeriod = 'daily';
        syncState();
        return true;
    }

    function failAnalysis(request, error) {
        if (!isAnalysisRequestCurrent(request)) return false;
        state.analysisLoading = false;
        syncState();
        return true;
    }

    function setRootData(payload) {
        state.rootData = payload || null;
        syncState();
    }

    function setViewData(payload) {
        state.viewData = payload || null;
        syncState();
    }

    function setActivePeriod(period) {
        state.activePeriod = normalizePeriod(period);
        syncState();
        return state.activePeriod;
    }

    function setChartPositionView(view) {
        state.chartPositionView = normalizeChartPositionView(view);
        syncState();
        return state.chartPositionView;
    }

    function getRootData() {
        return state.rootData;
    }

    function getViewData() {
        return state.viewData;
    }

    function getActivePeriod() {
        return state.activePeriod;
    }

    function getChartPositionView() {
        return state.chartPositionView;
    }

    function getTimeframeRequest(period) {
        return state.timeframeRequests[normalizePeriod(period)] || null;
    }

    function getTimeframePromise(period) {
        var request = getTimeframeRequest(period);
        return request ? request.promise : null;
    }

    function beginTimeframeLoad(period, code) {
        var key = normalizePeriod(period);
        if (key === 'daily') return null;
        var existing = state.timeframeRequests[key];
        if (existing && existing.promise) return existing;
        var request = {
            id: ++state.timeframeSeq,
            period: key,
            code: normalizeCode(code),
            promise: null
        };
        state.timeframeRequests[key] = request;
        syncState();
        return request;
    }

    function attachTimeframePromise(request, promise) {
        if (!request || !isTimeframeRequestCurrent(request)) return null;
        request.promise = promise;
        syncState();
        return promise;
    }

    function isTimeframeRequestCurrent(request) {
        if (!request) return false;
        var current = state.timeframeRequests[request.period];
        var rootCode = normalizeCode(state.rootData && (state.rootData.stock_code || state.rootData.stock_name));
        return Boolean(
            current
            && current.id === request.id
            && current.code === request.code
            && (!rootCode || rootCode === request.code)
        );
    }

    function mergeTimeframes(payload) {
        if (!state.rootData || !payload || !payload.multi_timeframes) return false;
        state.rootData.multi_timeframes = Object.assign(
            {},
            state.rootData.multi_timeframes || {},
            payload.multi_timeframes || {}
        );
        if (state.viewData && normalizeCode(state.viewData.stock_code) === normalizeCode(state.rootData.stock_code)) {
            state.viewData.multi_timeframes = state.rootData.multi_timeframes;
        }
        syncState();
        return true;
    }

    function failTimeframeLoad(request, error) {
        if (!isTimeframeRequestCurrent(request)) return false;
        syncState();
        return true;
    }

    function finishTimeframeLoad(request) {
        if (!request || !state.timeframeRequests[request.period]) return false;
        if (state.timeframeRequests[request.period].id !== request.id) return false;
        delete state.timeframeRequests[request.period];
        syncState();
        return true;
    }

    return {
        beginAnalysis: beginAnalysis,
        isAnalysisRequestCurrent: isAnalysisRequestCurrent,
        completeAnalysis: completeAnalysis,
        failAnalysis: failAnalysis,
        isAnalysisLoading: function() { return state.analysisLoading; },
        setRootData: setRootData,
        setViewData: setViewData,
        getRootData: getRootData,
        getViewData: getViewData,
        getCurrentChartData: currentChartData,
        setActivePeriod: setActivePeriod,
        getActivePeriod: getActivePeriod,
        setChartPositionView: setChartPositionView,
        getChartPositionView: getChartPositionView,
        getTimeframeRequest: getTimeframeRequest,
        getTimeframePromise: getTimeframePromise,
        beginTimeframeLoad: beginTimeframeLoad,
        attachTimeframePromise: attachTimeframePromise,
        isTimeframeRequestCurrent: isTimeframeRequestCurrent,
        mergeTimeframes: mergeTimeframes,
        failTimeframeLoad: failTimeframeLoad,
        finishTimeframeLoad: finishTimeframeLoad
    };
})();
