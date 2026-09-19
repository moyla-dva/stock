function formatChartTooltipNumber(value, digits, fallback) {
    if (value == null || Number.isNaN(Number(value))) return fallback == null ? '-' : fallback;
    var number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits == null ? 2 : digits) : (fallback == null ? '-' : fallback);
}

function buildChartOption(data, dates, markPoints, defaultStart, scanFocus) {
    var scanFocusColorValue = scanFocus ? scanFocusColor(scanFocus) : '#202421';
    return {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            backgroundColor: 'rgba(255, 255, 255, 0.9)',
            formatter: function(params) {
                var date = params[0].name;
                var res = '<div class="chart-tooltip-date">' + date + '</div>';
                params.forEach(function(item) {
                    if (item.seriesName === 'K线') {
                        var open = item.value[0];
                        var close = item.value[1];
                        var low = item.value[2];
                        var high = item.value[3];
                        var amplitude = formatChartTooltipNumber(Number(high) - Number(close), 2);
                        res += 'K线 开: ' + open + ' 收: ' + close + ' 低: ' + low + ' 高: ' + high + '<br/>';
                        res += '波幅: ' + amplitude + '<br/>';
                    } else if (item.seriesName === '主力成本线') {
                        res += '主力成本: ' + formatChartTooltipNumber(item.value, 2) + '<br/>';
                    } else if (item.seriesName === '波动效率') {
                        res += '波动效率: ' + formatChartTooltipNumber(item.value, 2, '0') + '<br/>';
                    }
                });
                return res;
            }
        },
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        grid: [
            { left: '5%', right: '5%', top: '5%', height: '45%' },
            { left: '5%', right: '5%', top: '60%', height: '15%' },
            { left: '5%', right: '5%', top: '80%', height: '15%' }
        ],
        xAxis: [
            { type: 'category', data: dates, gridIndex: 0, axisLine: { onZero: false } },
            { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
            { type: 'category', data: dates, gridIndex: 2, axisLabel: { show: false } }
        ],
        yAxis: [
            { scale: true, splitArea: { show: true }, gridIndex: 0 },
            { scale: true, gridIndex: 1, splitLine: { show: false }, axisLabel: { show: false } },
            { scale: true, gridIndex: 2, splitLine: { show: false } }
        ],
        dataZoom: [
            {
                type: 'inside',
                xAxisIndex: [0, 1, 2],
                start: defaultStart,
                end: 100,
                zoomLock: false,
                zoomOnMouseWheel: true,
                moveOnMouseWheel: false,
                moveOnMouseMove: true,
                moveOnTouch: true,
                preventDefaultMouseMove: true,
                minSpan: 5
            },
            {
                show: true,
                xAxisIndex: [0, 1, 2],
                type: 'slider',
                top: '52%',
                height: 20,
                start: defaultStart,
                end: 100,
                handleSize: '80%',
                brushSelect: true,
                minSpan: 5
            }
        ],
        series: [
            {
                name: 'K线',
                type: 'candlestick',
                data: data.k_data,
                itemStyle: {
                    color: '#ef5350',
                    color0: '#26a69a',
                    borderColor: '#ef5350',
                    borderColor0: '#26a69a'
                },
                markLine: scanFocus ? {
                    silent: true,
                    symbol: ['none', 'none'],
                    lineStyle: {
                        color: scanFocusColorValue,
                        width: 2,
                        type: 'dashed',
                        opacity: 0.72
                    },
                    label: {
                        show: true,
                        formatter: '扫描事件日',
                        position: 'insideEndTop',
                        color: scanFocusColorValue,
                        fontWeight: 900,
                        fontSize: 11
                    },
                    data: [{ xAxis: scanFocus.date }]
                } : undefined,
                markPoint: {
                    data: markPoints,
                    label: { show: chartSignalView !== 'full', color: '#fff' },
                    tooltip: {
                        formatter: function(param) {
                            var point = param.data || {};
                            var meta = getPointMeta(point);
                            var role = typeof chartMarkerRole === 'function' ? chartMarkerRole(point, meta) : '';
                            var roleLabel = typeof chartMarkerRoleLabel === 'function' ? chartMarkerRoleLabel(role, point, meta) : '';
                            var date = point.date || (point.coord && point.coord[0]) || '';
                            var reason = point.reason || point.value || meta.detail || '';
                            var source = meta.displaySource ? '<br/>原始事实: ' + meta.displaySource : '';
                            return '<div class="chart-tooltip-date">' + date + '</div>' +
                                (roleLabel ? roleLabel + '<br/>' : '') +
                                meta.label + ' ' + meta.name + '<br/>' +
                                '收盘: ' + formatPrice(point.price) + '<br/>' +
                                reason +
                                source;
                        }
                    }
                }
            },
            {
                name: 'MA20',
                type: 'line',
                data: data.ma20_data,
                smooth: true,
                lineStyle: { width: 1, color: '#ffb74d', type: 'dashed' },
                symbol: 'none'
            },
            {
                name: '主力成本线',
                type: 'line',
                data: data.vwap_data,
                smooth: true,
                lineStyle: { width: 3, color: '#ffd700' },
                symbol: 'none',
                z: 5
            },
            {
                name: '波动效率',
                type: 'line',
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: data.custom_data,
                smooth: true,
                lineStyle: { width: 1, color: '#ff4081' },
                areaStyle: { opacity: 0.2, color: '#ff4081' }
            },
            {
                name: 'DIF',
                type: 'line',
                xAxisIndex: 2,
                yAxisIndex: 2,
                data: data.dif_data,
                showSymbol: false,
                lineStyle: { width: 1, color: '#333' }
            },
            {
                name: 'DEA',
                type: 'line',
                xAxisIndex: 2,
                yAxisIndex: 2,
                data: data.dea_data,
                showSymbol: false,
                lineStyle: { width: 1, color: '#ff9800' }
            },
            {
                name: 'MACD',
                type: 'bar',
                xAxisIndex: 2,
                yAxisIndex: 2,
                data: data.macd_data,
                itemStyle: {
                    color: function(params) {
                        return params.value > 0 ? '#ef5350' : '#26a69a';
                    }
                }
            }
        ]
    };
}
