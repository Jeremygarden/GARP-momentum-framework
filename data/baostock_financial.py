"""
baostock_financial.py
======================
Phase 2 — GARP 财务数据 + 前复权K线 自动填充

数据源切换状态（2026-05-22）：
  - 财务数据：东财 ZYZBAjaxNew（HTTPS）✅ 当前主力
  - 前复权K线：东财 push2his（HTTPS，fqt=1）✅ 当前主力
  - baostock：TCP 9898 在 Azure 环境被封，代码已注释保留
    ⚠️ 待办：登录 Azure NSG 添加出站 TCP 9898 规则后，取消注释重新验证
    验证通过后可切回 baostock（财务深度更稳定）或继续用东财

baostock 原有优势（封锁解除后可重新评估）：
  - 财务数据：~20期历史深度，字段标准化好
  - 前复权K线：adjustflag=2，官方认证前复权
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

# ── 东财公共配置 ──────────────────────────────────────────────
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_EASTMONEY_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://emweb.securities.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
_KLINE_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ── 数据源开关 ────────────────────────────────────────────────
# 当 Azure NSG 解封 baostock TCP 9898 后，将此项改为 "baostock" 重新验证
DATA_SOURCE = "eastmoney"  # "eastmoney" | "baostock"


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def is_trading_hours() -> bool:
    """判断当前是否在 A 股交易时间内（北京时间 9:15-15:35，工作日）。"""
    CST = timezone(timedelta(hours=8))
    now = datetime.now(CST)
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1535


def _safe_float(val) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except Exception:
        return None


def _kline_is_fresh(df: pd.DataFrame, max_age_days: int = 7) -> bool:
    """确认K线末条日期足够新鲜；过期动量不得沿用旧数据。"""
    if df is None or df.empty or "date" not in df.columns:
        return False
    try:
        latest = pd.to_datetime(df["date"].iloc[-1]).to_pydatetime()
    except Exception:
        return False
    return (datetime.now() - latest) <= timedelta(days=max_age_days)


def _to_em_secid(code: str) -> str:
    """东财 secid 格式：沪市1.xxxxxx，深市0.xxxxxx，指数特殊处理"""
    if code.startswith("0") and len(code) == 6 and code[0] == "0":
        # 000开头指数
        if code.startswith("000") or code.startswith("399"):
            return f"0.{code}"
        return f"0.{code}"
    if code.startswith(("6", "9")):
        return f"1.{code}"
    return f"0.{code}"


def _to_em_secid_index(code: str) -> str:
    """沪深300指数专用"""
    return "1.000300"  # sh.000300


# ══════════════════════════════════════════════════════════════
# 东财：财务数据（ZYZBAjaxNew）
# ══════════════════════════════════════════════════════════════

def _em_get_finance_main(code: str) -> list[dict]:
    """
    拉取东财主要财务指标（ZYZBAjaxNew）。
    返回按 REPORT_DATE 倒序的多期数据列表。
    字段包含：ROEJQ/XSMLL/XSJLL/ZCFZL/TOTALOPERATEREVETZ/PARENTNETPROFITTZ/EPSJBTZ 等。
    """
    url = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew"
    # type=0 返回全量年报；code 格式 SH600519 / SZ000001
    prefix = "SH" if code.startswith(("6", "9")) else "SZ"
    params = {"type": "0", "code": f"{prefix}{code}"}
    try:
        r = requests.get(url, params=params, headers=_EASTMONEY_HEADERS, timeout=10)
        data = r.json()
        rows = data.get("data", [])
        if not rows:
            return []
        # 按报告期倒序（最新在前）
        rows.sort(key=lambda x: x.get("REPORT_DATE", ""), reverse=True)
        return rows
    except Exception as e:
        print(f"  [东财财务] {code} 异常: {e}")
        return []


def _em_calc_financials(code: str) -> dict:
    """
    从东财 ZYZBAjaxNew 计算 GARP 所需财务指标。
    返回字段与 baostock 版本完全一致，方便无缝切换。
    """
    rows = _em_get_finance_main(code)

    # 名称从第一条取
    name = rows[0].get("SECURITY_NAME_ABBR", "") if rows else ""

    # 年报数据（REPORT_TYPE=="006"为年报，或 REPORT_DATE_NAME 含"年报"）
    annual = [r for r in rows if "年报" in r.get("REPORT_DATE_NAME", "")]
    if not annual:
        # 兜底：取 Q4 报告（REPORT_DATE 月份为 12）
        annual = [r for r in rows if r.get("REPORT_DATE", "")[:7].endswith("-12")]
    # 最多取最近 5 年
    annual = annual[:5]

    latest = annual[0] if annual else {}

    # ROE（加权，已是百分比）
    roe = _safe_float(latest.get("ROEJQ"))

    # ROE 趋势（近3年）
    roe_trend = "stable"
    if len(annual) >= 3:
        roe_vals = [_safe_float(r.get("ROEJQ")) for r in annual[:3]]
        roe_vals = [v for v in roe_vals if v is not None]
        if len(roe_vals) >= 3:
            if roe_vals[0] > roe_vals[-1] * 1.05:
                roe_trend = "improving"
            elif roe_vals[0] < roe_vals[-1] * 0.95:
                roe_trend = "declining"

    # 毛利率（已是百分比）
    gross_margin = _safe_float(latest.get("XSMLL"))

    # 资产负债率（已是百分比）
    debt_ratio = _safe_float(latest.get("ZCFZL"))

    # EPS CAGR（近3年平均 YOY）
    eps_cagr_3y = None
    eps_yoys = [_safe_float(r.get("EPSJBTZ")) for r in annual[:3]]
    eps_yoys = [v for v in eps_yoys if v is not None]
    if eps_yoys:
        eps_cagr_3y = round(sum(eps_yoys) / len(eps_yoys), 2)

    # 营收 CAGR（近3年平均 YOY，用净利润增速 PARENTNETPROFITTZ 代理，与 baostock YOYPNI 对应）
    revenue_cagr_3y = None
    ni_yoys = [_safe_float(r.get("PARENTNETPROFITTZ")) for r in annual[:3]]
    ni_yoys = [v for v in ni_yoys if v is not None]
    if ni_yoys:
        revenue_cagr_3y = round(sum(ni_yoys) / len(ni_yoys), 2)

    # 财报期
    fiscal_year = latest.get("REPORT_DATE", "")[:4]
    data_freshness = latest.get("REPORT_DATE", "")[:7]

    return {
        "name": name,
        "roe": round(roe, 2) if roe is not None else None,
        "roe_trend": roe_trend,
        "gross_margin": round(gross_margin, 2) if gross_margin is not None else None,
        "debt_ratio": round(debt_ratio, 2) if debt_ratio is not None else None,
        "eps_cagr_3y": eps_cagr_3y,
        "revenue_cagr_3y": revenue_cagr_3y,
        "fiscal_year": fiscal_year,
        "data_freshness": data_freshness,
    }


# ══════════════════════════════════════════════════════════════
# 东财：前复权K线（push2his，fqt=1）
# ══════════════════════════════════════════════════════════════

def _em_get_kline(secid: str, days: int = 200) -> pd.DataFrame:
    """
    拉取前复权日K线。
    当前实现：yfinance（Azure 环境下东财 push2his/push2 被 NSG 拦截）。
    secid: 东财格式 "1.600519" / "0.000300"，内部转换为 yfinance ticker。
    返回 DataFrame，列：date(str), close(float)
    """
    # 东财 secid → yfinance ticker
    # "1.600519" → "600519.SS"（沪市），"0.000001" → "000001.SZ"（深市）
    # 指数：000300 → "000300.SS"
    parts = secid.split(".")
    code = parts[1] if len(parts) == 2 else secid
    market = parts[0] if len(parts) == 2 else "1"
    if market == "1":
        ticker_sym = f"{code}.SS"
    else:
        ticker_sym = f"{code}.SZ"

    import yfinance as yf
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        df = yf.Ticker(ticker_sym).history(start=start, auto_adjust=True)
        if df.empty:
            return pd.DataFrame(columns=["date", "close"])
        result = pd.DataFrame({
            "date": df.index.strftime("%Y-%m-%d"),
            "close": df["Close"].values,
        }).dropna(subset=["close"])
        return result
    except Exception as e:
        print(f"  [yfinance K线] {ticker_sym} 异常: {e}")
        return pd.DataFrame(columns=["date", "close"])


def _calc_momentum(stock_df: pd.DataFrame, index_df: pd.DataFrame) -> tuple[Optional[float], Optional[float]]:
    """计算6M/1M超额动量；K线超过7天视为过期，不使用旧值。"""
    if stock_df.empty or index_df.empty or len(stock_df) < 21:
        return None, None
    if not _kline_is_fresh(stock_df) or not _kline_is_fresh(index_df):
        print("  [动量] K线超过7天或日期异常，返回 None 触发上层降级")
        return None, None

    n6m = min(126, len(stock_df) - 1)
    ret_stock_6m = (stock_df.iloc[-1]["close"] / stock_df.iloc[-n6m]["close"] - 1) * 100
    n6m_300 = min(126, len(index_df) - 1)
    ret_300_6m = (index_df.iloc[-1]["close"] / index_df.iloc[-n6m_300]["close"] - 1) * 100
    momentum_6m = round(ret_stock_6m - ret_300_6m, 2)

    n1m = min(21, len(stock_df) - 1)
    ret_stock_1m = (stock_df.iloc[-1]["close"] / stock_df.iloc[-n1m]["close"] - 1) * 100
    n1m_300 = min(21, len(index_df) - 1)
    ret_300_1m = (index_df.iloc[-1]["close"] / index_df.iloc[-n1m_300]["close"] - 1) * 100
    momentum_1m = round(ret_stock_1m - ret_300_1m, 2)

    return momentum_6m, momentum_1m


# ══════════════════════════════════════════════════════════════
# 主函数：get_financial_data
# ══════════════════════════════════════════════════════════════

def get_financial_data(code: str, _session_active: bool = False) -> dict:
    """
    拉取 GARP 五因子所需财务数据 + 前复权K线动量。
    code: 6位A股代码，如 '600519'

    当前数据源：东财（DATA_SOURCE="eastmoney"），走 HTTPS，无 TCP 限制。
    baostock 代码已注释保留，等待 Azure NSG 解封 TCP 9898 后可切回。
    """
    if DATA_SOURCE == "eastmoney":
        return _get_financial_data_eastmoney(code)
    else:
        return _get_financial_data_baostock(code, _session_active)


def _get_financial_data_eastmoney(code: str) -> dict:
    """东财版本：财务数据 + push2his 前复权K线。无盘中限制，7×24 可用。"""
    # 财务数据
    fin = _em_calc_financials(code)

    # 前复权K线（个股 + 沪深300）
    secid = _to_em_secid(code)
    stock_df = _em_get_kline(secid, days=200)
    hs300_df = _em_get_kline("1.000300", days=200)  # 000300.SS

    momentum_6m, momentum_1m = _calc_momentum(stock_df, hs300_df)

    return {
        "code": code,
        "name": fin.get("name", ""),
        "revenue_cagr_3y": fin.get("revenue_cagr_3y"),
        "eps_cagr_3y": fin.get("eps_cagr_3y"),
        "consensus_eps_growth": None,
        "roe": fin.get("roe"),
        "roe_trend": fin.get("roe_trend", "stable"),
        "gross_margin": fin.get("gross_margin"),
        "debt_ratio": fin.get("debt_ratio"),
        "momentum_6m_pct": momentum_6m,
        "momentum_1m_pct": momentum_1m,
        "momentum_asof": stock_df["date"].iloc[-1] if not stock_df.empty else "",
        "momentum_needs_refresh": momentum_6m is None,
        "fiscal_year": fin.get("fiscal_year", ""),
        "data_freshness": fin.get("data_freshness", ""),
        "source": "eastmoney",
    }


# ══════════════════════════════════════════════════════════════
# baostock 版本（保留，Azure NSG 解封 TCP 9898 后可切回）
# ⚠️ 待办：登录 Azure NSG 添加出站 TCP 9898 规则 → 测试通过后将 DATA_SOURCE 改为 "baostock"
# ══════════════════════════════════════════════════════════════

def _get_financial_data_baostock(code: str, _session_active: bool = False) -> dict:
    """
    baostock 版本。
    TCP 9898 在 Azure 环境被 NSG 封锁，当前不可用。
    代码完整保留，解封后直接切 DATA_SOURCE="baostock" 即可。
    """
    # ── 延迟导入，避免 import 时就触发 baostock 初始化 ──
    import baostock as bs  # noqa: F401

    if not is_trading_hours():
        print(f"  [baostock] 盘后静默，跳过 {code}（请在盘中运行）")
        return {"code": code, "source": "baostock", "skipped": True, "reason": "afterhours"}

    bs_code = code[0:6]
    bs_code = f"sh.{code}" if code.startswith(("6", "9")) else f"sz.{code}"
    if not _session_active:
        bs.login()

    try:
        name = ""
        try:
            rs_basic = bs.query_stock_basic(code=bs_code)
            while rs_basic.next():
                row = rs_basic.get_row_data()
                d = dict(zip(rs_basic.fields, row))
                name = d.get("code_name", "")
                break
        except Exception:
            pass

        end_year = datetime.now().year - 1

        profit_list = []
        for year in range(end_year, end_year - 5, -1):
            rs = bs.query_profit_data(code=bs_code, year=year, quarter=4)
            while rs.next():
                profit_list.append(dict(zip(rs.fields, rs.get_row_data())))
                break
        profit_df = pd.DataFrame(profit_list)

        growth_list = []
        for year in range(end_year, end_year - 4, -1):
            rs = bs.query_growth_data(code=bs_code, year=year, quarter=4)
            while rs.next():
                growth_list.append(dict(zip(rs.fields, rs.get_row_data())))
                break
        growth_df = pd.DataFrame(growth_list)

        balance_list = []
        rs = bs.query_balance_data(code=bs_code, year=end_year, quarter=4)
        while rs.next():
            balance_list.append(dict(zip(rs.fields, rs.get_row_data())))
            break
        balance_df = pd.DataFrame(balance_list)

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_6m = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        rs = bs.query_history_k_data_plus(
            bs_code, "date,code,close,pctChg",
            start_date=start_6m, end_date=end_date,
            frequency="d", adjustflag="2",  # 🔒 前复权，必须显式指定
        )
        klines = []
        while rs.next():
            klines.append(rs.get_row_data())
        kline_df = pd.DataFrame(klines, columns=["date", "code", "close", "pctChg"])

        rs300 = bs.query_history_k_data_plus(
            "sh.000300", "date,code,close,pctChg",
            start_date=start_6m, end_date=end_date,
            frequency="d", adjustflag="2",
        )
        hs300 = []
        while rs300.next():
            hs300.append(rs300.get_row_data())
        hs300_df = pd.DataFrame(hs300, columns=["date", "code", "close", "pctChg"])

        roe = None
        if not profit_df.empty and "roeAvg" in profit_df.columns:
            v = _safe_float(profit_df.iloc[0].get("roeAvg", ""))
            roe = v * 100 if v is not None else None

        roe_trend = "stable"
        if not profit_df.empty and len(profit_df) >= 3 and "roeAvg" in profit_df.columns:
            vals = [_safe_float(r.get("roeAvg", "")) for _, r in profit_df.head(3).iterrows()]
            vals = [v for v in vals if v is not None]
            if len(vals) >= 3:
                if vals[0] > vals[-1] * 1.05:
                    roe_trend = "improving"
                elif vals[0] < vals[-1] * 0.95:
                    roe_trend = "declining"

        gross_margin = None
        if not profit_df.empty and "gpMargin" in profit_df.columns:
            v = _safe_float(profit_df.iloc[0].get("gpMargin", ""))
            gross_margin = v * 100 if v is not None else None

        debt_ratio = None
        if not balance_df.empty:
            ta = _safe_float(balance_df.iloc[0].get("totalAssets", ""))
            tl = _safe_float(balance_df.iloc[0].get("totalLiab", ""))
            if ta and tl:
                debt_ratio = round(tl / ta * 100, 2)

        eps_cagr_3y = None
        if not growth_df.empty and "YOYEPSBasic" in growth_df.columns and len(growth_df) >= 3:
            vals = [_safe_float(r.get("YOYEPSBasic", "")) for _, r in growth_df.head(3).iterrows()]
            vals = [v * 100 for v in vals if v is not None]
            if vals:
                eps_cagr_3y = round(sum(vals) / len(vals), 2)

        revenue_cagr_3y = None
        if not growth_df.empty and "YOYPNI" in growth_df.columns:
            vals = [_safe_float(r.get("YOYPNI", "")) for _, r in growth_df.head(3).iterrows()]
            vals = [v * 100 for v in vals if v is not None]
            if vals:
                revenue_cagr_3y = round(sum(vals) / len(vals), 2)

        kline_df["close"] = pd.to_numeric(kline_df["close"], errors="coerce")
        hs300_df["close"] = pd.to_numeric(hs300_df["close"], errors="coerce")
        kline_df = kline_df.dropna(subset=["close"])
        hs300_df = hs300_df.dropna(subset=["close"])
        momentum_6m, momentum_1m = _calc_momentum(kline_df, hs300_df)

        fiscal_year = profit_df.iloc[0].get("statDate", "")[:4] if not profit_df.empty else ""
        data_freshness = profit_df.iloc[0].get("statDate", "")[:7] if not profit_df.empty else ""

        return {
            "code": code,
            "name": name,
            "revenue_cagr_3y": revenue_cagr_3y,
            "eps_cagr_3y": eps_cagr_3y,
            "consensus_eps_growth": None,
            "roe": round(roe, 2) if roe is not None else None,
            "roe_trend": roe_trend,
            "gross_margin": round(gross_margin, 2) if gross_margin is not None else None,
            "debt_ratio": debt_ratio,
            "momentum_6m_pct": momentum_6m,
            "momentum_1m_pct": momentum_1m,
            "momentum_asof": kline_df["date"].iloc[-1] if not kline_df.empty else "",
            "momentum_needs_refresh": momentum_6m is None,
            "fiscal_year": fiscal_year,
            "data_freshness": data_freshness,
            "source": "baostock",
        }

    finally:
        if not _session_active:
            bs.logout()


# ══════════════════════════════════════════════════════════════
# 批量接口
# ══════════════════════════════════════════════════════════════

def batch_financial_data(codes: list[str], max_workers: int = 8) -> dict[str, dict]:
    """
    批量获取财务数据。
    东财版：串行调用，间隔 0.3s，无 TCP 限制，7×24 可用。
    baostock 版：login/logout 提升到 batch 层，遇 BrokenPipe 自动重试。
    """
    results: dict[str, dict] = {}
    total = len(codes)

    if DATA_SOURCE == "baostock":
        import baostock as bs
        if not is_trading_hours():
            print("[baostock] 盘后静默，跳过全部（请在盘中运行）")
            for code in codes:
                results[code] = {"code": code, "source": "baostock", "skipped": True, "reason": "afterhours"}
            return results

        bs.login()
        try:
            for i, code in enumerate(codes):
                retry = 0
                while retry <= 2:
                    try:
                        data = _get_financial_data_baostock(code, _session_active=True)
                        results[code] = data
                        break
                    except Exception as e:
                        err_str = str(e)
                        if any(k in err_str for k in ["Broken pipe", "BrokenPipeError", "Connection"]):
                            retry += 1
                            print(f"  [{i+1}/{total}] {code} 连接异常，重新 login（第{retry}次）")
                            try:
                                bs.logout()
                            except Exception:
                                pass
                            time.sleep(1)
                            bs.login()
                        else:
                            print(f"  [{i+1}/{total}] {code} 失败: {e}")
                            results[code] = {"code": code, "source": "baostock", "error": err_str}
                            break
                else:
                    results[code] = {"code": code, "source": "baostock", "error": "max retries exceeded (Broken pipe)"}
                if (i + 1) % 10 == 0:
                    print(f"  [{i+1}/{total}] 财务数据获取中...")
                time.sleep(0.3)
        finally:
            bs.logout()
    else:
        # 东财版：直接串行
        for i, code in enumerate(codes):
            try:
                results[code] = _get_financial_data_eastmoney(code)
            except Exception as e:
                print(f"  [{i+1}/{total}] {code} 失败: {e}")
                results[code] = {"code": code, "source": "eastmoney", "error": str(e)}
            if (i + 1) % 10 == 0:
                print(f"  [{i+1}/{total}] 财务数据获取中...")
            time.sleep(0.3)

    return results


# ══════════════════════════════════════════════════════════════
# Phase 2 批处理入口
# ══════════════════════════════════════════════════════════════

def run_phase2_batch(
    candidate_pool_path: str = "data/candidate_pool.json",
    regime: str = "neutral",
    top_n: int = 50,
    output_path: str = "data/phase2_results.json",
) -> list[dict]:
    """
    Phase 2 完整流程：
    1. 读取候选池（pre_filter 输出的 JSON）
    2. 批量拉财务数据（东财 HTTPS，无盘中限制）
    3. 调用 batch_garp_score 评分
    4. 输出 Top N 排名到 JSON 文件
    """
    import sys
    import os
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
        "data_source": DATA_SOURCE,
        "results": top_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[Phase2] 输出 Top{top_n} 到 {output_path}（数据源: {DATA_SOURCE}）")
    return top_results


# ══════════════════════════════════════════════════════════════
# 命令行验证入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    from a_stock_supplement import auto_garp_score

    print(f"[数据源] {DATA_SOURCE}")

    for test_code, test_name in [("600519", "贵州茅台"), ("600309", "万华化学")]:
        print(f"\n{'='*50}")
        print(f"{test_name} {test_code}")
        print("=" * 50)

        data = get_financial_data(test_code)

        if data.get("skipped"):
            print(f"  ⚠️  {data.get('reason','盘后')} — 请在盘中（北京时间9:15-15:35）运行")
            continue

        if data.get("error"):
            print(f"  ❌ 获取失败: {data['error']}")
            continue

        print(f"ROE={data.get('roe')} 毛利率={data.get('gross_margin')} 负债率={data.get('debt_ratio')}")
        print(f"EPS CAGR={data.get('eps_cagr_3y')} 营收CAGR={data.get('revenue_cagr_3y')}")
        print(f"6M动量={data.get('momentum_6m_pct')}% 1M动量={data.get('momentum_1m_pct')}%")
        print(f"ROE趋势={data.get('roe_trend')} 财报期={data.get('data_freshness')} 来源={data.get('source')}")

        fin_keys = ["revenue_cagr_3y", "eps_cagr_3y", "roe", "gross_margin", "debt_ratio", "momentum_6m_pct"]
        result = auto_garp_score(
            test_code, regime="neutral",
            **{k: data.get(k) for k in fin_keys}
        )
        print(f"\nGARP总分={result['total_score']} {result['tier']}")
        print(f"G={result['scores']['G']} Q={result['scores']['Q']} V={result['scores']['V']} M={result['scores']['M']} R={result['scores']['R']}")
        for k, v in result["factor_notes"].items():
            print(f"  {k}: {v}")
        print(f"建议: {result['recommendation']}")
