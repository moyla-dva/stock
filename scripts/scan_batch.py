#!/usr/bin/env python3
"""
扫描A股中本周出现底背离且整体处于上升趋势的股票
"""
import sys
import os
import pandas as pd
from datetime import datetime
import time

# 添加项目路径
sys.path.insert(0, '/Users/vainve/股票短线分析软件')

# 设置代理环境变量（确保akshare能连接）
os.environ.setdefault('HTTP_PROXY', 'http://127.0.0.1:7897')
os.environ.setdefault('HTTPS_PROXY', 'http://127.0.0.1:7897')
os.environ.setdefault('no_proxy', 'localhost,127.0.0.1')

import akshare as ak
import numpy as np
from stock_analyzer.versioning import DATA_ADJUST, DATA_START_DATE


def normalize_code(code):
    """规范化股票代码"""
    import re
    if code is None:
        return None
    code = str(code).strip()
    if not code:
        return None
    match = re.search(r'(\d{6})', code)
    return match.group(1) if match else None

def calculate_kdj(df, period=9):
    """计算KDJ指标"""
    low_list = df['low'].rolling(window=period, min_periods=1).min()
    high_list = df['high'].rolling(window=period, min_periods=1).max()
    denom = (high_list - low_list).replace(0, np.nan)
    rsv = (df['close'] - low_list) / denom * 100
    df['k'] = rsv.ewm(com=2, adjust=False).mean()
    df['d'] = df['k'].ewm(com=2, adjust=False).mean()
    df['j'] = 3 * df['k'] - 2 * df['d']
    return df

def calculate_bollinger_bands(df, period=20, std_dev=2):
    """计算布林带"""
    df['bb_middle'] = df['close'].rolling(window=period).mean()
    df['bb_std'] = df['close'].rolling(window=period).std()
    df['bb_upper'] = df['bb_middle'] + std_dev * df['bb_std']
    df['bb_lower'] = df['bb_middle'] - std_dev * df['bb_std']
    # 布林位置 (0-1之间，越低越靠近下轨)
    df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
    # 触及上轨
    df['touch_upper'] =(df['close'] >= df['bb_upper']).astype(int)
    # 触及下轨
    df['touch_lower'] =(df['close'] <= df['bb_lower']).astype(int)
    return df

def calculate_ma(df, periods=[5, 10, 20]):
    """计算移动平均线"""
    for p in periods:
        df[f'ma{p}'] = df['close'].rolling(window=p).mean()
        df[f'ma{p}_prev'] = df[f'ma{p}'].shift(1)
    return df

def calculate_macd(df, fast=12, slow=26, signal=9):
    """计算MACD指标"""
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    df['dif'] = ema_fast - ema_slow
    df['dea'] = df['dif'].ewm(span=signal, adjust=False).mean()
    df['macd_hist'] = (df['dif'] - df['dea']) * 2
    # 保存前值用于背离判断
    df['macd_hist_prev'] = df['macd_hist'].shift(1)
    return df

def calculate_bias(df, period=20):
    """计算乖离率 BIAS"""
    ma = df['close'].rolling(window=period).mean()
    df['bias'] = (df['close'] - ma) / ma * 100
    return df

def calculate_volume_ma(df, periods=[5, 10]):
    """计算成交量移动平均"""
    for p in periods:
        df[f'volume_ma{p}'] = df['volume'].rolling(window=p).mean()
        df[f'volume_ma{p}_prev'] = df[f'volume_ma{p}'].shift(1)
    return df

def calculate_vwap(df):
    """计算等权均线"""
    # 简单的等权价格平均
    df['vwap'] = (df['high'] + df['low'] + df['close']) / 3
    return df

def calculate_divergence(df):
    """计算背离信号"""
    # --- MACD 背离 ---
    # 顶背离：价格创新高但 MACD 柱状图高点下移
    df['is_top_divergence'] = 0
    # 底背离：价格创新低但 MACD 柱状图低点上移
    df['is_bottom_divergence'] = 0
    
    for i in range(20, len(df)):
        # 检查前20根K线作为窗口
        window = df.iloc[i-5:i+1]  # 当前帧+前4根
        
        # 价格是否创新低
        low_idx = window['low'].idxmin()
        macd_low_idx = window['macd_hist'].idxmin()
        
        # 条件1: 价格低点出现在最近，且MACD低点没有同步（反而提前或滞后）
        if low_idx == i:  # 当前帧是价格最低点
            if macd_low_idx < i:  # MACD低点出现在之前（提前）
                df.at[i, 'is_bottom_divergence'] = 1
    
    return df

