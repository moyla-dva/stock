import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendAnalysisStoreTest(unittest.TestCase):
    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node 不可用，跳过前端脚本测试")

    def _run_node_script(self, script):
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_analysis_store_rejects_stale_analysis_and_timeframe_requests(self):
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const source = fs.readFileSync({str(ROOT / 'static/js/analysisStore.js')!r}, 'utf8');
            const context = {{ window: {{}}, console }};
            vm.createContext(context);
            vm.runInContext(source, context);
            const store = context.analysisStore;

            const first = store.beginAnalysis('600063');
            const second = store.beginAnalysis('000001');
            assert.strictEqual(store.isAnalysisRequestCurrent(first), false);
            assert.strictEqual(store.completeAnalysis(first, {{ stock_code: '600063' }}), false);
            assert.strictEqual(store.completeAnalysis(second, {{ stock_code: '000001', multi_timeframes: {{}} }}), true);
            assert.strictEqual(store.getRootData().stock_code, '000001');
            assert.strictEqual(store.getCurrentChartData().stock_code, '000001');
            assert.strictEqual(store.getActivePeriod(), 'daily');

            const timeframe = store.beginTimeframeLoad('60m', '000001');
            store.attachTimeframePromise(timeframe, Promise.resolve({{}}));
            assert.strictEqual(store.isTimeframeRequestCurrent(timeframe), true);

            const third = store.beginAnalysis('600063');
            assert.strictEqual(store.isTimeframeRequestCurrent(timeframe), false);
            assert.strictEqual(store.failTimeframeLoad(timeframe, new Error('late response')), false);
            assert.strictEqual(store.finishTimeframeLoad(timeframe), false);
            assert.strictEqual(store.completeAnalysis(third, {{ stock_code: '600063', multi_timeframes: {{}} }}), true);
            assert.strictEqual(store.getRootData().stock_code, '600063');
            """
        )

        self._run_node_script(script)

    def test_analysis_scripts_load_without_legacy_analysis_globals(self):
        scripts = [
            "static/js/api.js",
            "static/js/analysisStore.js",
            "static/js/app.js",
            "static/js/signalPanel.js",
            "static/js/chartMarkers.js",
            "static/js/chartOptions.js",
            "static/js/chartView.js",
            "static/js/scanState.js",
            "static/js/scanStrategyCompare.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            function dummyElement() {{
                return {{
                    innerText: '',
                    textContent: '',
                    disabled: false,
                    title: '',
                    dataset: {{}},
                    style: {{ setProperty() {{}} }},
                    classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
                    setAttribute() {{}},
                    appendChild() {{}},
                    querySelectorAll() {{ return []; }},
                    querySelector() {{ return null; }},
                    addEventListener() {{}}
                }};
            }}
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{
                    getElementById() {{ return dummyElement(); }},
                    querySelectorAll() {{ return []; }},
                    querySelector() {{ return null; }},
                    createElement() {{ return dummyElement(); }},
                    body: {{ setAttribute() {{}} }}
                }},
                echarts: {{
                    init() {{
                        return {{
                            resize() {{}},
                            setOption() {{}},
                            dispatchAction() {{}},
                            on() {{}}
                        }};
                    }}
                }},
                fetch() {{ return Promise.resolve({{ ok: true, json() {{ return Promise.resolve({{}}); }} }}); }},
                URLSearchParams,
                Promise,
                setTimeout(fn) {{ fn(); return 0; }},
                console,
                alert() {{}}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            assert.ok(context.analysisStore);
            assert.strictEqual('lastData' in context, false);
            assert.strictEqual('lastAnalysisData' in context, false);
            assert.strictEqual('activeChartPeriod' in context, false);
            assert.strictEqual('timeframeLoadPromises' in context, false);
            assert.strictEqual('timeframeLoadErrors' in context, false);

            const request = context.analysisStore.beginAnalysis('600063');
            assert.strictEqual(
                context.analysisStore.completeAnalysis(request, {{ stock_code: '600063', multi_timeframes: {{}} }}),
                true
            );
            assert.strictEqual(context.analysisStore.getCurrentChartData().stock_code, '600063');
            assert.strictEqual(context.window.lastData, undefined);
            """
        )

        self._run_node_script(script)

    def test_late_timeframe_response_does_not_override_latest_period_selection(self):
        scripts = [
            "static/js/analysisStore.js",
            "static/js/chartView.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            function dummyElement() {{
                return {{
                    disabled: false,
                    title: '',
                    classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
                    setAttribute() {{}}
                }};
            }}
            const context = {{
                window: {{}},
                document: {{
                    getElementById() {{ return dummyElement(); }}
                }},
                echarts: {{
                    init() {{
                        return {{
                            resize() {{}},
                            setOption() {{}},
                            dispatchAction() {{}},
                            on() {{}}
                        }};
                    }}
                }},
                Promise,
                console,
                normalizeChartStockCode(code) {{
                    const match = String(code || '').match(/\\d{{6}}/);
                    return match ? match[0] : String(code || '').trim();
                }},
                setChartState() {{}},
                setText() {{}}
            }};
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            (async () => {{
                const request = context.analysisStore.beginAnalysis('600063');
                context.analysisStore.completeAnalysis(request, {{
                    stock_code: '600063',
                    stock_name: '示例股票',
                    dates: ['2026-01-01'],
                    k_data: [[1, 1, 1, 1]],
                    mark_points_v2: [],
                    event_stats: {{ v2: {{ by_signal: {{}} }} }},
                    multi_timeframes: {{
                        daily: {{ period: '1d', available: true }},
                        hour_1: {{ period: '60m', available: true }},
                        hour_4: {{ period: '4h', available: true }}
                    }}
                }});

                const resolvers = {{}};
                const renders = [];
                context.fetchAnalysisTimeframes = function(code, period) {{
                    return new Promise(resolve => {{
                        resolvers[period] = resolve;
                    }});
                }};
                context.renderChart = function(data) {{
                    renders.push({{
                        period: context.analysisStore.getActivePeriod(),
                        code: data.stock_code
                    }});
                }};

                context.setChartPeriod('60m');
                assert.strictEqual(context.analysisStore.getActivePeriod(), '60m');
                context.setChartPeriod('4h');
                assert.strictEqual(context.analysisStore.getActivePeriod(), '4h');

                resolvers['60m']({{
                    multi_timeframes: {{
                        hour_1: {{
                            period: '60m',
                            available: true,
                            chart: {{ dates: ['2026-01-01'], k_data: [], mark_points_v2: [] }}
                        }}
                    }}
                }});
                await Promise.resolve();
                await Promise.resolve();
                assert.strictEqual(context.analysisStore.getActivePeriod(), '4h');
                assert.strictEqual(renders.length, 0);

                resolvers['4h']({{
                    multi_timeframes: {{
                        hour_4: {{
                            period: '4h',
                            available: true,
                            chart: {{ dates: ['2026-01-01'], k_data: [], mark_points_v2: [] }}
                        }}
                    }}
                }});
                await Promise.resolve();
                await Promise.resolve();
                assert.strictEqual(context.analysisStore.getActivePeriod(), '4h');
                assert.strictEqual(renders.length, 1);
                assert.strictEqual(renders[0].period, '4h');
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_chart_position_view_relabels_risk_events_without_losing_source_fact(self):
        scripts = [
            "static/js/analysisStore.js",
            "static/js/signalPanel.js",
            "static/js/chartMarkers.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {{
                window: {{}},
                console,
                signalMeta: {{}},
                activeSignalKeys: {{}}
            }};
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            const sellPoint = {{
                signalKey: 'v2_exit_gate_sell',
                signalLabel: 'C风',
                name: 'V2防守离场',
                signalCategory: 'exit',
                markerRole: 'sell',
                markerReason: 'trailing_stop_break',
                date: '2026-08-24',
                coord: ['2026-08-24', 10],
                price: 10,
                reason: '跌破防守线'
            }};
            const bottomPoint = {{
                signalKey: 'v2_structure_candidate',
                signalLabel: 'C候',
                name: 'V2结构候选',
                signalCategory: 'bottom',
                markerRole: 'observe',
                date: '2026-08-24',
                coord: ['2026-08-24', 9],
                price: 9,
                reason: '双底分型低点抬高'
            }};
            const scalePoint = {{
                signalKey: 'v2_strong_resistance_scale_out',
                signalLabel: 'C盈',
                name: 'V2强阻减仓',
                signalCategory: 'risk',
                markerRole: 'scale_out',
                date: '2026-09-01',
                coord: ['2026-09-01', 12],
                price: 12,
                reason: '触及核心强阻'
            }};

            const annotated = context.annotateChartDisplayContext([sellPoint, bottomPoint, scalePoint]);
            assert.strictEqual(context.getChartPositionView(), 'flat');
            assert.strictEqual(context.getPointMeta(annotated[0]).label, '候?');
            assert.strictEqual(context.getPointMeta(annotated[0]).name, '破位修复观察');
            assert.strictEqual(context.getPointMeta(annotated[0]).displaySource, 'C风 V2防守离场');
            assert.strictEqual(context.chartMarkerDisplayRole(annotated[0], context.getPointMeta(annotated[0])), 'scale_out');
            assert.strictEqual(context.getPointMeta(annotated[2]).label, '阻');

            const soloSell = context.annotateChartDisplayContext([sellPoint])[0];
            assert.strictEqual(context.getPointMeta(soloSell).label, '破');

            context.analysisStore.setChartPositionView('position');
            assert.strictEqual(context.getPointMeta(annotated[0]).label, '卖');
            assert.strictEqual(context.getPointMeta(annotated[2]).label, '减');
            assert.strictEqual(context.getPointMeta({{
                signalKey: 'v2_top_fractal_observe',
                signalLabel: 'C研',
                name: 'V2顶分型观察',
                signalCategory: 'top',
                markerRole: 'observe',
                date: '2026-09-02'
            }}).label, '撤');
            assert.strictEqual(context.getPointMeta({{
                signalKey: 'v2_ignition',
                signalLabel: 'C爆',
                name: 'V2起爆触发',
                signalCategory: 'entry',
                markerRole: 'buy',
                date: '2026-09-03'
            }}).label, '持');
            """
        )

        self._run_node_script(script)

    def test_scan_strategy_compare_surfaces_pending_trigger_plan(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanStrategyCompare.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{ querySelectorAll() {{ return []; }} }},
                console
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            const item = {{
                v2_signal: 'C候',
                candidate_display_label: '待触',
                candidate_substate_label: '强修复待触发',
                candidate_trigger_plan: {{
                    status: 'pending_trigger',
                    summary: '强修复线索已出现，但当前仍不是买点。',
                    confirmation_label: '右侧确认价',
                    confirmation_price: 10.1,
                    invalidation_price: 8.51,
                    distance_to_confirmation_pct: 10.87,
                    intraday_rule: '盘中只有放量站上右侧确认价 10.10 才进入触发复核。',
                    next_session_rule: '次日收盘有效突破 10.10 后，转入 `触`。',
                    failure_rule: '跌破失效价 8.51 后，本轮候选失效。',
                    missing_confirmations: ['突破确认价', 'Plan Gate 校验']
                }},
                v2_state_model: {{
                    signal: 'C候',
                    signal_name: '结构候选',
                    permission: 'structure_only',
                    permission_label: '结构观察',
                    candidate_trigger_plan: null,
                    requires_trade_plan: false,
                    requires_stop_loss: false,
                    facts: {{}}
                }}
            }};

            const triggerText = context.scanV2CandidateTriggerText(item.candidate_trigger_plan);
            assert.strictEqual(triggerText, '右侧确认价 10.10 / 差 10.87%');
            const chips = context.scanV2CardEvidenceItems(item);
            assert.ok(chips.some(chip => chip.label === '触发' && chip.value === triggerText));
            assert.ok(chips.some(chip => chip.label === '失效' && chip.value === '失效 8.51'));
            const deltaItems = context.scanStrategyDeltaItems(item);
            assert.ok(deltaItems.some(row => row.label === '待触计划' && row.value.includes('不是买点')));
            assert.ok(deltaItems.some(row => row.label === '盘中/次日' && row.value.includes('盘中只有放量站上')));
            """
        )

        self._run_node_script(script)

    def test_scan_strategy_compare_surfaces_legacy_experience_as_material(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanStrategyCompare.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{ querySelectorAll() {{ return []; }} }},
                console
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            const text = context.scanV2FactsText({{
                facts: {{
                    source: 'c_signal_v2_p19_repair_watch_facts',
                    structure: {{}},
                    trigger: {{}},
                    macro_tide: {{ permission: 'watch_only', label: '观察' }},
                    target_structure: {{}},
                    exit_gate: {{}},
                    legacy_experience: {{
                        available: true,
                        grants_permission: false,
                        items: [
                            {{ key: 'legacy_low_risk_pullback', label: '旧C低风险回踩' }},
                            {{ key: 'legacy_bottom_repair_hint', label: '旧C底部修复' }}
                        ]
                    }},
                    v2_scores: {{
                        research_score: 12,
                        structure_score: 34,
                        trigger_quality: 0,
                        execution_risk: 3
                    }}
                }}
            }});

            assert.ok(text.includes('旧C低风险回踩素材'));
            assert.ok(text.includes('旧C底部修复素材'));
            assert.ok(text.includes('大周期观察'));
            assert.ok(text.includes('研究12 / 结构34 / 触发0 / 风险3'));
            """
        )

        self._run_node_script(script)

    def test_force_scan_poll_keeps_existing_results_when_results_are_omitted(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanWorkspaceStore.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{ querySelectorAll() {{ return []; }} }},
                console,
                setTimeout(fn) {{ fn(); return 0; }}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            context.scanWorkspaceState.pools.opportunity = {{
                title: '参与候选',
                count: 3,
                loaded_count: 2,
                max_items: 120,
                has_more: true,
                results: [
                    {{ code: '600001', event_date: '2026-05-11' }},
                    {{ code: '600002', event_date: '2026-05-11' }}
                ]
            }};

            context.applyRunningScanJobToWorkspace({{
                scan_type: 'opportunity',
                refresh_policy: 'force',
                matched: 1,
                results: [],
                results_omitted: true
            }});

            const pool = context.scanWorkspaceState.pools.opportunity;
            assert.strictEqual(pool.count, 1);
            assert.deepStrictEqual(pool.results.map(item => item.code), ['600001', '600002']);
            assert.strictEqual(pool.loaded_count, 2);
            """
        )

        self._run_node_script(script)

    def test_candidate_detail_requests_event_date_and_does_not_fallback_to_wrong_result(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanWorkspaceStore.js",
            "static/js/scanSelection.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{
                    getElementById() {{ return {{ value: '', textContent: '', classList: {{ add() {{}}, remove() {{}} }} }}; }},
                    querySelectorAll() {{ return []; }},
                    querySelector() {{ return null; }}
                }},
                console,
                setTimeout(fn) {{ fn(); return 0; }},
                pendingFocusDate: null,
                renderScanSelection() {{}},
                renderActiveScanPool() {{}}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            vm.runInContext(`
                var capturedDetailOptions = null;
                fetchScanCandidateDetail = async function(options) {{
                    capturedDetailOptions = options;
                    return {{
                        results: [
                            {{ code: '600001', event_date: '2026-05-12', scan_type: 'opportunity', name: 'wrong day' }}
                        ]
                    }};
                }};
            `, context);

            context.scanWorkspaceState.selectedResult = {{
                code: '600001',
                date: '2026-05-11',
                event_date: '2026-05-11',
                scan_type: 'opportunity',
                _scan_type: 'opportunity',
                _compact: true
            }};

            async function main() {{
                await context.loadScanCandidateDetailForSelection();
                assert.strictEqual(context.capturedDetailOptions.eventDate, '2026-05-11');
                assert.strictEqual(context.scanWorkspaceState.selectedResult._compact, false);
                assert.strictEqual(context.scanWorkspaceState.selectedResult._detail_loading, false);
                assert.strictEqual(context.scanWorkspaceState.selectedResult._detail_error, '未找到完整详情');
            }}
            main().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)


if __name__ == "__main__":
    unittest.main()
