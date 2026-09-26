import os
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendAnalysisStoreTest(unittest.TestCase):
    def setUp(self):
        if shutil.which("node") is None:
            if os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}:
                self.fail("node is required for frontend tests in CI")
            self.skipTest("node 不可用，跳过前端脚本测试")

    def _run_node_script(self, script):
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_daily_chart_header_shows_bar_state_date_and_source(self):
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const labels = {{}};
            const context = {{
                window: {{}},
                document: {{ getElementById() {{ return {{}}; }} }},
                echarts: {{ init() {{ return {{ on() {{}}, resize() {{}}, setOption() {{}} }}; }} }},
                activeScanChartFocus: null,
                signalMode: 'composite',
                setText(id, value) {{ labels[id] = value; }},
                getModeText() {{ return '综合研判'; }}
            }};
            vm.createContext(context);
            vm.runInContext(fs.readFileSync('static/js/chartView.js', 'utf8'), context);
            context.updateChartHeader({{
                stock_code: '600001',
                chart_period: 'daily',
                data_identity: {{
                    bar_state: 'preview',
                    data_source: 'tencent_direct+tencent_realtime'
                }}
            }}, ['2026-09-22', '2026-09-23']);

            assert.ok(labels['data-window'].includes('2026-09-23'));
            assert.ok(labels['data-window'].includes('盘中实时'));
            assert.ok(labels['data-window'].includes('腾讯实时行情'));

            context.updateChartHeader({{
                stock_code: '600001',
                chart_period: '60m',
                data_identity: {{ bar_state: 'preview', data_source: 'tencent_realtime' }}
            }}, ['2026-09-23 10:00']);
            assert.ok(!labels['data-window'].includes('盘中实时'));
            """
        )

        self._run_node_script(script)

    def test_single_stock_stable_read_model_is_default_with_legacy_fallback(self):
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const urls = [];
            const stable = {{
                schema_version: 2,
                identity: {{
                    code: '600001', as_of: '2026-09-22', bar_state: 'closed',
                    data_source: 'tencent_qfq', data_revision: 'sha256:data',
                    generated_at: '2026-09-22T16:00:00+08:00', calendar_id: 'XSHG'
                }},
                profile: {{
                    display_name: '样本A (600001)', sector: '半导体',
                    concepts: ['存储芯片'], tag_profile: {{confidence: 0.9}}
                }},
                market_data: {{latest_at: '2026-09-22', row_count: 2}},
                chart: {{
                    dates: ['2026-09-21', '2026-09-22'],
                    candles: [[10, 10.2, 9.9, 10.3], [10.2, 10.5, 10.1, 10.6]],
                    candle_fields: ['open', 'close', 'low', 'high'],
                    series: {{
                        ma20: [9.8, 9.9], vwap: [10, 10.3], custom: [0.1, 0.2],
                        dif: [0.01, 0.02], dea: [0, 0.01], macd: [0.02, 0.02],
                        bull_power: [0.1, 0.2], bear_power: [-0.1, -0.05], williams_r: [50, 40]
                    }}
                }},
                signal_observations: {{
                    events: [{{date: '2026-09-22', signalCode: 'v2_breakout'}}],
                    event_lookback: 60,
                    score_summary: {{setup: 3}},
                    definitions: {{v2_breakout: {{label: 'C突'}}}}
                }},
                current_state: {{state: 'trigger_plan_ready'}},
                conditional_plan: {{status: 'ready'}},
                timeframes: {{daily: {{available: true}}}},
                event_study: {{results: {{v2: {{horizon: 5}}}}}},
                data_quality: {{cache_status: 'hit', refresh_requested: true}}
            }};
            const context = {{
                window: {{location: {{search: ''}}}},
                URLSearchParams,
                Promise,
                AbortSignal: {{timeout() {{ return null; }}}},
                fetch(url) {{
                    urls.push(String(url));
                    return Promise.resolve({{ok: true, json() {{ return Promise.resolve(stable); }}}});
                }}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            for (const file of ['static/js/api.js', 'static/js/singleStockReadModelAdapter.js']) {{
                vm.runInContext(fs.readFileSync(file, 'utf8'), context, {{filename: file}});
            }}

            (async () => {{
                const payload = await context.analyzeStockData('600001', {{forceRefresh: true}});
                assert.strictEqual(urls.length, 1);
                assert.ok(urls[0].startsWith('/api/single_stock_analysis?'));
                assert.ok(urls[0].includes('refresh=1'));
                assert.strictEqual(payload.stock_code, '600001');
                assert.deepStrictEqual(Array.from(payload.dates), ['2026-09-21', '2026-09-22']);
                assert.deepStrictEqual(Array.from(payload.k_data[1]), [10.2, 10.5, 10.1, 10.6]);
                assert.strictEqual(payload.mark_points_v2[0].signalCode, 'v2_breakout');
                assert.strictEqual(payload.c_signal_v2_state.state, 'trigger_plan_ready');
                assert.strictEqual(payload.trade_plan.status, 'ready');
                assert.strictEqual(payload.data_identity.data_source, 'tencent_qfq');
                assert.strictEqual(payload._single_stock_read_model_source, 'single_stock_analysis_v2');

                context.window.location.search = '?single_stock_source=legacy';
                await context.analyzeStockData('600001', {{forceRefresh: true}});
                assert.strictEqual(urls.length, 2);
                assert.ok(urls[1].startsWith('/api/analyze?'));
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_request_json_surfaces_structured_api_error_message(self):
        script = textwrap.dedent(
            """
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {
                Promise,
                AbortSignal: {},
                fetch() {
                    return Promise.resolve({
                        ok: false,
                        status: 503,
                        text() {
                            return Promise.resolve(JSON.stringify({
                                error: {
                                    code: 'upstream_unavailable',
                                    message: '行情源暂不可用',
                                    retryable: true
                                }
                            }));
                        }
                    });
                }
            };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync('static/js/api.js', 'utf8'), context);

            context.requestJson('/api/single_stock_analysis', {disableTimeout: true})
                .then(() => { throw new Error('expected request failure'); })
                .catch(error => {
                    assert.ok(error.message.includes('503'));
                    assert.ok(error.message.includes('upstream_unavailable'));
                    assert.ok(error.message.includes('行情源暂不可用'));
                    assert.strictEqual(error.message.includes('{"error"'), false);
                    assert.strictEqual(error.status, 503);
                    assert.strictEqual(error.code, 'upstream_unavailable');
                    assert.strictEqual(error.retryable, true);
                })
                .catch(error => {
                    console.error(error);
                    process.exit(1);
                });
            """
        )

        self._run_node_script(script)

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

    def test_scan_job_formats_market_data_coverage_without_claiming_suspension(self):
        script = textwrap.dedent(
            """
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {};
            vm.createContext(context);
            vm.runInContext(fs.readFileSync('static/js/scanJobFormat.js', 'utf8'), context);
            const text = context.formatMarketDataCoverage({
                universe_as_of: '2026-09-23',
                data_coverage: {
                    checked_count: 4,
                    current_session_closed_count: 1,
                    stale_or_no_new_bar_count: 2,
                    no_data_count: 1
                }
            });
            assert.ok(text.includes('当日收盘 1'));
            assert.ok(text.includes('旧数据/无新K线 2'));
            assert.ok(text.includes('无数据/源未返回 1'));
            assert.ok(text.includes('未更新不等于停牌'));
            const detailed = context.formatMarketDataCoverage({
                data_coverage: {
                    checked_count: 3,
                    no_data_count: 2,
                    provider_empty_count: 1,
                    provider_error_count: 1,
                    stale_cache_count: 1
                }
            });
            assert.ok(detailed.includes('源无数据 1'));
            assert.ok(detailed.includes('源请求失败 1'));
            assert.ok(detailed.includes('陈旧缓存 1'));
            assert.ok(!detailed.includes('无数据/源未返回'));
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

    def test_new_analysis_aborts_previous_inflight_request(self):
        scripts = [
            "static/js/api.js",
            "static/js/analysisStore.js",
            "static/js/app.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');

            let codeValue = '600001';
            const button = {{ disabled: false }};
            const alerts = [];
            const fetchCalls = [];

            function dummyElement(id) {{
                if (id === 'stock-code') return {{ value: codeValue }};
                if (id === 'btn-analyze') return button;
                return {{
                    innerText: '',
                    textContent: '',
                    disabled: false,
                    classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
                    setAttribute() {{}}
                }};
            }}

            const context = {{
                window: {{}},
                document: {{
                    getElementById(id) {{ return dummyElement(id); }},
                    querySelectorAll() {{ return []; }},
                    querySelector() {{ return null; }},
                    body: {{ setAttribute() {{}} }}
                }},
                AbortController,
                AbortSignal,
                DOMException,
                URLSearchParams,
                Promise,
                console,
                alert(message) {{ alerts.push(message); }},
                renderChart() {{}},
                updateScanButtonLabel() {{}}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            context.fetch = function(url, options) {{
                const call = {{ url, options, aborted: false }};
                fetchCalls.push(call);
                if (fetchCalls.length === 1) {{
                    return new Promise((resolve, reject) => {{
                        options.signal.addEventListener('abort', () => {{
                            call.aborted = true;
                            reject(new DOMException('aborted', 'AbortError'));
                        }});
                    }});
                }}
                return Promise.resolve({{
                    ok: true,
                    json() {{
                        return Promise.resolve({{
                            stock_code: '000002',
                            stock_name: '第二只',
                            dates: [],
                            k_data: [],
                            mark_points_v2: [],
                            event_stats: {{ v2: {{ by_signal: {{}} }} }},
                            multi_timeframes: {{}}
                        }});
                    }}
                }});
            }};

            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            (async () => {{
                const first = context.analyzeStock();
                codeValue = '000002';
                const second = context.analyzeStock();
                await Promise.all([first, second]);

                assert.strictEqual(fetchCalls.length, 2);
                assert.ok(fetchCalls[0].url.includes('refresh=1'));
                assert.ok(fetchCalls[1].url.includes('refresh=1'));
                assert.strictEqual(fetchCalls[0].aborted, true);
                assert.strictEqual(fetchCalls[0].options.signal.aborted, true);
                assert.deepStrictEqual(alerts, []);
                assert.strictEqual(context.analysisStore.getRootData().stock_code, '000002');
                assert.strictEqual(button.disabled, false);
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_stock_code_input_auto_refreshes_realtime_quote(self):
        scripts = [
            "static/js/api.js",
            "static/js/analysisStore.js",
            "static/js/app.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');

            let codeValue = '60000';
            const input = {{ value: codeValue }};
            const fetchCalls = [];
            const workspaceState = {{}};

            function dummyElement(id) {{
                if (id === 'stock-code') return input;
                return {{
                    innerText: '',
                    textContent: '',
                    disabled: false,
                    classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
                    setAttribute() {{}}
                }};
            }}

            const context = {{
                window: {{}},
                document: {{
                    getElementById(id) {{ return dummyElement(id); }},
                    querySelectorAll() {{ return []; }},
                    querySelector() {{ return null; }},
                    body: {{ setAttribute(key, value) {{ workspaceState[key] = value; }} }}
                }},
                AbortController,
                AbortSignal,
                DOMException,
                URLSearchParams,
                Promise,
                console,
                setTimeout,
                clearTimeout,
                alert() {{}},
                renderChart() {{}},
                updateScanButtonLabel() {{}}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            context.fetch = function(url) {{
                fetchCalls.push(url);
                return Promise.resolve({{
                    ok: true,
                    json() {{
                        return Promise.resolve({{
                            stock_code: input.value,
                            stock_name: '自动刷新',
                            dates: [],
                            k_data: [],
                            mark_points_v2: [],
                            event_stats: {{ v2: {{ by_signal: {{}} }} }},
                            multi_timeframes: {{}}
                        }});
                    }}
                }});
            }};

            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            (async () => {{
                context.window.onload();
                assert.strictEqual(fetchCalls.length, 0);

                context.handleStockCodeInput({{ target: input }});
                await new Promise(resolve => setTimeout(resolve, 650));
                assert.strictEqual(fetchCalls.length, 0);

                input.value = '600001';
                context.handleStockCodeInput({{ target: input }});
                await new Promise(resolve => setTimeout(resolve, 650));
                assert.strictEqual(fetchCalls.length, 1);
                assert.ok(fetchCalls[0].includes('code=600001'));
                assert.ok(fetchCalls[0].includes('refresh=1'));
                assert.strictEqual(workspaceState['data-workspace'], 'analysis');
                assert.strictEqual(workspaceState['data-desk'], 'analysis');

                context.handleStockCodeInput({{ target: input }});
                await new Promise(resolve => setTimeout(resolve, 650));
                assert.strictEqual(fetchCalls.length, 1);

                input.value = '000002';
                context.setWorkspaceView('candidates');
                context.handleKeyPress({{ key: 'Enter', target: input }});
                await new Promise(resolve => setTimeout(resolve, 0));
                assert.strictEqual(fetchCalls.length, 2);
                assert.ok(fetchCalls[1].includes('code=000002'));
                assert.ok(fetchCalls[1].includes('refresh=1'));
                assert.strictEqual(workspaceState['data-workspace'], 'analysis');
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
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
                name: 'V2强阻保护',
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
            assert.strictEqual(context.getPointMeta(annotated[0]).label, '离');
            assert.strictEqual(context.getPointMeta(annotated[2]).label, '护');
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
            }}).label, '跟');
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

    def test_scan_job_poll_retries_transient_status_failure(self):
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');

            const timers = [];
            const statuses = [];
            const rendered = [];
            let fetchCalls = 0;

            const context = {{
                window: {{}},
                document: {{
                    getElementById() {{ return {{ innerHTML: '' }}; }}
                }},
                console,
                setTimeout(fn, delay) {{
                    timers.push({{ fn, delay }});
                    return timers.length;
                }},
                clearTimeout() {{}},
                fetchScanJob(jobId) {{
                    fetchCalls += 1;
                    if (fetchCalls === 1) return Promise.reject(new Error('network blink'));
                    return Promise.resolve({{ id: jobId, scan_type: 'opportunity', status: 'running' }});
                }},
                renderScanJob(job) {{ rendered.push(job.status); }},
                isScanJobTerminal(status) {{ return ['completed', 'failed', 'cancelled', 'interrupted'].includes(status); }},
                disableScanButtons() {{ throw new Error('transient failure should not unlock buttons'); }},
                refreshScanActionState() {{}},
                updateScanButtonLabel() {{}},
                loadScanWorkspace() {{ return Promise.resolve(true); }},
                loadScanJobHistory() {{ return Promise.resolve(true); }},
                setScanStatus(message) {{ statuses.push(message); }},
                showScanError() {{ throw new Error('transient failure should not render terminal error'); }},
                openScanTaskWorkspace() {{}}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            const source = fs.readFileSync({str(ROOT / 'static/js/scanJobs.js')!r}, 'utf8');
            vm.runInContext(source, context, {{ filename: 'static/js/scanJobs.js' }});
            vm.runInContext("activeScanJobId = 'job1'; activeScanJobType = 'opportunity';", context);

            (async () => {{
                await context.pollActiveScanJob();
                assert.strictEqual(fetchCalls, 1);
                assert.strictEqual(statuses[0], '任务状态暂时不可用，重试中 1/3');
                assert.strictEqual(timers.length, 1);
                assert.strictEqual(timers[0].delay, 900);

                const retry = timers.shift();
                await retry.fn();
                assert.strictEqual(fetchCalls, 2);
                assert.deepStrictEqual(rendered, ['running']);
                assert.strictEqual(timers.length, 1);
                assert.strictEqual(timers[0].delay, 900);
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_scan_search_filter_debounces_render_and_clears_on_explicit_filter(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanFilters.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');

            let nextTimerId = 1;
            const timers = {{}};
            let renderCount = 0;
            let enrichCount = 0;

            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{
                    getElementById() {{ return null; }},
                    querySelectorAll() {{ return []; }}
                }},
                console,
                setTimeout(fn, delay) {{
                    const id = nextTimerId++;
                    timers[id] = {{ fn, delay, cleared: false }};
                    return id;
                }},
                clearTimeout(id) {{
                    if (timers[id]) timers[id].cleared = true;
                }},
                renderActiveScanPool() {{ renderCount += 1; }},
                enrichActiveScanProfiles() {{ enrichCount += 1; }},
                renderScanRecommendation() {{}},
                renderScanEntryModelToggle() {{}},
                isScanV2StrategyView() {{ return true; }},
                scanFirstText(item, keys) {{
                    for (const key of keys || []) {{
                        if (item && item[key]) return item[key];
                    }}
                    return '';
                }}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            function runActiveTimers() {{
                Object.values(timers).forEach(timer => {{
                    if (!timer.cleared) {{
                        timer.cleared = true;
                        timer.fn();
                    }}
                }});
            }}

            context.setScanFilterQuery('半');
            context.setScanFilterQuery('半导体');
            assert.strictEqual(context.scanWorkspaceState.filters.query, '半导体');
            assert.strictEqual(renderCount, 0);

            runActiveTimers();
            assert.strictEqual(renderCount, 1);
            assert.strictEqual(enrichCount, 1);

            context.setScanFilterQuery('储能');
            context.setScanSectorFilter('电力设备');
            assert.strictEqual(renderCount, 2);
            runActiveTimers();
            assert.strictEqual(renderCount, 2);
            """
        )

        self._run_node_script(script)

    def test_candidate_selection_is_remembered_per_pool_and_snapshot(self):
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
                window: {{ localStorage: {{ getItem() {{ return null; }}, setItem() {{}} }} }},
                normalizeFilterText(value) {{ return String(value || '').trim().toLowerCase(); }}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                vm.runInContext(fs.readFileSync(file, 'utf8'), context, {{ filename: file }});
            }}

            context.scanWorkspaceState.latest_snapshot_day = '2026-09-24';
            const risk = {{
                code: '002410', event_date: '2026-09-24', signal_key: 'v2_risk_stop_loss',
                v2_signal: 'C风', scan_type: 'risk', _scan_type: 'risk'
            }};
            const opportunity = {{
                code: '300829', event_date: '2026-09-24', signal_key: 'v2_breakout',
                v2_signal: 'C突', scan_type: 'opportunity', _scan_type: 'opportunity'
            }};

            context.rememberScanPoolSelection(risk, 'risk');
            context.rememberScanPoolSelection(opportunity, 'opportunity');
            assert.strictEqual(
                context.findRememberedScanPoolSelection([{{ code: '600001' }}, opportunity], 'opportunity').code,
                '300829'
            );
            assert.strictEqual(
                context.findRememberedScanPoolSelection([risk], 'risk').code,
                '002410'
            );

            context.scanWorkspaceState.latest_snapshot_day = '2026-09-23';
            assert.strictEqual(context.findRememberedScanPoolSelection([risk], 'risk'), null);
            """
        )

        self._run_node_script(script)

    def test_switching_candidate_pools_restores_the_last_visible_selection(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanWorkspaceStore.js",
            "static/js/scanView.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const scope = {{ textContent: '' }};
            const elements = {{
                'scan-list': {{ innerHTML: '' }},
                'scan-result-panel': {{ classList: {{ add() {{}} }}, querySelector() {{ return scope; }} }},
                'market-results-label': {{ textContent: '' }},
                'market-results-heading': {{ textContent: '' }}
            }};
            const context = {{
                window: {{ localStorage: {{ getItem() {{ return null; }}, setItem() {{}} }} }},
                document: {{ getElementById(id) {{ return elements[id] || null; }} }},
                normalizeFilterText(value) {{ return String(value || '').trim().toLowerCase(); }},
                getActiveWorkspaceView() {{ return 'candidates'; }},
                updateScanButtonLabel() {{}},
                renderScanFilters() {{}},
                getVisibleScanResults() {{ return context.getScanPool(context.scanWorkspaceState.activeType).results; }},
                isSelectedScanResult(item) {{
                    const selected = context.scanWorkspaceState.selectedResult;
                    return Boolean(selected && item.code === selected.code
                        && (item._scan_type || item.scan_type) === (selected._scan_type || selected.scan_type));
                }},
                isPreviewScanResult() {{ return false; }},
                renderCandidateDeskBrief() {{}},
                renderScanResults() {{}},
                renderScanCandidateContext() {{}},
                renderScanSelection() {{}},
                loadScanCandidateDetailForSelection() {{}}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                vm.runInContext(fs.readFileSync(file, 'utf8'), context, {{ filename: file }});
            }}

            const risk = {{ code: '002410', event_date: '2026-09-24', signal_key: 'v2_risk_stop_loss', _scan_type: 'risk' }};
            const opportunityFirst = {{ code: '600001', event_date: '2026-09-24', signal_key: 'v2_pullback', _scan_type: 'opportunity' }};
            const opportunitySaved = {{ code: '300829', event_date: '2026-09-24', signal_key: 'v2_breakout', _scan_type: 'opportunity' }};
            context.scanWorkspaceState.latest_snapshot_day = '2026-09-24';
            context.scanWorkspaceState.pools = {{
                risk: {{ count: 1, loaded_count: 1, results: [risk] }},
                opportunity: {{ count: 2, loaded_count: 2, results: [opportunityFirst, opportunitySaved] }}
            }};
            context.scanWorkspaceState.selectedResult = Object.assign({{}}, risk);
            context.setActiveScanType('risk');
            context.renderActiveScanPool();

            context.rememberScanPoolSelection(opportunitySaved, 'opportunity');
            context.setActiveScanType('opportunity');
            context.renderActiveScanPool();
            assert.strictEqual(context.scanWorkspaceState.selectedResult.code, '300829');

            context.setActiveScanType('risk');
            context.renderActiveScanPool();
            assert.strictEqual(context.scanWorkspaceState.selectedResult.code, '002410');
            """
        )

        self._run_node_script(script)

    def test_sqlite_candidate_summary_adapter_builds_contextual_workspace(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanExplain.js",
            "static/js/scanReadModelAdapter.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const calls = [];
            const rows = {{
                opportunity: {{
                    code: '600001', name: '样本股', pool: 'opportunity',
                    event_date: '2026-09-24', as_of: '2026-09-24', snapshot_day: '20260924',
                    signal_key: 'v2_pullback', signal_label: 'C回', state: 'entry_pullback',
                    permission: 'pullback_allowed', plan_status: 'ready', price: 12.3,
                    priority_score: 176.6, final_score: 23, confirm_score: 3,
                    risk_score: 1, reason_summary: '计划闸门通过', reason_tags: ['plan_ready', 'c_pullback'],
                    missing_confirmations: [], concepts: ['人工智能'], sector: '软件服务',
                    requires_trade_plan: true, requires_stop_loss: true,
                    strategy_status: 'current', strategy_version: '2026.09.20.1',
                    rank_context: {{ priority_score: 604.8, priority_group: 'trade_ready', final_score: 56.7, sector_score: 80, concept_score: 70 }}
                }},
                risk: null,
                bottom_div: null
            }};
            const context = {{
                window: {{ location: {{ search: '' }} }},
                URLSearchParams,
                Promise,
                requestJson(url) {{
                    const parsed = new URL(url, 'http://local');
                    const type = parsed.searchParams.get('scan_type');
                    calls.push(parsed);
                    return Promise.resolve({{
                        source: 'sqlite_index', scan_type: type, results: rows[type] ? [rows[type]] : [],
                        count: rows[type] ? 1 : 0, loaded_count: rows[type] ? 1 : 0,
                        has_more: false, limit: 120, latest_snapshot_day: '2026-09-24',
                        latest_data_date: '2026-09-24', history_snapshot_day: '', pool_count: rows[type] ? 1 : 0,
                        ranking: {{ mode: 'contextual', context_applied: true, context_revision: 'sha256:test' }},
                        index_health: {{ index_complete: true, valid_snapshot_count: 103437 }}
                    }});
                }}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                vm.runInContext(fs.readFileSync(file, 'utf8'), context, {{ filename: file }});
            }}

            (async () => {{
                assert.strictEqual(context.shouldUseScanIndexRead(), true);
                const workspace = await context.fetchScanIndexWorkspace({{limit: 120, activeType: 'opportunity'}});
                assert.strictEqual(workspace.read_source, 'sqlite_index');
                assert.strictEqual(workspace.pools.opportunity.count, 1);
                assert.strictEqual(workspace.pools.risk.count, 0);
                const item = workspace.pools.opportunity.results[0];
                assert.strictEqual(item.v2_priority_score, 604.8);
                assert.strictEqual(item.v2_priority_group, 'trade_ready');
                assert.strictEqual(item.v2_state_model.v2_permission_model.plan_gate.status, 'ready');
                assert.strictEqual(item._compact, true);
                assert.ok(context.buildScanExplanation(item).headline.includes('SQLite 候选摘要'));
                assert.ok(!context.buildScanExplanation(item).summary.includes('旧结果'));
                assert.strictEqual(calls.length, 3);
                assert.ok(calls.every(url => url.searchParams.get('rank_mode') === 'contextual'));

                calls.length = 0;
                const page = await context.fetchScanIndexCandidatePage({{
                    scanType: 'opportunity', reason: 'plan_ready', offset: 120, limit: 120
                }});
                assert.strictEqual(page.results[0].code, '600001');
                assert.strictEqual(calls[0].searchParams.get('reason'), 'plan_ready');
                assert.strictEqual(calls[0].searchParams.get('offset'), '120');

                context.window.location.search = '?candidate_source=json';
                assert.strictEqual(context.shouldUseScanIndexRead(), false);
                context.window.location.search = '';
                context.scanWorkspaceState.readSourceOverride = 'json';
                assert.strictEqual(context.shouldUseScanIndexRead(), false);
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_sqlite_candidate_detail_is_validated_and_mapped_to_workspace_item(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanExplain.js",
            "static/js/scanReadModelAdapter.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {{
                window: {{ location: {{ search: '?candidate_source=sqlite' }} }},
                URLSearchParams,
                Promise,
                scanWorkspaceState: {{ readSourceOverride: '' }},
                requestJson(url) {{
                    assert.ok(url.includes('/api/scan_index/candidates/600001?'));
                    return Promise.resolve({{
                        schema_version: 2,
                        summary: {{
                            code: '600001', pool: 'opportunity', name: '样本股', sector: '半导体',
                            concepts: ['AI芯片'], event_date: '2026-09-24', snapshot_day: '20260924',
                            snapshot_revision: 'sha256:test', signal_key: 'v2_breakout', signal_label: 'C突',
                            state: 'entry_breakout', permission: 'breakout_allowed', plan_status: 'ready',
                            price: 12.3, invalidation_price: 11.8, missing_confirmations: [],
                            reason_summary: '结构通过', requires_trade_plan: true, requires_stop_loss: true
                        }},
                        decision_state: {{
                            v2_state_schema_version: 'v2-test', signal: 'C突', signal_name: '突破入场',
                            state: 'entry_breakout', next_action: '等待确认', requires_trade_plan: true,
                            requires_stop_loss: true, candidate_trigger_plan: {{ confirmation_price: 12.4 }}
                        }},
                        score_context: {{ win_rate: 0.62, avg_ret: 0.04, sector_breadth_sample_count: 5 }},
                        decision_explanation: {{
                            headline: '突破候选', summary: '结构与计划通过', drivers: [], cautions: [], score_badges: []
                        }},
                        rule_results: {{ scores: {{ confirm: 4 }}, next_action: '等待确认' }},
                        structure_facts: {{
                            target_structure: {{ selected_breakout_target: {{ price: 13.1 }} }},
                            trigger: {{ breakout: true }}
                        }},
                        permission: {{
                            permission: 'breakout_allowed', permission_label: '允许突破计划',
                            plan_status_label: '计划可执行', plan_gate: {{ status: 'ready', stop_price: 11.8 }}
                        }},
                        conditional_plan: {{ status: 'ready', entry: {{ trigger_price: 12.4 }} }},
                        risk_conditions: {{ risk: {{ score: 0 }}, exit_gate: {{ marker_role: 'observe' }} }},
                        environment_context: {{ macro_tide: {{ permission: 'allowed' }} }},
                        profile: {{ profile_relation_count: 1, profile_relation_groups: [{{ key: 'core_business' }}] }},
                        related_snapshot: {{ data_date: '2026-09-24' }}
                    }});
                }}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                vm.runInContext(fs.readFileSync(file, 'utf8'), context, {{ filename: file }});
            }}

            (async () => {{
                const detail = await context.fetchScanIndexCandidateDetail({{
                    code: '600001', scanType: 'opportunity', snapshotDay: '2026-09-24',
                    eventDate: '2026-09-24'
                }});
                const item = context.scanIndexCandidateDetailToWorkspaceItem({{
                    code: '600001', _scan_type: 'opportunity', _indexed_summary: true,
                    final_score: 56.7, v2_priority_score: 604.8, _visible_rank: 1
                }}, detail);
                assert.strictEqual(item.name, '样本股');
                assert.strictEqual(item.final_score, 56.7);
                assert.strictEqual(item.v2_priority_score, 604.8);
                assert.strictEqual(item.v2_state_model.v2_permission_model.plan_gate.status, 'ready');
                assert.strictEqual(item.v2_state_model.facts.target_structure.selected_breakout_target.price, 13.1);
                assert.strictEqual(item.v2_state_model.facts.exit_gate.marker_role, 'observe');
                assert.strictEqual(item.trade_plan.entry.trigger_price, 12.4);
                assert.strictEqual(item.explanation.headline, '突破候选');
                assert.strictEqual(item.win_rate, 0.62);
                assert.strictEqual(item.profile_relation_groups[0].key, 'core_business');
                assert.strictEqual(item._candidate_detail_source, 'sqlite_candidate_detail');

                let mismatch = null;
                try {{
                    await context.fetchScanIndexCandidateDetail({{
                        code: '600001', scanType: 'risk', eventDate: '2026-09-24'
                    }});
                }} catch (error) {{ mismatch = error; }}
                assert.ok(mismatch && mismatch.message.includes('身份'));
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_sqlite_candidate_detail_api_failure_falls_back_to_exact_json_detail(self):
        scripts = [
            "static/js/api.js",
            "static/js/scanReadModelAdapter.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const urls = [];
            const context = {{
                window: {{ location: {{ search: '?candidate_source=sqlite' }} }},
                URLSearchParams,
                Promise,
                scanWorkspaceState: {{ readSourceOverride: '' }},
                console
            }};
            context.window.window = context.window;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                vm.runInContext(fs.readFileSync(file, 'utf8'), context, {{ filename: file }});
            }}
            context.requestJson = function(url) {{
                urls.push(url);
                if (url.includes('/api/scan_index/')) return Promise.reject(new Error('索引详情暂不可用'));
                return Promise.resolve({{ results: [{{ code: '600001', event_date: '2026-09-24' }}] }});
            }};

            (async () => {{
                const payload = await context.fetchScanCandidateDetail({{
                    code: '600001', scanType: 'opportunity', snapshotDay: '20260924',
                    eventDate: '2026-09-24', indexedSummary: true
                }});
                assert.strictEqual(payload._detail_read_source, 'json_fallback');
                assert.strictEqual(payload._detail_read_error, '索引详情暂不可用');
                assert.ok(urls[0].includes('/api/scan_index/candidates/600001'));
                assert.ok(urls[1].includes('/api/scan_workspace/candidates?'));
                assert.ok(urls[1].includes('snapshot_day=20260924'));
                assert.ok(urls[1].includes('event_date=2026-09-24'));
                assert.ok(urls[1].includes('compact=0'));
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_sqlite_workspace_failure_switches_whole_read_source_to_json(self):
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {{
                window: {{ location: {{ search: '?candidate_source=sqlite' }} }},
                URLSearchParams,
                Promise,
                scanWorkspaceState: {{ readSourceOverride: '', readSourceError: '' }}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync('static/js/api.js', 'utf8'), context, {{ filename: 'static/js/api.js' }});
            context.shouldUseScanIndexRead = function() {{ return context.scanWorkspaceState.readSourceOverride !== 'json'; }};
            context.isScanIndexOptInRequested = function() {{ return true; }};
            context.fetchScanIndexWorkspace = function() {{ return Promise.reject(new Error('索引上下文暂不可用')); }};
            context.fetchScanWorkspaceFromJson = function() {{ return Promise.resolve({{ pools: {{ opportunity: {{ count: 4 }} }} }}); }};

            (async () => {{
                const workspace = await context.fetchScanWorkspace('', false, 120, {{}});
                assert.strictEqual(workspace.read_source, 'json_fallback');
                assert.strictEqual(workspace.read_source_error, '索引上下文暂不可用');
                assert.strictEqual(context.scanWorkspaceState.readSourceOverride, 'json');
                assert.strictEqual(context.shouldUseScanIndexRead(), false);
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_sqlite_workspace_cancellation_does_not_trigger_json_fallback(self):
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            let jsonCalls = 0;
            const context = {{
                window: {{ location: {{ search: '?candidate_source=sqlite' }} }},
                URLSearchParams,
                Promise,
                scanWorkspaceState: {{ readSourceOverride: '', readSourceError: '' }}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync('static/js/api.js', 'utf8'), context, {{ filename: 'static/js/api.js' }});
            context.shouldUseScanIndexRead = function() {{ return context.scanWorkspaceState.readSourceOverride !== 'json'; }};
            context.fetchScanIndexWorkspace = function() {{
                const error = new Error('request aborted');
                error.cancelled = true;
                return Promise.reject(error);
            }};
            context.fetchScanWorkspaceFromJson = function() {{
                jsonCalls += 1;
                return Promise.resolve({{ pools: {{}} }});
            }};

            (async () => {{
                let caught = null;
                try {{ await context.fetchScanWorkspace('', false, 120, {{}}); }}
                catch (error) {{ caught = error; }}
                assert.ok(caught && caught.cancelled);
                assert.strictEqual(jsonCalls, 0);
                assert.strictEqual(context.scanWorkspaceState.readSourceOverride, '');
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_force_refresh_retries_sqlite_after_json_fallback(self):
        script = textwrap.dedent(
            """
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            let indexCalls = 0;
            const context = {
                window: { location: { search: '?candidate_source=sqlite' } },
                URLSearchParams,
                Promise,
                scanWorkspaceState: { readSourceOverride: 'json', readSourceError: 'offline' }
            };
            context.window.window = context.window;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync('static/js/api.js', 'utf8'), context);
            context.shouldUseScanIndexRead = function() {
                return context.scanWorkspaceState.readSourceOverride !== 'json';
            };
            context.fetchScanIndexWorkspace = function() {
                indexCalls += 1;
                return Promise.resolve({ pools: { opportunity: { count: 3 } } });
            };

            (async () => {
                const result = await context.fetchScanWorkspace('', true, 120, {});
                assert.strictEqual(indexCalls, 1);
                assert.strictEqual(context.scanWorkspaceState.readSourceOverride, '');
                assert.strictEqual(context.scanWorkspaceState.readSourceError, '');
                assert.strictEqual(result.pools.opportunity.count, 3);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )

        self._run_node_script(script)

    def test_failed_stale_scan_poll_does_not_clear_new_active_job(self):
        script = textwrap.dedent(
            """
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            let rejectFetch;
            let cleanupCalls = 0;
            const context = {
                window: {},
                document: { getElementById() { return {}; } },
                setTimeout() { return 1; },
                clearTimeout() {},
                fetchScanJob() {
                    return new Promise((resolve, reject) => { rejectFetch = reject; });
                },
                disableScanButtons() { cleanupCalls += 1; },
                refreshScanActionState() { cleanupCalls += 1; },
                updateScanButtonLabel() { cleanupCalls += 1; },
                setScanStatus() { cleanupCalls += 1; },
                showScanError() { cleanupCalls += 1; },
                console
            };
            context.window.window = context.window;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync('static/js/scanJobs.js', 'utf8'), context);
            vm.runInContext("activeScanJobId = 'job-A';", context);

            (async () => {
                const polling = context.pollActiveScanJob();
                vm.runInContext("activeScanJobId = 'job-B';", context);
                rejectFetch(new Error('old request failed'));
                await polling;
                assert.strictEqual(vm.runInContext('activeScanJobId', context), 'job-B');
                assert.strictEqual(cleanupCalls, 0);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )

        self._run_node_script(script)

    def test_sqlite_candidate_expansion_uses_offset_pages_and_restarts_filtered_page(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanWorkspaceStore.js",
            "static/js/scanJobs.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const requests = [];
            const statuses = [];
            const context = {{
                window: {{ localStorage: {{ getItem() {{ return null; }}, setItem() {{}} }} }},
                document: {{ getElementById() {{ return null; }}, querySelectorAll() {{ return []; }} }},
                AbortController,
                AbortSignal,
                console,
                normalizeFilterText(value) {{ return String(value || '').trim().toLowerCase(); }},
                setText() {{}},
                shouldUseScanIndexRead() {{ return true; }},
                fetchScanCandidates(options) {{
                    requests.push(options);
                    const filtered = Boolean(options.query);
                    const code = filtered ? '600003' : '600002';
                    const results = [{{
                        code, event_date: '2026-09-24', signal_key: 'v2_pullback',
                        signal: 'C回', scan_type: 'opportunity', _scan_type: 'opportunity'
                    }}];
                    return Promise.resolve({{
                        source: 'sqlite_index', scan_type: 'opportunity', results,
                        filters: {{query: options.query || '', sector: '', concept: '', reason: ''}},
                        count: filtered ? 1 : 3,
                        loaded_count: filtered ? 1 : 2,
                        has_more: !filtered,
                        offset: options.offset
                    }});
                }},
                getVisibleScanResults() {{ return context.getScanPool('opportunity').results; }},
                renderActiveScanPool() {{}},
                setScanStatus(message) {{ statuses.push(message); }},
                showScanError(_list, message) {{ throw new Error(message); }}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                vm.runInContext(fs.readFileSync(file, 'utf8'), context, {{ filename: file }});
            }}
            context.scanWorkspaceState.readSource = 'sqlite_index';
            context.scanWorkspaceState.pools.opportunity = {{
                count: 3, loaded_count: 1, has_more: true,
                results: [{{code: '600001', event_date: '2026-09-24', signal: 'C回', scan_type: 'opportunity'}}]
            }};

            (async () => {{
                await context.loadMoreScanResults();
                assert.strictEqual(requests[0].offset, 1);
                assert.strictEqual(context.getScanPool('opportunity').results.map(item => item.code).join(','), '600001,600002');

                context.scanWorkspaceState.filters.query = '科技';
                await context.loadMoreScanResults();
                assert.strictEqual(requests[1].offset, 0);
                assert.strictEqual(context.getScanPool('opportunity').results.map(item => item.code).join(','), '600003');
                assert.strictEqual(context.getActiveScanFilterLoadMeta().count, 1);
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
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

    def test_selected_sqlite_summary_loads_candidate_detail_model(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanWorkspaceStore.js",
            "static/js/scanReadModelAdapter.js",
            "static/js/scanSelection.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            let requestedOptions = null;
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{ getElementById() {{ return null; }}, querySelectorAll() {{ return []; }} }},
                URLSearchParams,
                Promise,
                console,
                renderScanSelection() {{}},
                fetchScanCandidateDetail(options) {{
                    requestedOptions = options;
                    return Promise.resolve({{
                        _detail_read_source: 'sqlite_candidate_detail',
                        candidate_detail: {{
                            schema_version: 2,
                            summary: {{
                                code: '600001', pool: 'opportunity', name: '样本A',
                                event_date: '2026-09-24', snapshot_day: '20260924',
                                signal_key: 'v2_breakout', signal_label: 'C突',
                                state: 'entry_breakout', permission: 'breakout_allowed',
                                plan_status: 'ready', price: 10.5, reason_summary: '结构通过'
                            }},
                            decision_state: {{ signal: 'C突', next_action: '等待确认' }},
                            score_context: {{}},
                            decision_explanation: {{ headline: '突破候选', summary: '结构通过', drivers: [], cautions: [] }},
                            rule_results: {{}},
                            structure_facts: {{ target_structure: {{ selected_breakout_target: {{ price: 12 }} }} }},
                            permission: {{ permission: 'breakout_allowed', plan_gate: {{ status: 'ready' }} }},
                            conditional_plan: {{ status: 'ready' }},
                            risk_conditions: {{ risk: {{}}, exit_gate: {{ marker_role: 'observe' }} }},
                            environment_context: {{ macro_tide: {{ permission: 'allowed' }} }},
                            profile: {{}},
                            related_snapshot: {{ data_date: '2026-09-24' }}
                        }}
                    }});
                }}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                vm.runInContext(fs.readFileSync(file, 'utf8'), context, {{ filename: file }});
            }}
            context.scanWorkspaceState.selectedResult = {{
                code: '600001', name: '样本A', event_date: '2026-09-24', date: '2026-09-24',
                snapshot_day: '20260924', _history_snapshot_day: '20260924',
                _scan_type: 'opportunity', _indexed_summary: true, _compact: true
            }};

            (async () => {{
                await context.loadScanCandidateDetailForSelection();
                const selected = context.scanWorkspaceState.selectedResult;
                assert.strictEqual(requestedOptions.indexedSummary, true);
                assert.strictEqual(requestedOptions.snapshotDay, '20260924');
                assert.strictEqual(selected._compact, false);
                assert.strictEqual(selected.trade_plan.status, 'ready');
                assert.strictEqual(selected.v2_state_model.facts.target_structure.selected_breakout_target.price, 12);
                assert.strictEqual(selected._candidate_detail_source, 'sqlite_candidate_detail');
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_scan_workspace_load_aborts_previous_inflight_request(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanWorkspaceStore.js",
            "static/js/scanJobs.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');

            const calls = [];
            const errors = [];
            const statuses = [];
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{
                    getElementById() {{ return {{ innerHTML: '' }}; }},
                    querySelectorAll() {{ return []; }}
                }},
                AbortController,
                AbortSignal,
                console,
                isRequestCancelled(error) {{ return Boolean(error && error.cancelled); }},
                setText(id, message) {{ statuses.push(message); }},
                setScanStatus(message) {{ statuses.push(message); }},
                renderScanWorkspace() {{}},
                enrichActiveScanProfiles() {{}},
                showScanError() {{ errors.push('error'); }},
                loadScanJobHistory() {{}},
                openScanTaskWorkspace() {{}}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            context.fetchScanWorkspace = function(snapshotDay, forceRefresh, limit, options) {{
                const call = {{ snapshotDay, forceRefresh, limit, options, aborted: false }};
                calls.push(call);
                if (calls.length === 1) {{
                    return new Promise((resolve, reject) => {{
                        options.signal.addEventListener('abort', () => {{
                            call.aborted = true;
                            const error = new Error('cancelled');
                            error.cancelled = true;
                            reject(error);
                        }});
                    }});
                }}
                return Promise.resolve({{
                    scanned_count: 1,
                    latest_snapshot_day: '2026-09-20',
                    latest_data_date: '2026-09-20',
                    pools: {{
                        risk: {{ title: '风险', count: 1, loaded_count: 1, results: [{{ code: '600002' }}] }}
                    }}
                }});
            }};

            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            (async () => {{
                const first = context.loadScanWorkspace('opportunity');
                const second = context.loadScanWorkspace('risk');
                const results = await Promise.all([first, second]);

                assert.deepStrictEqual(results, [false, true]);
                assert.strictEqual(calls.length, 2);
                assert.strictEqual(calls[0].aborted, true);
                assert.strictEqual(calls[0].options.signal.aborted, true);
                assert.deepStrictEqual(errors, []);
                assert.strictEqual(statuses.includes('结果读取失败'), false);
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_scan_index_workspace_status_uses_candidate_count(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanWorkspaceStore.js",
            "static/js/scanJobs.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const elements = {{'scan-status': {{innerText: '', textContent: ''}}}};
            const context = {{
                window: {{localStorage: {{getItem() {{return null;}}, setItem() {{}}}}}},
                document: {{getElementById(id) {{return elements[id] || null;}}}},
                console,
                setText(id, value) {{ if (elements[id]) elements[id].innerText = value; }},
                fetchScanWorkspace() {{ return Promise.resolve({{
                    read_source: 'sqlite_index', scanned_count: 0,
                    latest_snapshot_day: '2026-09-24', latest_data_date: '2026-09-24',
                    pools: {{opportunity: {{title: '参与候选', count: 3632, loaded_count: 120, results: []}}}}
                }}); }},
                renderScanWorkspace(workspace) {{ context.applyScanWorkspacePayload(workspace); }},
                enrichActiveScanProfiles() {{}}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                vm.runInContext(fs.readFileSync(file, 'utf8'), context, {{filename: file}});
            }}
            (async () => {{
                const loaded = await context.loadScanWorkspace('opportunity');
                assert.strictEqual(loaded, true);
                assert.strictEqual(elements['scan-status'].innerText, '参与候选 3632 只 · SQLite 摘要');
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_scan_candidate_filter_request_aborts_previous_inflight_request(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanWorkspaceStore.js",
            "static/js/scanJobs.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');

            const calls = [];
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{ querySelectorAll() {{ return []; }} }},
                AbortController,
                AbortSignal,
                console,
                isRequestCancelled(error) {{ return Boolean(error && error.cancelled); }},
                renderActiveScanPool() {{}}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            context.fetchScanCandidates = function(options) {{
                const call = {{ options, aborted: false }};
                calls.push(call);
                if (calls.length === 1) {{
                    return new Promise((resolve, reject) => {{
                        options.signal.addEventListener('abort', () => {{
                            call.aborted = true;
                            const error = new Error('cancelled');
                            error.cancelled = true;
                            reject(error);
                        }});
                    }});
                }}
                return Promise.resolve({{
                    scan_type: 'opportunity',
                    results: [{{ code: '600002', event_date: '2026-09-20' }}],
                    count: 1,
                    loaded_count: 1,
                    has_more: false
                }});
            }};

            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}
            context.scanWorkspaceState.filters.query = '半导体';

            (async () => {{
                const first = context.loadScanCandidatesForCurrentFilters('opportunity', 0, 20)
                    .catch(error => error);
                const second = context.loadScanCandidatesForCurrentFilters('opportunity', 0, 20);
                const firstResult = await first;
                const secondResult = await second;

                assert.strictEqual(calls.length, 2);
                assert.strictEqual(calls[0].aborted, true);
                assert.strictEqual(firstResult.cancelled, true);
                assert.strictEqual(secondResult.loaded_count, 1);
                assert.strictEqual(
                    context.scanWorkspaceState.pools.opportunity.results.map(item => item.code).join(','),
                    '600002'
                );
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_candidate_detail_request_aborts_previous_selection_detail(self):
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

            const calls = [];
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                document: {{
                    getElementById() {{ return {{ value: '', textContent: '', classList: {{ add() {{}}, remove() {{}} }} }}; }},
                    querySelectorAll() {{ return []; }},
                    querySelector() {{ return null; }}
                }},
                AbortController,
                AbortSignal,
                console,
                isRequestCancelled(error) {{ return Boolean(error && error.cancelled); }},
                renderScanSelection() {{}},
                renderActiveScanPool() {{}}
            }};
            context.window.window = context.window;
            context.window.document = context.document;
            context.fetchScanCandidateDetail = function(options) {{
                const call = {{ options, aborted: false }};
                calls.push(call);
                if (calls.length === 1) {{
                    return new Promise((resolve, reject) => {{
                        options.signal.addEventListener('abort', () => {{
                            call.aborted = true;
                            const error = new Error('cancelled');
                            error.cancelled = true;
                            reject(error);
                        }});
                    }});
                }}
                return Promise.resolve({{
                    results: [
                        {{ code: '600002', event_date: '2026-05-12', scan_type: 'opportunity', name: 'second detail' }}
                    ]
                }});
            }};

            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            (async () => {{
                context.scanWorkspaceState.selectedResult = {{
                    code: '600001',
                    event_date: '2026-05-11',
                    scan_type: 'opportunity',
                    _scan_type: 'opportunity',
                    _compact: true
                }};
                const first = context.loadScanCandidateDetailForSelection();
                context.scanWorkspaceState.selectedResult = {{
                    code: '600002',
                    event_date: '2026-05-12',
                    scan_type: 'opportunity',
                    _scan_type: 'opportunity',
                    _compact: true
                }};
                const second = context.loadScanCandidateDetailForSelection();
                await Promise.all([first, second]);

                assert.strictEqual(calls.length, 2);
                assert.strictEqual(calls[0].aborted, true);
                assert.strictEqual(context.scanWorkspaceState.selectedResult.code, '600002');
                assert.strictEqual(context.scanWorkspaceState.selectedResult.name, 'second detail');
                assert.strictEqual(context.scanWorkspaceState.selectedResult._compact, false);
                assert.strictEqual(context.scanWorkspaceState.selectedResult._detail_error, '');
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_deferred_timeframe_requests_can_be_aborted(self):
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
            const calls = [];
            const chartStates = [];
            const context = {{
                window: {{}},
                document: {{ getElementById() {{ return dummyElement(); }} }},
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
                AbortController,
                AbortSignal,
                Promise,
                console,
                isRequestCancelled(error) {{ return Boolean(error && error.cancelled); }},
                normalizeChartStockCode(code) {{
                    const match = String(code || '').match(/\\d{{6}}/);
                    return match ? match[0] : String(code || '').trim();
                }},
                setChartState(message) {{ chartStates.push(message); }},
                setText() {{}},
                renderChart() {{}}
            }};
            context.fetchAnalysisTimeframes = function(code, period, options) {{
                const call = {{ code, period, options, aborted: false }};
                calls.push(call);
                return new Promise((resolve, reject) => {{
                    options.signal.addEventListener('abort', () => {{
                        call.aborted = true;
                        const error = new Error('cancelled');
                        error.cancelled = true;
                        reject(error);
                    }});
                }});
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
                    multi_timeframes: {{}}
                }});

                context.setChartPeriod('60m');
                const promise = context.analysisStore.getTimeframePromise('60m');
                assert.ok(promise);
                assert.strictEqual(calls.length, 1);
                assert.ok(calls[0].options.signal);

                context.abortDeferredTimeframeRequests();
                await promise;
                assert.strictEqual(calls[0].aborted, true);
                assert.strictEqual(context.analysisStore.getTimeframePromise('60m'), null);
                assert.strictEqual(chartStates.some(message => String(message).includes('加载失败')), false);
            }})().catch(error => {{
                console.error(error);
                process.exit(1);
            }});
            """
        )

        self._run_node_script(script)

    def test_chart_tooltips_escape_dynamic_html(self):
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const source = fs.readFileSync({str(ROOT / 'static/js/chartOptions.js')!r}, 'utf8');
            const context = {{
                chartSignalView: 'focus',
                scanFocusColor() {{ return '#111'; }},
                getPointMeta() {{
                    return {{
                        label: '<b>标签</b>',
                        name: '<img src=x onerror=1>',
                        detail: '<script>detail</script>',
                        displaySource: '<svg onload=1></svg>'
                    }};
                }},
                chartMarkerRole() {{ return 'role'; }},
                chartMarkerRoleLabel() {{ return '<em>角色</em>'; }},
                formatPrice(value) {{ return String(value); }}
            }};
            vm.createContext(context);
            vm.runInContext(source, context);

            const option = context.buildChartOption({{
                k_data: [],
                ma20_data: [],
                vwap_data: [],
                custom_data: [],
                dif_data: [],
                dea_data: [],
                macd_data: []
            }}, [], [], 0, null);

            const axisHtml = option.tooltip.formatter([
                {{ name: '<script>x</script>', seriesName: 'K线', value: ['<b>开</b>', 2, 1, 3] }}
            ]);
            const indexedKlineHtml = option.tooltip.formatter([
                {{ name: '2026-09-21', seriesName: 'K线', value: [341, 5.56, 5.67, 5.56, 5.77] }},
                {{ name: '2026-09-21', seriesName: '主力成本线', value: [341, 5.675] }},
                {{ name: '2026-09-21', seriesName: '波动效率', value: [341, 0.38] }}
            ]);
            const markerHtml = option.series[0].markPoint.tooltip.formatter({{
                data: {{
                    date: '<script>d</script>',
                    reason: '<img src=x onerror=1>',
                    price: 12.3
                }}
            }});

            assert.ok(axisHtml.includes('&lt;script&gt;x&lt;/script&gt;'));
            assert.strictEqual(axisHtml.includes('<b>开</b>'), false);
            assert.ok(indexedKlineHtml.includes('<strong>5.56</strong>'));
            assert.ok(indexedKlineHtml.includes('<strong>5.67</strong>'));
            assert.ok(indexedKlineHtml.includes('<strong>5.77</strong>'));
            assert.ok(indexedKlineHtml.includes('0.21'));
            assert.ok(indexedKlineHtml.includes('3.78%'));
            assert.ok(indexedKlineHtml.includes('主力成本'));
            assert.ok(indexedKlineHtml.includes('5.67'));
            assert.ok(indexedKlineHtml.includes('波动效率'));
            assert.ok(indexedKlineHtml.includes('0.38'));
            assert.ok(markerHtml.includes('&lt;em&gt;角色&lt;/em&gt;'));
            assert.ok(markerHtml.includes('&lt;img src=x onerror=1&gt;'));
            assert.strictEqual(axisHtml.includes('<script>'), false);
            assert.strictEqual(markerHtml.includes('<img'), false);
            assert.strictEqual(markerHtml.includes('<svg'), false);
            """
        )

        self._run_node_script(script)

    def test_scan_reason_signal_aliases_match_breakout_family(self):
        scripts = [
            "static/js/scanState.js",
            "static/js/scanStrategyCompare.js",
            "static/js/scanFilters.js",
        ]
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const assert = require('assert');
            const context = {{
                window: {{ localStorage: {{ setItem() {{}}, getItem() {{ return null; }} }} }},
                console,
                isScanV2StrategyView() {{ return true; }}
            }};
            context.window.window = context.window;
            vm.createContext(context);
            for (const file of {scripts!r}) {{
                const source = fs.readFileSync(file, 'utf8');
                vm.runInContext(source, context, {{ filename: file }});
            }}

            assert.strictEqual(context.scanSignalMatchesReason('c_breakout', 'C突', ''), true);
            assert.strictEqual(context.scanSignalMatchesReason('c_breakout', '', 'v2_bear_trap_recovery'), true);
            assert.strictEqual(context.scanSignalMatchesReason('c_breakout', 'C回', 'v2_pullback'), false);
            assert.strictEqual(context.scanSignalMatchesReason('unknown', 'C突', 'v2_breakout'), null);
            assert.strictEqual(context.scanResultMatchesReasonFilter({{ signal_key: 'v2_bear_trap_recovery' }}, 'c_breakout'), true);
            assert.strictEqual(context.scanResultMatchesReasonFilter({{ signal_key: 'v2_breakout' }}, 'unknown'), false);
            """
        )

        self._run_node_script(script)


if __name__ == "__main__":
    unittest.main()