def calculate_signals(df):
    """计算买卖信号"""
    df['new_is_b_point'] = 0
    df['new_is_pullback_b'] = 0
    df['new_is_s_point'] = 0

    if 'is_s_point' not in df.columns:
        df['is_s_point'] = 0

    if 'is_pullback_b' not in df.columns:
        df['is_pullback_b'] = (
            df['ma20'].notna() &
            (df['close'] >= df['ma20'] * 0.98) &
            (df['close'] <= df['ma20'] * 1.02) &
            (df['close'] >= df['open'])
        ).astype(int)
    
    for idx in range(len(df)):
        row = df.iloc[idx]
        
        # 新黄金B点条件
        if (row['close'] < row['ma20'] and 
            row['j'] < 30 and 
            (row['bias'] < -15 or row['bb_position'] < 0.2) and
            (row['volume'] < row['volume_ma5_prev'] * 0.8) and
            (row['volume'] < row['volume_ma10_prev'] * 0.8) and
            not row['is_s_point'] and
            row['ma20'] > row['ma20_prev'] and
            row['is_bottom_divergence']):
            df.at[idx, 'new_is_b_point'] = 1
        
        # 新回踩买点：在B点确立后，价格回踩MA20且不破前低
        elif (row['new_is_b_point'] == 0 and
              row['is_pullback_b'] and
              row['close'] > row['ma20'] * 0.98 and row['close'] < row['ma20'] * 1.02):
            df.at[idx, 'new_is_pullback_b'] = 1
        
        # 新S点：MACD顶背离 + J值超买 + 成交量放大
        if (row['dif'] > 0 and row['dea'] > 0 and
            row['j'] > 80 and
            row['volume'] > row['volume_ma5_prev'] * 1.5 and
            row['is_top_divergence']):
            df.at[idx, 'new_is_s_point'] = 1
    
    return df

def fetch_stock_data(code, start_date, end_date):
    """获取股票数据（复用项目 fetch_stock_history：腾讯主源 + TDX 兜底）"""
    from stock_analyzer.data_fetcher import fetch_stock_history

    df = fetch_stock_history(code, start_date=start_date, adjust=DATA_ADJUST)

    if df is None or df.empty:
        return None

    # 标准化列名
    df = df.rename(columns={
        '日期': 'date', '开盘': 'open', '收盘': 'close',
        '最高': 'high', '最低': 'low', '成交量': 'volume',
        '成交额': 'amount'
    })

    # 确保日期格式
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    return df

def analyze_stock(code):
    """分析单个股票，返回是否出现底背离和上升趋势"""
    # 获取固定起始日以来的数据
    end = datetime.now()

    df = fetch_stock_data(code, DATA_START_DATE.replace("-", ""), end.strftime("%Y%m%d"))
    if df is None or len(df) < 30:
        return None
    
    # 计算指标
    df = calculate_ma(df)
    df = calculate_bollinger_bands(df)
    df = calculate_macd(df)
    df = calculate_kdj(df)
    df = calculate_bias(df)
    df = calculate_volume_ma(df)
    df = calculate_vwap(df)
    df = calculate_divergence(df)
    df = calculate_signals(df)
    
    # 判断整体趋势：近20日MA20是否向上
    recent_ma20 = df['ma20'].iloc[-10:].values  # 近10个交易日
    is_uptrend = recent_ma20[-1] > recent_ma20[0]
    
    # 判断本周（近5个交易日）是否有底背离
    recent_days = 5
    recent_bottom_divergence = df['is_bottom_divergence'].iloc[-recent_days:].any()
    
    # 判断本周是否出现新B点信号
    recent_b_point = df['new_is_b_point'].iloc[-recent_days:].any()
    
    return {
        'code': code,
        'is_uptrend': is_uptrend,
        'has_bottom_divergence': recent_bottom_divergence,
        'has_b_point': recent_b_point,
        'latest_date': df['date'].iloc[-1].strftime('%Y-%m-%d'),
        'close': round(df['close'].iloc[-1], 2)
    }

def get_all_stock_codes():
    """获取所有A股股票代码列表（走项目 provider 链：TDX → 交易所 → 保底列表）"""
    try:
        from stock_analyzer.catalog_stock_list import get_stock_codes

        codes = get_stock_codes()
        print(f"获取到 {len(codes)} 只A股（TDX 清单不区分 ST 标记）")
        return codes
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        return []

def main():
    print("开始扫描A股底背离+上升趋势股票...")
    print("=" * 60)
    
    # 获取所有股票代码
    codes = get_all_stock_codes()
    if not codes:
        print("无法获取股票列表，退出")
        return
    
    results = []
    tested = 0
    errors = 0
    
    # 分批处理
    batch_size = 50
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        print(f"\n处理批次 {i//batch_size+1}/{(len(codes)-1)//batch_size+1} ({len(batch)}只)")
        
        for code in batch:
            try:
                result = analyze_stock(code)
                tested += 1
                if result:
                    # 筛选条件：上升趋势 + 本周有底背离
                    if result['is_uptrend'] and result['has_bottom_divergence']:
                        results.append(result)
                        print(f"  ✓ {code} - {result['close']}元 - {result['latest_date']} - 上升趋势 + 底背离")
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                # 不打印每个错误，避免刷屏
        
        # 批次间暂停，避免API限制
        if i + batch_size < len(codes):
            print(f"  批次完成，暂停3秒...")
            time.sleep(3)
    
    print("\n" + "=" * 60)
    print(f"扫描完成！总计测试: {tested}只, 错误: {errors}只")
    print(f"符合条件的股票: {len(results)}只")
    print("=" * 60)
    
    if results:
        print("\n本周出现的底背离且上升趋势的股票：")
        print("-" * 60)
        for r in results:
            print(f"{r['code']} - 最新价: {r['close']}元 - 日期: {r['latest_date']}")
            if r['has_b_point']:
                print(f"    ⚠️ 本周出现新B点信号")
        print("-" * 60)
        
        # 保存结果
        df_out = pd.DataFrame(results)
        output_file = '/Users/vainve/股票短线分析软件/scan_results_uptrend_divergence.csv'
        df_out.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存至: {output_file}")
    else:
        print("未找到符合条件的股票。")

if __name__ == "__main__":
    main()
