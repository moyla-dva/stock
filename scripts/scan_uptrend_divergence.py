#!/usr/bin/env python3
"""
通过Flask API扫描A股中本周出现底背离且整体处于上升趋势的股票
"""
import sys
import os
import requests
import pandas as pd
from datetime import datetime
import time
import json
import akshare as ak

BASE_URL = "http://127.0.0.1:5009"

# 设置代理环境变量（从用户配置文件读取，或使用默认值）
os.environ.setdefault('HTTP_PROXY', 'http://127.0.0.1:7897')
os.environ.setdefault('HTTPS_PROXY', 'http://127.0.0.1:7897')
# 同时设置no_proxy确保本地连接不被代理
os.environ.setdefault('no_proxy', 'localhost,127.0.0.1')

def get_stock_list():
    """获取A股股票列表（走项目 provider 链：TDX → 交易所 → 保底列表）"""
    try:
        from stock_analyzer.catalog_stock_list import get_stock_codes

        return get_stock_codes()
    except Exception as e:
        print(f"[ERROR] 获取股票列表失败: {e}")
        return []

def analyze_via_api(code):
    """通过API分析单个股票"""
    try:
        resp = requests.get(f"{BASE_URL}/api/analyze", params={'code': code}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if 'error' in data:
            return None
        
        # 提取关键信息
        dates = data.get('dates', [])
        k_data = data.get('k_data', [])
        ma20_data = data.get('ma20_data', [])
        mark_points_new = data.get('mark_points_new', [])
        mark_points_old = data.get('mark_points_old', [])
        
        if not dates or not k_data:
            return None

        latest_k = k_data[-1]
        if not isinstance(latest_k, list) or len(latest_k) < 2:
            return None
        latest_close = latest_k[1]
        
        # 判断上升趋势：近10日MA20是否向上
        if len(ma20_data) >= 10:
            recent_ma20 = ma20_data[-10:]
            is_uptrend = recent_ma20[-1] > recent_ma20[0]
        else:
            is_uptrend = False
        
        # 判断本周（近5个交易日）是否有底背离
        recent_days = 5
        recent_bottom_divergence = False
        recent_b_point = False
        
        # 获取最近日期
        latest_date = dates[-1] if dates else None
        
        for mp in mark_points_old:
            # 判断是否是底背离（标签为'回'且不是回踩买点：value=底背离）
            if mp.get('label', {}).get('formatter') == '回' and mp.get('value') == '底背离':
                # 检查是否在最近5个交易日
                mp_date = mp.get('coord', [None, None])[0]
                if mp_date and mp_date in dates[-recent_days:]:
                    recent_bottom_divergence = True
                    break
        
        # 判断是否有新B点（新黄金B点或新回踩买点）
        for mp in mark_points_new:
            mp_date = mp.get('coord', [None, None])[0]
            if mp_date and mp_date in dates[-recent_days:]:
                recent_b_point = True
                break
        
        return {
            'code': code,
            'is_uptrend': is_uptrend,
            'has_bottom_divergence': recent_bottom_divergence,
            'has_b_point': recent_b_point,
            'latest_date': latest_date,
            'close': round(latest_close, 2),
            'name': data.get('stock_name', code)
        }
    except Exception:
        return None

def main():
    print("=" * 60)
    print("通过API扫描：本周底背离 + 上升趋势的A股")
    print("=" * 60)
    
    codes = get_stock_list()
    if not codes:
        print("无法获取股票列表")
        return
    
    results = []
    errors = 0
    batch_size = 20
    
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        print(f"\n批次 {i//batch_size+1}/{(len(codes)-1)//batch_size+1} ({len(batch)}只)")
        
        for code in batch:
            result = analyze_via_api(code)
            if result:
                # 筛选条件
                if result['is_uptrend'] and result['has_bottom_divergence']:
                    results.append(result)
                    print(f"  ✓ {code} - {result['name']} - ¥{result['close']} - {result['latest_date']} - 上升+底背离{' + B点' if result['has_b_point'] else ''}")
            else:
                errors += 1
        
        # 批次间隔
        if i + batch_size < len(codes):
            time.sleep(1)
    
    print("\n" + "=" * 60)
    print(f"扫描完成！测试: {len(codes)}只, 错误: {errors}只")
    print(f"符合条件的: {len(results)}只")
    print("=" * 60)
    
    if results:
        print("\n本周底背离且上升趋势的股票：")
        print("-" * 80)
        for r in results:
            print(f"{r['code']} {r['name']} ¥{r['close']} {r['latest_date']}")

if __name__ == "__main__":
    main()
