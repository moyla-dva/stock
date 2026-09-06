function scanResultNeedsProfile(item) {
    if (!item || !item.code) return false;
    return !item.sector || !item.name || item.name === item.code || !scanConcepts(item).length;
}

function applyStockProfiles(profiles) {
    if (!profiles) return false;
    var changed = false;

    function applyProfile(item) {
        if (!item || !item.code) return;
        var profile = profiles[item.code];
        if (!profile) return;
        if (profile.name && (!item.name || item.name === item.code)) {
            item.name = profile.name;
            changed = true;
        }
        if (profile.sector && !item.sector) {
            item.sector = profile.sector;
            changed = true;
        }
        var concepts = Array.isArray(profile.concepts) ? profile.concepts : [];
        if (concepts.length && !scanConcepts(item).length) {
            item.concepts = concepts;
            changed = true;
        }
    }

    SCAN_POOL_TYPES.forEach(function(scanType) {
        var pool = getScanPool(scanType);
        (pool.results || []).forEach(applyProfile);
    });
    applyProfile(scanWorkspaceState.selectedResult);
    return changed;
}

async function enrichActiveScanProfiles() {
    var pool = getScanPool(scanWorkspaceState.activeType);
    var visibleResults = getVisibleScanResults();
    var results = visibleResults.length ? visibleResults : (pool.results || []);
    var codes = [];
    results.some(function(item) {
        if (!scanResultNeedsProfile(item)) return false;
        if (hasScanProfileRequest(item.code)) return false;
        markScanProfileRequestPending(item.code);
        codes.push(item.code);
        return codes.length >= SCAN_PROFILE_ENRICH_LIMIT;
    });
    if (!codes.length || typeof fetchStockProfiles !== 'function') return;

    try {
        var payload = await fetchStockProfiles(codes);
        if (payload.error) throw new Error(payload.error);
        Object.keys(payload.profiles || {}).forEach(function(code) {
            markScanProfileRequestDone(code);
        });
        if (applyStockProfiles(payload.profiles || {})) {
            renderActiveScanPool();
        }
    } catch (err) {
        codes.forEach(function(code) {
            clearScanProfileRequest(code);
        });
        console.error('股票画像补齐失败:', err);
    }
}
