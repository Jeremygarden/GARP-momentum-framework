"""
baostock_financial.py
======================
Phase 2 — baostock 财务数据自动填充
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import baostock as bs
import numpy as np
import pandas as pd


def is_trading_hours() -> bool:
    """判断当前是否在 A 股交易时间内（北京时间 9:15-15:35，工作日）。"""
    CST = timezone(timedelta(hours=8))
    now = datetime.now(CST)
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1535


def _to_bs_code(code: str) -> str:
    """baostock 代码格式转换"""
    if code.startswith(("6", "9")):
        return f"sh.{code}"
    return f"sz.{code}"


def _safe_float(val: str | float | int | None) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except Exception:
        return None


def get_financial_data(code: str) -> dict:
    """
    从 baostock 拉取财务数据，计算 GARP 五因子所需字段。
    code: 6位代码，如 '600309'

    ⚠️ 盘后自动跳过：baostock TCP 在盘后（Azure 环境）连接超时。
    盘后调用返回空字典，不阻塞。请在盘中（北京时间 9:15-15:35）运行。
    """
    if not is_trading_hours():
        print(f"  [baostock] 盘后静默，跳过 {code}（请在盘中运行）")
        return {"code": code, "source": "baostock", "skipped": True, "reason": "afterhours"}

    bs_code = _to_bs_code(code)
    lg = bs.login()

    try:
        # 获取名称（可选）
        name = ""
        try:
            rs_basic = bs.query_stock_basic(code=bs_code)
            while rs_basic.next():
                row = rs_basic.get_row_data()
                data = dict(zip(rs_basic.fields, row))
                name = data.get("code_name", "")
                break
        except Exception:
            name = ""

        # 以当前年份 -1 为最新完整年度
        end_year = datetime.now().year - 1

        # 1. 利润数据（营收/净利润/EPS，用于计算 CAGR）
        # query_profit_data: 返回 statDate/roeAvg/npMargin/gpMargin/netProfit/epsTTM/MBRevenue/totalShare/liqaShare
        profit_list = []
        for year in range(end_year, end_year - 5, -1):
            rs = bs.query_profit_data(code=bs_code, year=year, quarter=4)
            while rs.next():
                row = rs.get_row_data()
                profit_list.append(dict(zip(rs.fields, row)))
                break  # 只取年度数据第一条
        profit_df = pd.DataFrame(profit_list)

        # 2. 增速数据（直接提供 YOY，省去自己计算）
        # query_growth_data: 返回 statDate/YOYEquity/YOYAsset/YOYNI/YOYEPSBasic/YOYPNI
        growth_list = []
        for year in range(end_year, end_year - 4, -1):
            rs = bs.query_growth_data(code=bs_code, year=year, quarter=4)
            while rs.next():
                row = rs.get_row_data()
                growth_list.append(dict(zip(rs.fields, row)))
                break
        growth_df = pd.DataFrame(growth_list)

        # 3. 资产负债数据（负债率）
        # query_balance_data: 返回 statDate/liquidAssets/totalAssets/totalLiab/...
        balance_list = []
        rs = bs.query_balance_data(code=bs_code, year=end_year, quarter=4)
        while rs.next():
            row = rs.get_row_data()
            balance_list.append(dict(zip(rs.fields, row)))
            break
        balance_df = pd.DataFrame(balance_list)

        # 4. 历史K线（计算动量）
        # 前复权，adjustflag="2"（🔒冻结，必须显式指定）
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_6m = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,code,close,pctChg",
            start_date=start_6m,
            end_date=end_date,
            frequency="d",
            adjustflag="2",  # 前复权，必须显式指定
        )
        klines = []
        while rs.next():
            klines.append(rs.get_row_data())
        kline_df = pd.DataFrame(klines, columns=["date", "code", "close", "pctChg"])

        # 同期拉沪深300（hs300 = sh.000300）
        rs300 = bs.query_history_k_data_plus(
            "sh.000300",
            "date,code,close,pctChg",
            start_date=start_6m,
            end_date=end_date,
            frequency="d",
            adjustflag="2",
        )
        hs300 = []
        while rs300.next():
            hs300.append(rs300.get_row_data())
        hs300_df = pd.DataFrame(hs300, columns=["date", "code", "close", "pctChg"])

        # ── 计算指标 ──

        # ROE（最新）
        roe = None
        if not profit_df.empty and "roeAvg" in profit_df.columns:
            roe_val = profit_df.iloc[0].get("roeAvg", "")
            roe_raw = _safe_float(roe_val)
            roe = roe_raw * 100 if roe_raw is not None else None

        # ROE 趋势（近3年）
        roe_trend = "stable"
        if not profit_df.empty and len(profit_df) >= 3 and "roeAvg" in profit_df.columns:
            roe_vals = []
            for _, row in profit_df.head(3).iterrows():
                v = _safe_float(row.get("roeAvg", ""))
                if v is not None:
                    roe_vals.append(v)
            if len(roe_vals) >= 3:
                if roe_vals[0] > roe_vals[-1] * 1.05:
                    roe_trend = "improving"
                elif roe_vals[0] < roe_vals[-1] * 0.95:
                    roe_trend = "declining"

        # 毛利率（最新）
        gross_margin = None
        if not profit_df.empty and "gpMargin" in profit_df.columns:
            gm_val = profit_df.iloc[0].get("gpMargin", "")
            gm_raw = _safe_float(gm_val)
            gross_margin = gm_raw * 100 if gm_raw is not None else None

        # 资产负债率（最新）
        debt_ratio = None
        if not balance_df.empty:
            total_assets = _safe_float(balance_df.iloc[0].get("totalAssets", ""))
            total_liab = _safe_float(balance_df.iloc[0].get("totalLiab", ""))
            if total_assets and total_liab:
                try:
                    debt_ratio = total_liab / total_assets * 100
                except Exception:
                    debt_ratio = None

        # EPS CAGR（3年）
        eps_cagr_3y = None
        if not growth_df.empty and "YOYEPSBasic" in growth_df.columns and len(growth_df) >= 3:
            yoy_eps = []
            for _, row in growth_df.head(3).iterrows():
                v = _safe_float(row.get("YOYEPSBasic", ""))
                if v is not None:
                    yoy_eps.append(v * 100)
            if yoy_eps:
                eps_cagr_3y = sum(yoy_eps) / len(yoy_eps)  # 近3年平均YOY

        # 营收 CAGR（3年）
        revenue_cagr_3y = None
        if not growth_df.empty and "YOYPNI" in growth_df.columns and len(growth_df) >= 2:
            # YOYPNI = 净利润同比，用净利润增速代理
            yoy_vals = []
            for _, row in growth_df.head(3).iterrows():
                v = _safe_float(row.get("YOYPNI", ""))
                if v is not None:
                    yoy_vals.append(v * 100)
            if yoy_vals:
                revenue_cagr_3y = sum(yoy_vals) / len(yoy_vals)

        # 动量（6M 超额收益 vs 沪深300）
        momentum_6m_pct = None
        momentum_1m_pct = None
        if not kline_df.empty and not hs300_df.empty:
            kline_df["close"] = pd.to_numeric(kline_df["close"], errors="coerce")
            hs300_df["close"] = pd.to_numeric(hs300_df["close"], errors="coerce")
            kline_df = kline_df.dropna(subset=["close"])
            hs300_df = hs300_df.dropna(subset=["close"])

            if len(kline_df) >= 21:
                # 6M 收益（约126个交易日，取最近180日数据的起始）
                n6m = min(126, len(kline_df) - 1)
                ret_stock_6m = (kline_df.iloc[-1]["close"] / kline_df.iloc[-n6m]["close"] - 1) * 100

                # 对齐日期计算300收益
                n6m_300 = min(126, len(hs300_df) - 1)
                ret_300_6m = (hs300_df.iloc[-1]["close"] / hs300_df.iloc[-n6m_300]["close"] - 1) * 100

                momentum_6m_pct = round(ret_stock_6m - ret_300_6m, 2)

                # 1M（约21个交易日，排除反转效应）
                n1m = min(21, len(kline_df) - 1)
                ret_stock_1m = (kline_df.iloc[-1]["close"] / kline_df.iloc[-n1m]["close"] - 1) * 100
                n1m_300 = min(21, len(hs300_df) - 1)
                ret_300_1m = (hs300_df.iloc[-1]["close"] / hs300_df.iloc[-n1m_300]["close"] - 1) * 100
                momentum_1m_pct = round(ret_stock_1m - ret_300_1m, 2)

        # 最新财报期
        fiscal_year = profit_df.iloc[0].get("statDate", "")[:4] if not profit_df.empty else ""
        data_freshness = profit_df.iloc[0].get("statDate", "")[:7] if not profit_df.empty else ""

        return {
            "code": code,
            "name": name,
            "revenue_cagr_3y": round(revenue_cagr_3y, 2) if revenue_cagr_3y is not None else None,
            "eps_cagr_3y": round(eps_cagr_3y, 2) if eps_cagr_3y is not None else None,
            "consensus_eps_growth": None,
            "roe": round(roe, 2) if roe is not None else None,
            "roe_trend": roe_trend,
            "gross_margin": round(gross_margin, 2) if gross_margin is not None else None,
            "debt_ratio": round(debt_ratio, 2) if debt_ratio is not None else None,
            "momentum_6m_pct": momentum_6m_pct,
            "momentum_1m_pct": momentum_1m_pct,
            "fiscal_year": fiscal_year,
            "data_freshness": data_freshness,
            "source": "baostock",
        }

    finally:
        bs.logout()


def batch_financial_data(codes: list[str], max_workers: int = 8) -> dict[str, dict]:
    """
    批量获取财务数据。
    注意：baostock 登录是全局状态，建议串行调用（baostock 不支持真正的并发）。
    max_workers 在此版本中用于控制重试逻辑。
    """
    results: dict[str, dict] = {}
    total = len(codes)
    for i, code in enumerate(codes):
        try:
            data = get_financial_data(code)
            results[code] = data
        except Exception as e:
            print(f"  [{i+1}/{total}] {code} 失败: {e}")
            results[code] = {"code": code, "source": "baostock", "error": str(e)}
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{total}] 财务数据获取中...")
        time.sleep(0.2)  # 礼貌性间隔
    return results


def run_phase2_batch(
    candidate_pool_path: str = "data/candidate_pool.json",
    regime: str = "neutral",
    top_n: int = 50,
    output_path: str = "data/phase2_results.json",
) -> list[dict]:
    """
    Phase 2 完整流程：
    1. 读取候选池（pre_filter 输出的 JSON）
    2. 批量拉 baostock 财务数据（ROE/增速/动量）
    3. 调用 batch_garp_score 评分
    4. 输出 Top N 排名到 JSON 文件

    ⚠️ 需要在盘中（北京时间 9:15-15:35）运行，baostock TCP 盘后不可用。
    """
    if not is_trading_hours():
        print("❌ 当前为盘后时间，baostock TCP 不可用，请在盘中运行。")
        print("   建议运行时间：工作日 09:30-15:00（北京时间）")
        return []

    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from pre_filter import load_candidate_pool
    from a_stock_supplement import batch_garp_score

    candidates = load_candidate_pool(candidate_pool_path)
    codes = [c["code"] for c in candidates]
    financial_data = batch_financial_data(codes)

    results = batch_garp_score(
        stocks=candidates,
        regime=regime,
        financial_data=financial_data,
    )

    top_results = results[:top_n]

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "regime": regime,
        "top_n": top_n,
        "total_candidates": len(candidates),
        "results": top_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[Phase2] 输出 Top{top_n} 到 {output_path}")
    return top_results


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from a_stock_supplement import auto_garp_score

    for test_code, test_name in [("600519", "贵州茅台"), ("600309", "万华化学")]:
        print(f"\n{'='*50}")
        print(f"{test_name} {test_code}")
        print('='*50)

        data = get_financial_data(test_code)

        if data.get("skipped"):
            print(f"  ⚠️  {data.get('reason','盘后')} — 请在盘中（北京时间9:15-15:35）运行")
            continue

        print(f"ROE={data.get('roe')} 毛利率={data.get('gross_margin')} 负债率={data.get('debt_ratio')}")
        print(f"EPS CAGR={data.get('eps_cagr_3y')} 营收CAGR={data.get('revenue_cagr_3y')}")
        print(f"6M动量={data.get('momentum_6m_pct')}% 1M动量={data.get('momentum_1m_pct')}%")
        print(f"ROE趋势={data.get('roe_trend')} 财报期={data.get('data_freshness')}")

        fin_keys = ["revenue_cagr_3y","eps_cagr_3y","roe","gross_margin","debt_ratio","momentum_6m_pct"]
        result = auto_garp_score(
            test_code, regime="neutral",
            **{k: data.get(k) for k in fin_keys}
        )
        print(f"\nGARP总分={result['total_score']} {result['tier']}")
        print(f"G={result['scores']['G']} Q={result['scores']['Q']} V={result['scores']['V']} M={result['scores']['M']} R={result['scores']['R']}")
        for k, v in result['factor_notes'].items():
            print(f"  {k}: {v}")
        print(f"建议: {result['recommendation']}")
