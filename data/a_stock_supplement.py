"""
a_stock_supplement.py
=====================
GARP 框架数据链路补强模块 — 基于 a-stock-data V3.1

🔒 Phase 2 冻结声明（2026-05-21 实测确认，禁止覆盖）：
  - baostock adjustflag=2（前复权K线）：mootdx 不支持前复权，
    GARP 动量因子依赖前复权价，baostock 不得迁移替换。
  - baostock query_profit/growth/balance_data（财务增速）：
    新浪三表接口已失效，字段标准化差，历史深度约20期不足，
    GARP G增长因子依赖多期YOY增速，baostock 财务接口保留不动。
  如需解除冻结，须提供完整替代方案验证报告。

补强方向（并联，不替换现有妙想/MX-Skill）：
  1. 东财 push2 资金流（替代 Tavily 兜底，thsdk 作最终兜底）
  2. 龙虎榜席位（GARP Layer4 风险确认新维度）
  3. 限售解禁日历（风险层补充）
  4. 东财研报（保留妙想，东财并联对比）
  5. 财联社快讯（直连 cls.cn，替代 Tavily 抓取）
  6. 巨潮公告（直连 cninfo，替代原有方案）
  7. MX-StockPick 信号接入预留接口

注意事项：
  - 行业分类口径：东财行业 ≠ 申万/中信，需通过 INDUSTRY_MAP 做口径映射
  - 所有金额统一换算为【万元】，函数内部已处理
  - 所有妙想/MX-Skill 模块保留不变，本模块并联运行
  - 港股/美股标的（如 9992.HK）继续走 yfinance，不经本模块
"""

import hashlib
import json
import os
import re
import requests
import urllib.parse
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, Any
import pandas as pd

# ─────────────────────────────────────────
# 全局配置
# ─────────────────────────────────────────

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# ── Cloudflare Worker 反代配置 ──────────────────────────────────────
# Azure IP（AS8075）被东财 push2/push2his 服务端封锁，需通过 CF Worker 转发。
# 部署 Worker 后，将 PUSH2_PROXY_BASE 设为 Worker URL，留空则直连（直连在 Azure 上不可用）。
#
# Worker 路由规则：
#   /push2/*    → push2.eastmoney.com/*
#   /push2his/* → push2his.eastmoney.com/*
#
# 例：PUSH2_PROXY_BASE = "https://em-proxy.your-name.workers.dev"
#     原始: https://push2.eastmoney.com/api/qt/stock/fflow/kline/get
#     代理: https://em-proxy.your-name.workers.dev/push2/api/qt/stock/fflow/kline/get
#
# Worker 代码见 deploy/cloudflare-worker/eastmoney-proxy.js
import os as _os
PUSH2_PROXY_BASE: str = _os.environ.get("PUSH2_PROXY_BASE", "").rstrip("/")


def _push2_url(path: str) -> str:
    """
    构造 push2.eastmoney.com 的请求 URL。
    有 PUSH2_PROXY_BASE 时走代理，否则直连（Azure 下直连不可用）。
    path 示例："/api/qt/stock/fflow/kline/get"
    """
    if PUSH2_PROXY_BASE:
        return f"{PUSH2_PROXY_BASE}/push2{path}"
    return f"https://push2.eastmoney.com{path}"


def _push2his_url(path: str) -> str:
    """
    构造 push2his.eastmoney.com 的请求 URL。
    有 PUSH2_PROXY_BASE 时走代理，否则直连（Azure 下直连不可用）。
    path 示例："/api/qt/stock/kline/get"
    """
    if PUSH2_PROXY_BASE:
        return f"{PUSH2_PROXY_BASE}/push2his{path}"
    return f"https://push2his.eastmoney.com{path}"

# ── 交易时间判断 ──
def is_trading_hours() -> bool:
    """
    判断当前是否在 A 股交易时间内（北京时间）。
    push2 在盘后重定向到 push2delay，Azure 超时，盘后自动跳过 push2 调用。
    """
    from datetime import datetime, timezone, timedelta
    CST = timezone(timedelta(hours=8))
    now = datetime.now(CST)
    if now.weekday() >= 5:  # 周六/周日
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1535  # 9:15 - 15:35

# 东财行业分类 → 申万一级行业 口径映射表（补充完善）
# 行业分类漂移警告：未映射的行业需人工校验后添加
INDUSTRY_MAP = {
    "银行": "银行",
    "非银金融": "非银金融",
    "医药生物": "医药生物",
    "电子": "电子",
    "计算机": "计算机",
    "通信": "通信",
    "传媒": "传媒",
    "汽车": "汽车",
    "机械设备": "机械设备",
    "电力设备": "电力设备",
    "化工": "基础化工",        # 东财"化工" → 申万"基础化工"
    "食品饮料": "食品饮料",
    "家用电器": "家用电器",
    "建筑材料": "建筑材料",
    "建筑装饰": "建筑装饰",
    "房地产": "房地产",
    "农林牧渔": "农林牧渔",
    "钢铁": "钢铁",
    "有色金属": "有色金属",
    "采掘": "煤炭",             # 东财"采掘" → 申万已拆分，需人工确认
    "纺织服装": "纺织服饰",
    "轻工制造": "轻工制造",
    "交通运输": "交通运输",
    "公用事业": "公用事业",
    "综合": "综合",
}


def normalize_code(code: str) -> str:
    """统一股票代码为纯6位数字"""
    code = code.strip().upper()
    for prefix in ["SH", "SZ", "BJ"]:
        if code.startswith(prefix):
            code = code[2:]
    if "." in code:
        code = code.split(".")[0]
    return code


def get_secid(code: str) -> str:
    """6位代码 → 东财 secid 格式（1.600519 / 0.000858）"""
    c = normalize_code(code)
    if c.startswith(("6", "9")):
        return f"1.{c}"
    elif c.startswith("8"):
        return f"0.{c}"  # 北交所
    else:
        return f"0.{c}"


def eastmoney_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
    retries: int = 3,
) -> list[dict]:
    """东财数据中心统一查询 helper（龙虎榜/解禁/融资融券/大宗/股东户数共用）
    retries: 超时自动重试次数（Azure→东财偶发超时，默认重试3次）
    """
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(
                DATACENTER_URL,
                params=params,
                headers={"User-Agent": UA},
                timeout=20,
            )
            d = r.json()
            if d.get("result") and d["result"].get("data"):
                return d["result"]["data"]
            return []
        except requests.exceptions.Timeout:
            if attempt < retries:
                print(f"[WARN] 东财 datacenter 超时，第{attempt}次重试...")
                time.sleep(2 * attempt)
            else:
                print(f"[ERROR] 东财 datacenter 超时，已重试{retries}次，放弃: {report_name}")
                return []
        except Exception as e:
            print(f"[ERROR] 东财 datacenter 异常: {e}")
            return []


# ─────────────────────────────────────────
# 1. 东财 push2 资金流（替代 Tavily 兜底）
# ─────────────────────────────────────────

def get_fund_flow_minute(code: str, fallback_thsdk: bool = True) -> list[dict]:
    """
    个股分钟级资金流向（当日盘中）。
    盘后自动跳过（push2 盘后重定向 push2delay，Azure 超时属正常架构行为）。
    """
    if not is_trading_hours():
        return []  # 盘后静默，不发请求
    secid = get_secid(code)
    url = _push2_url("/api/qt/stock/fflow/kline/get")
    params = {
        "secid": secid,
        "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        rows = []
        for line in d.get("data", {}).get("klines", []):
            parts = line.split(",")
            if len(parts) >= 6:
                # push2 原始单位：元（每分钟增量）
                # 保留元级精度，汇总层统一换算为万元
                rows.append({
                    "time": parts[0],
                    "main_net_yuan": float(parts[1]),
                    "small_net_yuan": float(parts[2]),
                    "mid_net_yuan": float(parts[3]),
                    "large_net_yuan": float(parts[4]),
                    "super_net_yuan": float(parts[5]),
                })
        if rows:
            return rows
        raise ValueError("push2 返回空数据")
    except Exception as e:
        print(f"[WARN] 东财 push2 资金流失败: {e}")
        if fallback_thsdk:
            return _thsdk_fund_flow_fallback(code)
        return []


def _thsdk_fund_flow_fallback(code: str) -> list[dict]:
    """
    thsdk 资金流兜底（仅在 push2 失败时调用）。
    需要 thsdk 已安装且鉴权有效。
    注意：thsdk 大单定义口径与东财略有差异，使用时需关注。
    """
    try:
        from thsdk import THS
        ths = THS()
        # 调用 big_order_flow（AShare-Overnight-Arb-Trader 核心信号源）
        result = ths.big_order_flow(code)
        # 将 thsdk 字段映射为统一格式（单位均换算为万元）
        rows = []
        for item in result if isinstance(result, list) else []:
            rows.append({
                "time": item.get("time", ""),
                "main_net_yuan": float(item.get("main_net", 0)),
                "large_net_yuan": float(item.get("large_net", 0)),
                "mid_net_yuan": 0.0,
                "small_net_yuan": float(item.get("small_net", 0)),
                "super_net_yuan": 0.0,
                "_source": "thsdk_fallback",
            })
        return rows
    except Exception as e:
        print(f"[ERROR] thsdk 兜底也失败: {e}")
        return []


def get_fund_flow_summary(code: str) -> dict:
    """
    资金流汇总（当日累计），供 GARP Layer4 快速判断。
    返回: {main_total_wan, signal, source}
    signal: 'bullish' / 'bearish' / 'neutral'
    阈值：主力净流入 > +500万 = bullish；< -500万 = bearish
    """
    rows = get_fund_flow_minute(code)
    if not rows:
        return {"main_total_wan": 0, "signal": "neutral", "source": "none"}
    # 元级累加后统一换算为万元
    total_yuan = sum(r["main_net_yuan"] for r in rows)
    total_wan = round(total_yuan / 10000, 1)
    source = rows[0].get("_source", "eastmoney_push2")
    signal = "bullish" if total_wan > 500 else ("bearish" if total_wan < -500 else "neutral")
    return {
        "main_total_wan": total_wan,
        "signal": signal,
        "source": source,
    }


# ─────────────────────────────────────────
# 2. 龙虎榜席位（GARP Layer4 新维度）
# ─────────────────────────────────────────

def get_dragon_tiger(
    code: str,
    trade_date: Optional[str] = None,
    look_back: int = 30,
) -> dict:
    """
    龙虎榜数据聚合。
    trade_date: YYYY-MM-DD，默认今日
    返回: {records, seats, institution, layer4_signal}
    layer4_signal: 'pass' / 'warning' / 'block'
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)).strftime("%Y-%m-%d")

    # 上榜记录
    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{normalize_code(code)}\")",
        page_size=50,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    for row in data:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })

    # 最近上榜的买卖席位 TOP5
    seats = {"buy": [], "sell": []}
    buy_data, sell_data = [], []
    if records:
        latest_date = records[0]["date"]
        c = normalize_code(code)
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{c}\")",
            page_size=10,
            sort_columns="BUY",
            sort_types="-1",
        )
        sell_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{c}\")",
            page_size=10,
            sort_columns="SELL",
            sort_types="-1",
        )
        for row in buy_data[:5]:
            seats["buy"].append({
                "name": row.get("OPERATEDEPT_NAME", ""),
                "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                "net_wan": round((row.get("NET") or 0) / 10000, 1),
            })
        for row in sell_data[:5]:
            seats["sell"].append({
                "name": row.get("OPERATEDEPT_NAME", ""),
                "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                "net_wan": round((row.get("NET") or 0) / 10000, 1),
            })

    # 机构席位统计（OPERATEDEPT_CODE="0"）
    institution = {"buy_wan": 0.0, "sell_wan": 0.0, "net_wan": 0.0}
    for row in buy_data:
        if str(row.get("OPERATEDEPT_CODE", "")) == "0":
            institution["buy_wan"] += (row.get("BUY") or 0) / 10000
    for row in sell_data:
        if str(row.get("OPERATEDEPT_CODE", "")) == "0":
            institution["sell_wan"] += (row.get("SELL") or 0) / 10000
    institution["buy_wan"] = round(institution["buy_wan"], 1)
    institution["sell_wan"] = round(institution["sell_wan"], 1)
    institution["net_wan"] = round(institution["buy_wan"] - institution["sell_wan"], 1)

    # Layer4 信号判断规则：
    #   block   → 机构净卖出 > 5000万 或 近30日上榜>=3次且均为卖出主导
    #   warning → 机构净卖出 500~5000万
    #   pass    → 无上榜 或 机构净买入
    layer4_signal = "pass"
    if institution["net_wan"] < -5000 or (len(records) >= 3 and institution["net_wan"] < 0):
        layer4_signal = "block"
    elif institution["net_wan"] < -500:
        layer4_signal = "warning"

    return {
        "records": records,
        "seats": seats,
        "institution": institution,
        "layer4_signal": layer4_signal,
    }


# ─────────────────────────────────────────
# 3. 限售解禁日历（风险层）
# ─────────────────────────────────────────

def get_lockup_expiry(
    code: str,
    trade_date: Optional[str] = None,
    forward_days: int = 90,
) -> dict:
    """
    限售解禁日历。
    返回: {history, upcoming, risk_label}
    risk_label: 'high' (解禁比例>5%) / 'medium' (1~5%) / 'low' (<1%) / 'none'
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)).strftime("%Y-%m-%d")
    c = normalize_code(code)

    history_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f"(SECURITY_CODE=\"{c}\")",
        page_size=15,
        sort_columns="FREE_DATE",
        sort_types="-1",
    )
    history = [
        {
            "date": str(r.get("FREE_DATE", ""))[:10],
            "type": r.get("LIMITED_STOCK_TYPE", ""),
            "shares": r.get("FREE_SHARES_NUM", 0),
            "ratio_pct": round(float(r.get("FREE_RATIO") or 0), 2),
        }
        for r in history_data
    ]

    upcoming_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f"(SECURITY_CODE=\"{c}\")(FREE_DATE>='{trade_date}')(FREE_DATE<='{end_date}')",
        page_size=20,
        sort_columns="FREE_DATE",
        sort_types="1",
    )
    upcoming = [
        {
            "date": str(r.get("FREE_DATE", ""))[:10],
            "type": r.get("LIMITED_STOCK_TYPE", ""),
            "shares": r.get("FREE_SHARES_NUM", 0),
            "ratio_pct": round(float(r.get("FREE_RATIO") or 0), 2),
        }
        for r in upcoming_data
    ]

    max_ratio = max((u["ratio_pct"] for u in upcoming), default=0)
    if max_ratio >= 5:
        risk_label = "high"
    elif max_ratio >= 1:
        risk_label = "medium"
    elif upcoming:
        risk_label = "low"
    else:
        risk_label = "none"

    return {"history": history, "upcoming": upcoming, "risk_label": risk_label}


# ─────────────────────────────────────────
# 4. 东财研报（妙想并联对比）
# ─────────────────────────────────────────

def get_eastmoney_reports(code: str, max_pages: int = 3) -> list[dict]:
    """
    东财研报列表（与妙想 MX-FinSearch 并联运行，不替换）。
    返回: [{date, org, title, rating, eps_this, eps_next, eps_next2}]
    """
    import re

    REPORT_API = "https://reportapi.eastmoney.com/report/list"
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    all_records = []

    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "50", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": normalize_code(code), "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        try:
            r = session.get(REPORT_API, params=params, timeout=30)
            d = r.json()
            rows = d.get("data") or []
            if not rows:
                break
            for row in rows:
                all_records.append({
                    "date": str(row.get("publishDate", ""))[:10],
                    "org": row.get("orgSName", ""),
                    "title": row.get("title", ""),
                    "rating": row.get("emRatingName", ""),
                    "eps_this": row.get("predictThisYearEps"),
                    "eps_next": row.get("predictNextYearEps"),
                    "eps_next2": row.get("predictNextTwoYearEps"),
                    "industry": row.get("indvInduName", ""),
                    "info_code": row.get("infoCode", ""),
                })
            if page >= (d.get("TotalPage", 1) or 1):
                break
            time.sleep(0.3)
        except Exception as e:
            print(f"[WARN] 东财研报第{page}页失败: {e}")
            break

    return all_records


def compare_reports_with_miaoxiang(
    eastmoney_reports: list[dict],
    miaoxiang_reports: list[dict],
) -> dict:
    """
    东财研报 vs 妙想研报对比（简单摘要，供人工判断）。
    miaoxiang_reports: 妙想 MX-FinSearch 返回的研报列表（格式自适应）

    返回: {em_count, mx_count, rating_diff, eps_consensus}
    rating_diff: 东财最新评级 vs 妙想最新评级是否一致
    """
    em_ratings = [r["rating"] for r in eastmoney_reports if r.get("rating")]
    mx_ratings = [r.get("rating", "") for r in miaoxiang_reports if r.get("rating")]

    em_latest = em_ratings[0] if em_ratings else "N/A"
    mx_latest = mx_ratings[0] if mx_ratings else "N/A"

    # 一致预期 EPS（取东财所有研报的均值）
    eps_values = [
        float(r["eps_next"])
        for r in eastmoney_reports
        if r.get("eps_next") is not None
    ]
    eps_consensus = round(sum(eps_values) / len(eps_values), 3) if eps_values else None

    latest_report_date = eastmoney_reports[0].get("date") if eastmoney_reports else None
    age_days = _days_since(latest_report_date)
    confidence = "⭐⭐⭐⭐⭐"
    if age_days is not None and age_days > 150:
        confidence = "⭐⭐⭐"
    elif age_days is not None and age_days > 90:
        confidence = "⭐⭐⭐⭐"

    return {
        "em_count": len(eastmoney_reports),
        "mx_count": len(miaoxiang_reports),
        "em_latest_rating": em_latest,
        "mx_latest_rating": mx_latest,
        "rating_consistent": em_latest == mx_latest,
        "eps_consensus_from_em": eps_consensus,
        "latest_report_date": latest_report_date,
        "report_age_days": age_days,
        "consensus_confidence": confidence,
    }


# ─────────────────────────────────────────
# 5. 财联社快讯（直连 cls.cn）
# ─────────────────────────────────────────

# ── CLS API v2 签名常量（sv 随前端版本更新，失效时修改此处）──
CLS_SV = "8.7.9"


class ClsApiStale(Exception):
    """CLS API 返回 errno!=0 或 roll_data 为空，说明 sv 版本号可能已过期。"""
    pass


def _cls_make_sign(params: dict) -> str:
    """CLS API 签名：对参数字典按字典序拼接后 SHA1 → MD5。"""
    sorted_items = sorted(params.items(), key=lambda x: x[0])
    query_string = urllib.parse.urlencode(sorted_items)
    sha1_digest = hashlib.sha1(query_string.encode("utf-8")).hexdigest()
    return hashlib.md5(sha1_digest.encode("utf-8")).hexdigest()


def _cls_fetch_primary(page_size: int) -> list[dict]:
    """CLS 新版签名接口（主路）。

    Raises:
        ClsApiStale: errno != 0 或 roll_data 为空（sv 可能过期）。
        requests.RequestException: 网络/HTTP 错误。
    """
    params: dict = {
        "appName": "CailianpressWeb",
        "os": "web",
        "rn": str(page_size),
        "sv": CLS_SV,
    }
    params["sign"] = _cls_make_sign(params)
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.cls.cn/telegraph",
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(
        "https://www.cls.cn/v1/roll/get_roll_list", params=params, headers=headers, timeout=15
    )
    resp.raise_for_status()
    payload = resp.json()

    errno = payload.get("errno", -1)
    roll_data = (payload.get("data") or {}).get("roll_data") or []
    if errno != 0 or not roll_data:
        raise ClsApiStale(
            f"CLS errno={errno}, roll_data_len={len(roll_data)}, sv={CLS_SV}"
        )

    results: list[dict] = []
    for item in roll_data:
        stocks: list[str] = []
        for s in item.get("stock_list") or []:
            code = (s.get("StockID") or s.get("StockCode") or s.get("secu_code") or "").strip()
            digits = "".join(ch for ch in code if ch.isdigit())
            if len(digits) >= 6:
                stocks.append(digits[:6])
        results.append({
            "title": (item.get("title") or "").strip(),
            "content": (item.get("content") or item.get("brief") or "").strip()[:300],
            "time": item.get("ctime") or item.get("modified_time") or 0,
            "stocks": stocks,
        })
    return results


def _sina_fetch_fallback(page_size: int) -> list[dict]:
    """新浪财经快讯 fallback（CLS 主路失败时启用）。

    尝试两个接口（滚动新闻 → 直播 feed），异常静默返回 []。
    """
    headers = {
        "User-Agent": UA,
        "Referer": "https://finance.sina.com.cn/",
        "Accept": "application/json, text/plain, */*",
    }
    code_re = re.compile(r"\b[036]\d{5}\b")

    def _extract_stocks(text: str) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for code in code_re.findall(text or ""):
            if code not in seen:
                seen.add(code)
                result.append(code)
        return result

    def _norm_time(raw) -> int | str:
        if raw is None or raw == "":
            return ""
        try:
            ts = int(raw)
            return ts // 1000 if ts > 10_000_000_000 else ts
        except (ValueError, TypeError):
            return ""

    def _parse_items(items: list) -> list[dict]:
        out: list[dict] = []
        for item in items[:page_size]:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            content = str(
                item.get("intro") or item.get("summary") or item.get("content") or ""
            ).strip()[:300]
            if not (title or content):
                continue
            out.append({
                "title": title,
                "content": content,
                "time": _norm_time(item.get("ctime") or item.get("createtime")),
                "stocks": _extract_stocks(f"{title} {content}"),
            })
        return out

    def _try_url(url: str) -> list[dict]:
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                return []
            text = resp.text.strip()
            # 处理 JSONP 包装
            if text.startswith("(") or ("(" in text[:60] and ")" in text[-5:]):
                start, end = text.find("{"), text.rfind("}")
                if start >= 0 and end > start:
                    text = text[start:end + 1]
            data = json.loads(text)
            if not isinstance(data, dict):
                return []
            items = (
                (data.get("result") or {}).get("data")
                or data.get("data")
                or []
            )
            if not isinstance(items, list):
                return []
            return _parse_items(items)
        except Exception:
            return []

    result = _try_url(
        f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2514&k=&num={page_size}&page=1"
    )
    if result:
        return result
    return _try_url(
        f"https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&page=1&page_size={page_size}&type=1"
    )


def _em_fetch_fallback(page_size: int) -> list[dict]:
    """东方财富快讯 fallback（CLS 和新浪都失败时启用）。

    异常静默返回 []。
    """
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.eastmoney.com/",
        "Accept": "application/json, text/plain, */*",
    }
    code_re = re.compile(r"\b[036]\d{5}\b")

    def _extract_codes(*texts) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for t in texts:
            for m in code_re.findall(str(t) if t else ""):
                if m not in seen:
                    seen.add(m)
                    out.append(m)
        return out

    def _parse_show_time(s) -> int | str:
        if not s:
            return ""
        try:
            return int(time.mktime(time.strptime(str(s).strip(), "%Y-%m-%d %H:%M:%S")))
        except Exception:
            try:
                return int(s)
            except Exception:
                return str(s)

    try:
        params = {
            "client": "web",
            "biz": "web_portal_symbol",
            "fastColumn": "102",
            "pageSize": str(max(1, int(page_size))),
            "pageIndex": "1",
            "order": "1",
            "sortEnd": "",
            "req_trace": str(int(time.time() * 1000)),
        }
        r = requests.get(
            "https://np-listapi.eastmoney.com/comm/web/getFastNewsList",
            params=params, headers=headers, timeout=10,
        )
        if r.status_code == 200:
            d = r.json()
            items = ((d.get("data") or {}).get("fastNewsList") or [])
            rows: list[dict] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "").strip()
                summary = (item.get("summary") or item.get("digest") or "").strip()
                # 优先使用接口直接返回的 stockList
                api_stocks: list[str] = []
                for s in item.get("stockList") or []:
                    if isinstance(s, str):
                        m = code_re.search(s)
                        if m:
                            api_stocks.append(m.group(0))
                    elif isinstance(s, dict):
                        for key in ("StockCode", "stockCode", "code", "secCode"):
                            v = s.get(key)
                            if v:
                                m = code_re.search(str(v))
                                if m:
                                    api_stocks.append(m.group(0))
                                    break
                stocks = api_stocks if api_stocks else _extract_codes(title, summary)
                # 去重保序
                seen: set[str] = set()
                stocks = [c for c in stocks if not (c in seen or seen.add(c))]  # type: ignore
                rows.append({
                    "title": title,
                    "content": summary[:300],
                    "time": _parse_show_time(
                        item.get("showTime") or item.get("realSort") or ""
                    ),
                    "stocks": stocks,
                })
            if rows:
                return rows
    except Exception:
        pass
    return []


def get_cls_telegraph(page_size: int = 50) -> list[dict]:
    """财联社电报（全市场实时快讯），含三级 fallback。

    数据链路：
      1. CLS /api/cache（新版签名，主路）
      2. 新浪财经滚动快讯（fallback-1）
      3. 东方财富 fastNews（fallback-2）
      4. 静默返回 []（全部失败时，不影响龙虎榜/限售解禁判断）

    返回: [{title, content, time, stocks}]
      stocks: 6位 A 股代码列表

    sv 版本号变更时更新 CLS_SV 常量即可，无需改动此函数。
    """
    try:
        return _cls_fetch_primary(page_size)
    except ClsApiStale:
        # sv 过期或接口结构变更 → 走 fallback
        pass
    except Exception:
        # 网络/HTTP 错误 → 走 fallback
        pass

    result = _sina_fetch_fallback(page_size)
    if result:
        return result

    result = _em_fetch_fallback(page_size)
    if result:
        return result

    return []


def filter_cls_by_holdings(
    news: list[dict],
    holdings: list[str],
) -> list[dict]:
    """
    过滤出与持仓相关的财联社快讯。
    holdings: 持仓股票代码列表（纯6位）
    """
    holding_set = set(normalize_code(c) for c in holdings)
    return [n for n in news if holding_set & set(n.get("stocks", []))]


def cls_keyword_alert(
    news: list[dict],
    alert_keywords: Optional[list[str]] = None,
) -> list[dict]:
    """
    财联社关键词风险告警过滤。
    alert_keywords: 触发告警的关键词，默认使用内置黑名单
    """
    if alert_keywords is None:
        alert_keywords = [
            "立案调查", "ST", "退市", "减持计划", "业绩预警", "亏损",
            "监管函", "处罚", "违规", "爆雷", "流动性危机",
        ]
    alerts = []
    for item in news:
        text = item.get("title", "") + item.get("content", "")
        matched = [kw for kw in alert_keywords if kw in text]
        if matched:
            alerts.append({**item, "matched_keywords": matched})
    return alerts


# ─────────────────────────────────────────
# 6. 巨潮公告（直连 cninfo）
# ─────────────────────────────────────────

def _ts_to_date(ts) -> str:
    """毫秒时间戳 → YYYY-MM-DD（兼容 int 和字符串格式）"""
    if ts is None:
        return ""
    try:
        ts_int = int(ts)
        return datetime.fromtimestamp(ts_int / 1000).strftime("%Y-%m-%d")
    except Exception:
        return str(ts)[:10]


def get_cninfo_announcements(
    code: str,
    page_size: int = 20,
    ann_type: str = "A",
) -> list[dict]:
    """
    巨潮公告全量查询（沪深北交所）。
    ann_type: 'A'=全部 / 'RB'=年报 / 'SB'=半年报 / 'QB'=季报 / 'D'=分红
    注意：stock 参数格式为 code,orgId（V3.1 修复）
          上交所: gssh{code}，深交所: gssz{code}
    返回: [{date, title, url, type}]
    """
    c = normalize_code(code)
    # 判断交易所（V3.1 修复：orgId 格式为 gssh0{code} / gssz0{code}）
    if c.startswith(("6", "9")):
        org_id = f"gssh0{c}"
    else:
        org_id = f"gssz0{c}"

    url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    data = {
        "stock": f"{c},{org_id}",
        "tabName": "fulltext",
        "pageSize": str(page_size),
        "pageNum": "1",
        "column": "sse" if c.startswith(("6", "9")) else "szse",
        "category": ann_type,
        "plate": "",
        "seDate": "",
        "searchkey": "",
        "secid": "",
        "sortName": "time",
        "sortType": "desc",
        "isHLtitle": "true",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.cninfo.com.cn/",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        r = requests.post(url, data=data, headers=headers, timeout=15)
        d = r.json()
        rows = []
        for row in d.get("announcements") or []:
            rows.append({
                "date": _ts_to_date(row.get("announcementTime")),
                "title": row.get("announcementTitle", ""),
                "url": f"https://static.cninfo.com.cn/{row.get('adjunctUrl', '')}",
                "type": row.get("announcementTypeName", ""),
                "id": row.get("announcementId", ""),
            })
        return rows
    except Exception as e:
        print(f"[ERROR] 巨潮公告获取失败: {e}")
        return []


# ─────────────────────────────────────────
# 7. MX-StockPick 信号接入（预留接口）
# ─────────────────────────────────────────

def get_mx_stockpick_signal(code: str) -> dict:
    """
    妙想 MX-StockPick 选股信号接入（预留接口）。
    实际调用逻辑由 MX-Skill 模块实现，此处仅做格式规范。

    返回标准格式（与本模块其他信号统一）:
    {
        "code": str,
        "mx_score": float,          # 妙想评分（0-100）
        "mx_signal": str,           # 'strong_buy'/'buy'/'hold'/'sell'/'strong_sell'
        "mx_reason": str,           # 推荐理由摘要
        "mx_target_price": float,   # 目标价
        "source": "mx_stockpick"
    }
    """
    # TODO: 集成 MX-Skill 实际调用
    # from mx_skill import MXStockPick
    # result = MXStockPick().get_signal(code)
    raise NotImplementedError(
        "MX-StockPick 信号接口预留，请在 MX-Skill 模块中实现并调用本函数"
    )


# ─────────────────────────────────────────
# 8. GARP Layer4 风险确认层集成入口
# ─────────────────────────────────────────

def layer4_risk_check(
    code: str,
    trade_date: Optional[str] = None,
) -> dict:
    """
    GARP Layer4 风险确认层综合检查（补强版）。
    整合：资金流信号 + 龙虎榜 + 限售解禁 + 财联社告警

    返回: {
        code, fund_flow, dragon_tiger, lockup,
        cls_alerts, overall_signal
    }
    overall_signal: 'pass' / 'caution' / 'block'
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    # 并发获取（串行版本，生产可改为 ThreadPoolExecutor）
    fund_flow = get_fund_flow_summary(code)
    dragon_tiger = get_dragon_tiger(code, trade_date)
    lockup = get_lockup_expiry(code, trade_date)
    cls_news = get_cls_telegraph(50)
    c_norm = normalize_code(code)
    cls_alerts = cls_keyword_alert(
        filter_cls_by_holdings(cls_news, [c_norm])
    )

    # 综合判断
    block_reasons = []
    caution_reasons = []

    if dragon_tiger["layer4_signal"] == "block":
        block_reasons.append("龙虎榜机构大幅净卖出")
    elif dragon_tiger["layer4_signal"] == "warning":
        caution_reasons.append("龙虎榜机构小幅净卖出")

    if lockup["risk_label"] == "high":
        block_reasons.append(f"限售解禁比例>{5}%（高风险）")
    elif lockup["risk_label"] == "medium":
        caution_reasons.append("限售解禁比例1-5%（中风险）")

    if fund_flow["signal"] == "bearish" and fund_flow["main_total_wan"] < -5000:
        yi = abs(fund_flow["main_total_wan"]) / 10000
        caution_reasons.append(f"主力资金净流出 {yi:.1f}亿")

    if cls_alerts:
        keywords = [kw for a in cls_alerts for kw in a.get("matched_keywords", [])]
        block_reasons.append(f"财联社风险快讯: {', '.join(set(keywords))}")

    if block_reasons:
        overall = "block"
    elif caution_reasons:
        overall = "caution"
    else:
        overall = "pass"

    return {
        "code": code,
        "trade_date": trade_date,
        "fund_flow": fund_flow,
        "dragon_tiger": {
            "appearances_30d": len(dragon_tiger["records"]),
            "institution_net_wan": dragon_tiger["institution"]["net_wan"],
            "layer4_signal": dragon_tiger["layer4_signal"],
        },
        "lockup": {
            "upcoming_count": len(lockup["upcoming"]),
            "max_ratio_pct": max((u["ratio_pct"] for u in lockup["upcoming"]), default=0),
            "risk_label": lockup["risk_label"],
        },
        "cls_alerts": cls_alerts[:3],  # 最多返回3条
        "block_reasons": block_reasons,
        "caution_reasons": caution_reasons,
        "overall_signal": overall,
    }


# ─────────────────────────────────────────
# 8. AI 智能选股评分（轻量版 auto_garp_score）
# ─────────────────────────────────────────

# 五因子动态权重矩阵（与 market-regime.md 完全对齐）
REGIME_WEIGHTS = {
    "deep_bear":   {"G": 0.15, "Q": 0.45, "V": 0.25, "M": 0.05, "R": 0.10},
    "bear":        {"G": 0.20, "Q": 0.40, "V": 0.20, "M": 0.10, "R": 0.10},
    "neutral":     {"G": 0.20, "Q": 0.30, "V": 0.15, "M": 0.25, "R": 0.10},  # v3.0 默认：M提权
    "bull":        {"G": 0.25, "Q": 0.25, "V": 0.10, "M": 0.30, "R": 0.10},
    "accelerating_bull": {"G": 0.25, "Q": 0.20, "V": 0.10, "M": 0.35, "R": 0.10},
    "bubble":      {"G": 0.10, "Q": 0.35, "V": 0.30, "M": 0.15, "R": 0.10},  # 状态5b：过热/泡沫预警
}

REGIME_ALIASES = {
    "5b": "bubble",
    "overheat": "bubble",
    "overheated": "bubble",
    "hot": "bubble",
    "泡沫": "bubble",
    "过热": "bubble",
    "过热预警": "bubble",
    "bubble_warning": "bubble",
    "super_bull": "accelerating_bull",
    "牛市加速": "accelerating_bull",
}

def normalize_regime(regime: Optional[str]) -> str:
    """Normalize market regime aliases to REGIME_WEIGHTS keys."""
    key = str(regime or "neutral").strip()
    lower = key.lower()
    return REGIME_ALIASES.get(key) or REGIME_ALIASES.get(lower) or (lower if lower in REGIME_WEIGHTS else "neutral")


def _canonical_regime(regime: Optional[str]) -> tuple[str, Optional[str]]:
    raw = str(regime or "neutral").strip()
    canonical = normalize_regime(raw)
    note = None
    if canonical != raw:
        note = f"市场状态{raw}映射为{canonical}权重"
    if canonical == "bubble":
        note = (note + "；" if note else "") + "状态5b过热预警：V权重上调为刹车，M/G降权"
    return canonical, note


def _parse_date(value) -> Optional[datetime]:
    """解析 YYYY-MM-DD / YYYY-MM / ISO 日期；失败返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:len(datetime.now().strftime(fmt))], fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _days_since(value) -> Optional[int]:
    dt = _parse_date(value)
    if dt is None:
        return None
    return (datetime.now() - dt).days


def check_data_freshness(candidate: dict) -> dict:
    """检查候选标的数据新鲜度，过期数据降级或触发重取。

    - G/Q/V数据：超过季报周期(90天)标注⚠️
    - M动量：超过7天标注需重新计算
    - 研报一致预期：超过150天降级为⭐⭐⭐
    """
    checked = dict(candidate or {})
    freshness = dict(checked.get("freshness", {}) or {})
    flags = list(checked.get("freshness_flags", []) or [])

    gqv_asof = (
        checked.get("gqv_asof") or checked.get("financial_asof") or
        checked.get("data_freshness") or checked.get("report_date")
    )
    gqv_age = _days_since(gqv_asof)
    freshness["gqv_age_days"] = gqv_age
    if gqv_age is None:
        flags.append("⚠️ G/Q/V数据日期缺失")
    elif gqv_age > 90:
        flags.append(f"⚠️ G/Q/V数据超过90天({gqv_age}天)")

    momentum_asof = checked.get("momentum_asof") or checked.get("m_asof")
    m_age = _days_since(momentum_asof)
    freshness["momentum_age_days"] = m_age
    if m_age is None:
        flags.append("⚠️ M动量日期缺失，需重新计算")
        checked["momentum_needs_refresh"] = True
    elif m_age > 7:
        flags.append(f"⚠️ M动量超过7天({m_age}天)，需重新计算")
        checked["momentum_needs_refresh"] = True
    else:
        checked["momentum_needs_refresh"] = False

    consensus_asof = (
        checked.get("consensus_asof") or checked.get("report_asof") or
        checked.get("latest_report_date")
    )
    consensus_age = _days_since(consensus_asof)
    freshness["consensus_age_days"] = consensus_age
    if consensus_age is not None and consensus_age > 150:
        flags.append(f"⚠️ 研报一致预期超过150天({consensus_age}天)，置信度降级为⭐⭐⭐")
        checked["consensus_confidence"] = "⭐⭐⭐"
        if checked.get("report_rating_trend") in ("upgrade", "downgrade"):
            checked["report_rating_trend"] = "stable"
    elif consensus_age is not None and consensus_age > 90:
        flags.append(f"⚠️ 研报一致预期超过90天({consensus_age}天)")

    checked["freshness"] = freshness
    checked["freshness_flags"] = list(dict.fromkeys(flags))
    return checked


def _linear_slope(values: list[float]) -> Optional[float]:
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    xbar = sum(xs) / n
    ybar = sum(values) / n
    denom = sum((x - xbar) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - xbar) * (y - ybar) for x, y in zip(xs, values)) / denom


def is_overheat_bubble_warning(
    pe_percentile: Optional[float],
    erp_pct: Optional[float],
    broad_index_1m_return_pct: Optional[float] = None,
    require_index_surge: bool = False,
) -> bool:
    """v3.0 状态5b：PE分位>90% AND ERP<0.5%，可选叠加宽基1月涨幅>20%。"""
    if pe_percentile is None or erp_pct is None:
        return False
    hot_valuation = pe_percentile > 90 and erp_pct < 0.5
    if not hot_valuation:
        return False
    if require_index_surge:
        return broad_index_1m_return_pct is not None and broad_index_1m_return_pct > 20
    return True


def detect_market_regime(
    pe_percentile: Optional[float] = None,
    north_10d_flow_yi: Optional[float] = None,
    volatility_pct: Optional[float] = None,
    erp_pct: Optional[float] = None,
    broad_index_1m_return_pct: Optional[float] = None,
) -> str:
    """轻量市场状态判断；优先识别5b过热/泡沫预警，其余按四变量投票回落。"""
    if is_overheat_bubble_warning(pe_percentile, erp_pct, broad_index_1m_return_pct):
        return "bubble"
    votes: list[str] = []
    if pe_percentile is not None:
        if pe_percentile < 30: votes.append("deep_bear")
        elif pe_percentile < 50: votes.append("bear")
        elif pe_percentile < 70: votes.append("neutral")
        elif pe_percentile < 85: votes.append("bull")
        else: votes.append("accelerating_bull")
    if north_10d_flow_yi is not None:
        if north_10d_flow_yi < -200: votes.append("deep_bear")
        elif north_10d_flow_yi < -50: votes.append("bear")
        elif north_10d_flow_yi <= 50: votes.append("neutral")
        elif north_10d_flow_yi <= 200: votes.append("bull")
        else: votes.append("accelerating_bull")
    if volatility_pct is not None:
        if volatility_pct > 35: votes.append("deep_bear")
        elif volatility_pct > 25: votes.append("bear")
        elif volatility_pct >= 15: votes.append("neutral")
        else: votes.append("accelerating_bull")
    if erp_pct is not None:
        if erp_pct > 6: votes.append("deep_bear")
        elif erp_pct > 4.5: votes.append("bear")
        elif erp_pct >= 3: votes.append("neutral")
        elif erp_pct >= 2: votes.append("bull")
        else: votes.append("accelerating_bull")
    if not votes:
        return "neutral"
    counts = {v: votes.count(v) for v in set(votes)}
    best, count = max(counts.items(), key=lambda kv: kv[1])
    if count >= 2:
        return best
    return normalize_regime(votes[0])


def _extract_jsonp(payload: str) -> Any:
    """解析东财普通 JSON 或 JSONP。"""
    import json
    text = payload.strip()
    if "(" in text and text.endswith(")"):
        text = text[text.find("(") + 1:-1]
    return json.loads(text)


def _to_float(value: Any) -> Optional[float]:
    """稳健数字转换，兼容东财 '-' / None / 字符串。"""
    if value is None or value == "" or value == "-":
        return None
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def get_north_flow_slope(code: Optional[str] = None, days: int = 20) -> Optional[float]:
    """
    获取北向资金近20日净流入斜率（亿元/天）。

    数据源：东方财富北向资金 HTTP 接口。优先 datacenter 历史日频，
    备用 push2his 历史 K 线，再备用 push2 实时分钟 JSONP。
    返回：float（正=净流入加速，负=净流出/流入减速），None=不可用。
    `code` 预留给未来个股级北向持仓扩展；当前口径为市场级北向净流入趋势。
    """
    _ = code
    headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/hsgtcg/"}

    history_candidates = [
        {
            "reportName": "RPT_MUTUAL_DEAL_HISTORY",
            "columns": "ALL",
            "pageNumber": "1",
            "pageSize": "30",
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        },
        {
            "reportName": "RPT_NORTH_NETFLOWIN",
            "columns": "ALL",
            "pageNumber": "1",
            "pageSize": "30",
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        },
    ]
    flow_keys = (
        "NET_BUY_AMT", "NETBUYAMT", "NET_BUY_AMOUNT", "NET_BUY_AMT_SHSZ",
        "BUY_AMT", "NET_FLOW", "NETFLOW", "HGT_NET_AMT", "SGT_NET_AMT",
        "NORTH_NET_INFLOW", "VALUE",
    )
    date_keys = ("TRADE_DATE", "TRADEDATE", "DATE", "TRADE_DATE_STR")

    for params in history_candidates:
        try:
            r = requests.get(DATACENTER_URL, params=params, headers=headers, timeout=12)
            d = _extract_jsonp(r.text)
            rows = (((d or {}).get("result") or {}).get("data") or [])
            parsed: list[tuple[str, float]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                val = None
                for key in flow_keys:
                    if key in row:
                        val = _to_float(row.get(key))
                        if val is not None:
                            break
                if val is None:
                    continue
                if abs(val) > 10000:  # 元 → 亿元
                    val = val / 100000000
                date = next((str(row.get(k)) for k in date_keys if row.get(k)), "")
                parsed.append((date, val))
            if len(parsed) >= 2:
                parsed.sort(key=lambda x: x[0])
                slope = _linear_slope([v for _, v in parsed[-days:]])
                return round(slope, 3) if slope is not None else None
        except Exception as e:
            print(f"[WARN] 北向历史资金接口不可用: {e}")

    try:
        lmt = max(days + 5, 25)
        url = _push2his_url("/api/qt/kamt.kline/get")
        params = {
            "fields1": "f1,f2,f3,f4",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "klt": "101",
            "lmt": str(lmt),
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = _extract_jsonp(r.text)
        klines = (d.get("data") or {}).get("klines") or []
        flows: list[float] = []
        for line in klines[-lmt:]:
            nums = [_to_float(item) for item in str(line).split(",")[1:]]
            nums = [x for x in nums if x is not None]
            if nums:
                flows.append(nums[2] if len(nums) >= 3 else nums[-1])
        slope = _linear_slope(flows[-days:])
        if slope is not None:
            return round(slope, 3)
    except Exception as e:
        print(f"[WARN] 北向push2his资金接口不可用: {e}")

    try:
        cb = f"jQuery{int(time.time() * 1000)}"
        url = _push2_url("/api/qt/kamt.rtmin/get")
        params = {
            "fields1": "f1,f2,f3,f4",
            "fields2": "f51,f52",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "cb": cb,
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = _extract_jsonp(r.text)
        data = (d or {}).get("data") or {}
        trends = data.get("s2n") or data.get("hk2sh") or data.get("hk2sz") or data.get("trends") or []
        values = []
        for item in trends:
            parts = item.split(",") if isinstance(item, str) else item
            if isinstance(parts, (list, tuple)) and len(parts) >= 2:
                val = _to_float(parts[1])
                if val is not None:
                    if abs(val) > 10000:
                        val = val / 100000000
                    values.append(val)
        if len(values) >= 2:
            minute_slope = _linear_slope(values[-240:])
            return round(minute_slope * 240, 3) if minute_slope is not None else None
    except Exception as e:
        print(f"[WARN] 北向实时资金接口不可用: {e}")

    # ── 层4 fallback：本地日频缓存（每次成功获取当日数据时写入，积累20日后可计算斜率）──
    cached_slope = get_north_flow_slope_from_cache(days=days)
    if cached_slope is not None:
        print(f"[INFO] 北向资金斜率来自本地缓存: {cached_slope} 亿/天")
        return cached_slope

    return None


_NORTH_FLOW_CACHE_PATH = _os.path.join(_os.path.dirname(__file__), "north_flow_cache.json")


def _load_north_flow_cache() -> dict:
    """加载北向资金日频缓存，格式 {日期: 亿元净流入}。"""
    if not _os.path.exists(_NORTH_FLOW_CACHE_PATH):
        return {}
    try:
        with open(_NORTH_FLOW_CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_north_flow_cache(cache: dict) -> None:
    """持久化北向资金日频缓存，保留最近60个交易日。"""
    try:
        # 只保留最近60条
        if len(cache) > 60:
            keys = sorted(cache.keys())[-60:]
            cache = {k: cache[k] for k in keys}
        with open(_NORTH_FLOW_CACHE_PATH, "w") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 北向缓存写入失败: {e}")


def record_north_flow_today(net_flow_yi: float) -> None:
    """
    将今日北向净流入（亿元）写入本地缓存。
    应在每日收盘后调用（如 cron 或 run_pre_filter 末尾）。
    正数=净流入，负数=净流出。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    cache = _load_north_flow_cache()
    cache[today] = round(float(net_flow_yi), 2)
    _save_north_flow_cache(cache)


def get_north_flow_slope_from_cache(days: int = 20) -> Optional[float]:
    """
    从本地缓存计算北向资金近N日净流入斜率（亿元/天）。
    需要提前通过 record_north_flow_today() 积累数据。
    数据不足时返回 None。
    """
    cache = _load_north_flow_cache()
    if not cache:
        return None
    sorted_items = sorted(cache.items())  # 按日期升序
    values = [v for _, v in sorted_items[-days:]]
    if len(values) < 5:  # 少于5个数据点，斜率不可信
        return None
    slope = _linear_slope(values)
    return round(slope, 3) if slope is not None else None


def get_today_north_net_flow() -> Optional[float]:
    """
    获取今日北向资金累计净流入（亿元）。
    使用东财 kamt.rtmin（实时分钟级）累加得到当日净流入，
    同时写入本地缓存供 get_north_flow_slope 使用。
    """
    headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/hsgtcg/"}
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        url = _push2_url("/api/qt/kamt.rtmin/get")
        params = {
            "fields1": "f1,f2,f3,f4",
            "fields2": "f51,f52",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json().get("data") or {}
        # n2s = 北向资金（港资→A股）分钟净流入；s2n = 南向
        # 格式: ["9:30,净流入额(万元)", ...] 累计值（每分钟刷新，最后一条是当日累计）
        n2s = d.get("n2s") or []
        if n2s:
            last = n2s[-1]
            parts = last.split(",")
            if len(parts) >= 2:
                val_wan = _to_float(parts[1])
                if val_wan is not None:
                    # 万元→亿元（东财 n2s 最后一条是当日港资净买入A股累计，万元单位）
                    net_flow_yi = round(val_wan / 10000, 2)
                    record_north_flow_today(net_flow_yi)  # 写入缓存
                    return net_flow_yi
    except Exception as e:
        print(f"[WARN] 获取今日北向净流入失败: {e}")
    # kamt.kline 备用（使用沪股通+深股通净额字段）
    try:
        url2 = _push2his_url("/api/qt/kamt.kline/get")
        params2 = {"fields1": "f1,f2,f3,f4", "fields2": "f51,f52,f53,f54", "klt": "101", "lmt": "5",
                   "ut": "b2884a393a59ad64002292a3e90d46a5"}
        r2 = requests.get(url2, params=params2, headers=headers, timeout=10)
        d2 = r2.json().get("data") or {}
        hk2sh = d2.get("hk2sh") or []
        hk2sz = d2.get("hk2sz") or []
        net_total = 0.0
        found_today = False
        for lines, label in [(hk2sh, "沪"), (hk2sz, "深")]:
            for line in lines:
                parts = line.split(",")
                if len(parts) >= 4 and parts[0] == today:
                    net_wan = _to_float(parts[3])  # 第4字段=净额(万元)
                    if net_wan is not None:
                        net_total += net_wan
                        found_today = True
        if found_today:
            net_flow_yi = round(net_total / 10000, 2)
            record_north_flow_today(net_flow_yi)
            return net_flow_yi
    except Exception as e:
        print(f"[WARN] kamt.kline 北向净流入获取失败: {e}")
    return None


# ════════════════════════════════════════════════════════════════════
# v3.0 产业链传导动量计算
# ════════════════════════════════════════════════════════════════════

# 产业链传导图谱：下游龙头 → 中游平台 → 上游材料
# 简化映射：行业代码 → 上游依赖产业链代码
# 下游择优态势市场 = AI算力(光模块中高笤10,24)/电力设备(30)/车载送(28)
# 中游层 = PCB(11)+CCL+模块岁数(24)
# 上游材料层 = 精密陶瓷(10)+区域靨(19)+石英顺材料(17)+有色冶炼(14)
_CHAIN_UPSTREAM_MAP: dict[str, list[str]] = {
    # 下游光模块/CPO→中游PCB/CCL→上游精密陶瓷/石英/纤维
    "24": ["11", "10", "17", "19"],  # 电子局很高
    # 下游新能源汽车→中游电子元器件→上游精密刻度/磁性材料
    "28": ["24", "10", "14"],
    # 下游电力设备→上游精密金属/功能材料
    "30": ["14", "19", "10"],
    # 下游工控/机器人→中游专用设备→上游特种陶瓷/贵金属
    "26": ["10", "25", "14"],
}

# 下游市场景气代表标的：用主力资金流入委托产业链优势。
# 当 `code` 的行业代码属于某条产业链的上游层，且下游层标的资金有流入，则上游标的得分拐弗。


def compute_industry_chain_score(
    code: str,
    industry_code: Optional[Any],
    fund_flow_signal: str = "neutral",
) -> Optional[float]:
    """
    计算个股的产业链传导动量得分（0-100）。

    逻辑：
    1. 判断该行业代码是否为某一产业链的上游。
    2. 找到对应的下游行业代码。
    3. 用下游行业内目标标的的资金流入信号作为传导工具。
    4. 当下游多标的资金流入“投票”，上游标的得高分（传导延迟效应）。

    当前实现：轻量版，用当前标的自身资金流信号 + 下游层行业代码则利(将来接入下游龙头资金流)。
    返回 None 则 _score_m 回落到研报评级兴容模式。
    """
    ind = str(industry_code).strip() if industry_code is not None else None
    if ind is None:
        return None

    # 判断是否属于某条产业链的上游
    is_upstream = False
    downstream_codes: list[str] = []
    for downstream_code, upstream_codes in _CHAIN_UPSTREAM_MAP.items():
        if ind in upstream_codes:
            is_upstream = True
            downstream_codes.append(downstream_code)

    # 评分逻辑：上游标的用下游行业局势 + 自身资金流
    if is_upstream:
        # 下游行业处于高景气层：传导得分拐弗
        # 当前简化：下游层优势 = 下游行业代码属于已知突破赛道
        hot_downstream = {"24", "30", "26", "28"}  # 光模块/电力/工控/汽车
        hot_count = len([c for c in downstream_codes if c in hot_downstream])
        if fund_flow_signal == "bullish":
            base = 80.0 + hot_count * 5  # 自身资金+下游局势双共振
        elif fund_flow_signal == "bearish":
            base = 35.0  # 就算是上游，如果自身资金流出，传导信号弱
        else:
            base = 58.0 + hot_count * 4  # 中性主力但下游局势加分
        return round(min(100.0, base), 1)
    else:
        # 不属于已知产业链上游，返回 None → _score_m 回落研报兼容模式
        return None


# PEG 阈值（与 market-regime.md §6.1 对齐）
PEG_THRESHOLDS = {
    "deep_bear":  {"good": 0.5, "ok": 0.7,  "max": 1.0},
    "bear":       {"good": 0.7, "ok": 1.0,  "max": 1.2},
    "neutral":    {"good": 1.0, "ok": 1.3,  "max": 1.5},
    "bull":       {"good": 1.2, "ok": 1.5,  "max": 1.8},
    "bubble":     {"good": 1.5, "ok": 1.8,  "max": 2.2},
}


def _score_g(revenue_cagr_3y: Optional[float],
             eps_cagr_3y: Optional[float],
             consensus_eps_growth: Optional[float]) -> tuple[float, str]:
    """
    G 成长因子评分（0-100）。
    G_adjusted = min(历史3年CAGR×0.70, 券商预期×0.80)
    """
    candidates = []
    if revenue_cagr_3y is not None:
        candidates.append(revenue_cagr_3y * 0.70)
    if eps_cagr_3y is not None:
        candidates.append(eps_cagr_3y * 0.70)
    if consensus_eps_growth is not None:
        candidates.append(consensus_eps_growth * 0.80)

    if not candidates:
        return 50.0, "无增速数据，给中性分50"

    g_adjusted = min(candidates)

    if g_adjusted >= 30:   score, note = 95, f"G_adj={g_adjusted:.1f}% 高成长"
    elif g_adjusted >= 20: score, note = 85, f"G_adj={g_adjusted:.1f}% 优质成长"
    elif g_adjusted >= 15: score, note = 75, f"G_adj={g_adjusted:.1f}% 中高成长"
    elif g_adjusted >= 10: score, note = 65, f"G_adj={g_adjusted:.1f}% 中等成长"
    elif g_adjusted >= 5:  score, note = 50, f"G_adj={g_adjusted:.1f}% 低成长"
    elif g_adjusted >= 0:  score, note = 35, f"G_adj={g_adjusted:.1f}% 微增长"
    else:                  score, note = 15, f"G_adj={g_adjusted:.1f}% 负增长"

    return float(score), note



CONSUMER_MEDICAL_INDUSTRY_CODES = {"15", "20", "37", "49"}
SCARCE_TECH_MANUFACTURING_CODES = {"10", "11", "13", "14", "17", "24"}
SCARCITY_PREMIUMS = {
    "unique": 1.50, "global_unique": 1.50, "domestic_unique": 1.50,
    "唯一": 1.50, "全球唯一": 1.50, "国内唯一": 1.50,
    "2-3": 0.80, "2_3": 0.80, "2-3家": 0.80, "oligopoly": 0.80, "寡头": 0.80,
    "top5": 0.40, "within5": 0.40, "5家以内": 0.40,
    "competitive": 0.0, "充分竞争": 0.0, "none": 0.0,
}

def _scarcity_subscore_from_slope(domestic_substitution_slope: Optional[float]) -> Optional[float]:
    """国产替代率提升斜率子分：近8季度市占率Δ>5pct满分；下滑0分。"""
    if domestic_substitution_slope is None:
        return None
    slope = float(domestic_substitution_slope)
    if slope <= 0:
        return 0.0
    if slope >= 5:
        return 100.0
    return round(slope / 5 * 100, 1)


def _scarcity_subscore_from_replacement_cost(replacement_cost_to_mcap: Optional[float]) -> Optional[float]:
    """重置成本/市值比子分：>2=100，1-2=70，<1=40。"""
    if replacement_cost_to_mcap is None:
        return None
    ratio = float(replacement_cost_to_mcap)
    if ratio > 2.0:
        return 100.0
    if ratio >= 1.0:
        return 70.0
    return 40.0


def _scarcity_subscore_from_irreplaceability(customer_irreplaceability: Optional[Any]) -> Optional[float]:
    """客户切换成本/不可替代性子分；支持人工数值或标签，不自动臆造。"""
    if customer_irreplaceability is None:
        return None
    if isinstance(customer_irreplaceability, (int, float)):
        return max(0.0, min(100.0, float(customer_irreplaceability)))
    label = str(customer_irreplaceability).strip().lower()
    if label in {"unique", "global_unique", "domestic_unique", "唯一", "全球唯一", "国内唯一"}:
        return 100.0
    if label in {"2-3", "2_3", "2-3家", "oligopoly", "寡头", "少数几家"}:
        return 70.0
    if label in {"competitive", "充分竞争", "可替代", "weak"}:
        return 30.0
    return 50.0


def calc_scarcity_score(
    domestic_substitution_slope: Optional[float] = None,
    replacement_cost_to_mcap: Optional[float] = None,
    customer_irreplaceability: Optional[Any] = None,
) -> tuple[float, str]:
    """v3.0 稀缺性评分 skeleton：三子指标缺失时各自按中性50计分。"""
    raw_subs = [
        ("国产替代率提升斜率", _scarcity_subscore_from_slope(domestic_substitution_slope)),
        ("重置成本/市值比", _scarcity_subscore_from_replacement_cost(replacement_cost_to_mcap)),
        ("客户切换成本/不可替代性", _scarcity_subscore_from_irreplaceability(customer_irreplaceability)),
    ]
    subs = [(name, 50.0 if score is None else score) for name, score in raw_subs]
    missing = [name for name, score in raw_subs if score is None]
    score = round(sum(score for _, score in subs) / len(subs), 1)
    note = "稀缺性=" + ";".join(f"{name}{score:.0f}" for name, score in subs)
    if missing:
        note += " | 缺失按中性50:" + ",".join(missing)
    return score, note

def _scarcity_premium(scarcity_tier: Optional[Any]) -> tuple[float, str]:
    if scarcity_tier is None:
        return 0.0, "充分竞争/未标注"
    if isinstance(scarcity_tier, (int, float)):
        val = float(scarcity_tier)
        if val >= 90: return 1.50, "唯一(数值映射)"
        if val >= 70: return 0.80, "2-3家(数值映射)"
        if val >= 55: return 0.40, "5家以内(数值映射)"
        return 0.0, "充分竞争(数值映射)"
    label = str(scarcity_tier).strip()
    return SCARCITY_PREMIUMS.get(label, SCARCITY_PREMIUMS.get(label.lower(), 0.0)), label


def _score_q(
    roe: Optional[float],
    gross_margin: Optional[float],
    debt_ratio: Optional[float],
    domestic_substitution_slope: Optional[float] = None,
    replacement_cost_to_mcap: Optional[float] = None,
    customer_irreplaceability: Optional[Any] = None,
    scarcity_score: Optional[float] = None,
) -> tuple[float, str]:
    """
    Q 质量因子评分（0-100）。

    v3.0 = 财务质量(60%) + 稀缺性评分(40%)。稀缺性三子指标无法
    自动获取时不伪造，回落历史财务质量并在 note 标注 MANUAL_REQUIRED。
    """
    financial_score = 50.0
    notes = []

    if roe is not None:
        if roe >= 25:   financial_score += 25; notes.append(f"ROE={roe:.1f}%优秀")
        elif roe >= 15: financial_score += 15; notes.append(f"ROE={roe:.1f}%良好")
        elif roe >= 10: financial_score += 5;  notes.append(f"ROE={roe:.1f}%一般")
        else:           financial_score -= 10; notes.append(f"ROE={roe:.1f}%偏低")

    if gross_margin is not None:
        if gross_margin >= 50:   financial_score += 15; notes.append(f"毛利率={gross_margin:.1f}%高")
        elif gross_margin >= 30: financial_score += 8;  notes.append(f"毛利率={gross_margin:.1f}%中")
        elif gross_margin >= 15: financial_score += 2;  notes.append(f"毛利率={gross_margin:.1f}%低")
        else:                    financial_score -= 5;  notes.append(f"毛利率={gross_margin:.1f}%很低")

    if debt_ratio is not None:
        if debt_ratio <= 30:   financial_score += 10; notes.append(f"负债率={debt_ratio:.1f}%健康")
        elif debt_ratio <= 50: financial_score += 5;  notes.append(f"负债率={debt_ratio:.1f}%一般")
        elif debt_ratio <= 70: financial_score -= 5;  notes.append(f"负债率={debt_ratio:.1f}%偏高")
        else:                  financial_score -= 15; notes.append(f"负债率={debt_ratio:.1f}%危险")

    financial_score = max(0.0, min(100.0, financial_score))

    if scarcity_score is None:
        scarcity_score, scarcity_note = calc_scarcity_score(
            domestic_substitution_slope=domestic_substitution_slope,
            replacement_cost_to_mcap=replacement_cost_to_mcap,
            customer_irreplaceability=customer_irreplaceability,
        )
    else:
        scarcity_score = max(0.0, min(100.0, float(scarcity_score)))
        scarcity_note = f"稀缺性={scarcity_score:.0f}(外部传入)"

    if scarcity_score is None:
        score = financial_score
        notes.append(scarcity_note)
    else:
        score = financial_score * 0.60 + scarcity_score * 0.40
        notes.append(scarcity_note)

    score = max(0.0, min(100.0, score))
    return round(score, 1), " | ".join(n for n in notes if n) if notes else "质量数据不足"


def _score_v(pe_ttm: Optional[float],
             pb: Optional[float],
             g_adjusted_pct: Optional[float],
             regime: str,
             industry_code: Optional[Any] = None,
             scarcity_tier: Optional[Any] = None,
             industry_avg_pe: Optional[float] = None) -> tuple[float, str]:
    """V 估值因子评分（0-100）：PEG轨 + 科技制造稀缺性溢价轨。"""
    if pe_ttm is None or pe_ttm <= 0:
        return 50.0, "PE数据缺失，给中性分"

    canonical_regime = normalize_regime(regime)
    thresholds = PEG_THRESHOLDS.get(canonical_regime, PEG_THRESHOLDS["neutral"])
    code = str(industry_code).strip() if industry_code is not None else None
    pb_value = pb if pb is not None else 0
    use_scarcity = code in SCARCE_TECH_MANUFACTURING_CODES and code not in CONSUMER_MEDICAL_INDUSTRY_CODES and pb_value >= 5

    if use_scarcity:
        premium, premium_label = _scarcity_premium(scarcity_tier)
        base_pe = industry_avg_pe if industry_avg_pe and industry_avg_pe > 0 else max(pe_ttm, 25.0)
        fair_pe = base_pe * (1 + premium)
        ratio = pe_ttm / fair_pe if fair_pe > 0 else 1.0
        if ratio <= 0.70: score, level = 90, "显著低于稀缺性合理PE"
        elif ratio <= 1.00: score, level = 78, "低于/接近稀缺性合理PE"
        elif ratio <= 1.20: score, level = 60, "略高于稀缺性合理PE"
        elif ratio <= 1.50: score, level = 40, "明显高于稀缺性合理PE"
        else: score, level = 20, "稀缺性溢价后仍过贵"
        note = (f"稀缺性溢价模型: 行业代码{code}, PB={pb_value:.1f}, 稀缺层级={premium_label}, "
                f"合理PE={fair_pe:.1f}x(行业{base_pe:.1f}×{1+premium:.1f}), 当前PE/合理PE={ratio:.2f}，{level}")
    else:
        if g_adjusted_pct and g_adjusted_pct > 0:
            peg = pe_ttm / g_adjusted_pct
            if peg <= thresholds["good"]: score, note = 90, f"PEG={peg:.2f}≤{thresholds['good']}极优"
            elif peg <= thresholds["ok"]: score, note = 75, f"PEG={peg:.2f}合理"
            elif peg <= thresholds["max"]: score, note = 55, f"PEG={peg:.2f}偏贵"
            else: score, note = 25, f"PEG={peg:.2f}>{thresholds['max']}超贵"
        else:
            if pe_ttm <= 15: score, note = 85, f"PE={pe_ttm:.1f}低估"
            elif pe_ttm <= 25: score, note = 70, f"PE={pe_ttm:.1f}合理"
            elif pe_ttm <= 40: score, note = 50, f"PE={pe_ttm:.1f}偏贵"
            elif pe_ttm <= 60: score, note = 30, f"PE={pe_ttm:.1f}较贵"
            else: score, note = 15, f"PE={pe_ttm:.1f}昂贵"
        if code:
            track = "消费/医药PEG轨" if code in CONSUMER_MEDICAL_INDUSTRY_CODES else "PEG轨"
            note = f"{track}(行业代码{code}): {note}"

    if pb is not None and not use_scarcity:
        # PB修正仅对非稀缺性模型生效；稀缺性模型中高PB是护城河特征，不应双重惩罚
        if pb < 1: score = min(100, score + 5)
        elif pb > 10: score = max(0, score - 5)
    if canonical_regime == "bubble" and g_adjusted_pct and g_adjusted_pct > 0:
        peg_for_brake = pe_ttm / g_adjusted_pct
        if peg_for_brake > 2.0:
            score = min(score, 30)
            note += f" | 状态5b过热刹车: PEG={peg_for_brake:.2f}>2.0"
    return float(score), note

def _score_m(momentum_6m_pct: Optional[float],
             fund_flow_signal: Optional[str],
             report_rating_trend: Optional[str],
             north_flow_slope: Optional[float] = None,
             industry_chain_score: Optional[float] = None,
             ) -> tuple[float, str]:
    """
    M 动量因子评分（0-100）。

    v3.0 三层结构（2026-06-14 升级）：
      价格动量(6M超额收益)       × 35%  （原55%→降）
      资金流动量(主力+北向联动)   × 35%  （原25%→升，内容升级）
      产业链传导动量             × 30%  （原研报20%→替换）

    资金流层内部：
      主力净流入信号(东财push2当日)   × 50%
      北向20日净流入斜率              × 50%

    产业链传导层（当无实时数据时回落到研报评级趋势兼容模式）。
    """
    notes = []
    price_score = 50.0
    flow_score = 50.0
    chain_score = 50.0

    # ── 层¹：价格动量（6M，相对大盘超额收益）──
    if momentum_6m_pct is not None:
        if momentum_6m_pct >= 30:    price_score = 95; notes.append(f"6M超额+{momentum_6m_pct:.1f}%强势")
        elif momentum_6m_pct >= 15:  price_score = 80; notes.append(f"6M超额+{momentum_6m_pct:.1f}%好")
        elif momentum_6m_pct >= 5:   price_score = 65; notes.append(f"6M超额+{momentum_6m_pct:.1f}%偏好")
        elif momentum_6m_pct >= -5:  price_score = 50; notes.append(f"6M超额{momentum_6m_pct:.1f}%中性")
        elif momentum_6m_pct >= -15: price_score = 35; notes.append(f"6M超额{momentum_6m_pct:.1f}%偏弱")
        else:                        price_score = 15; notes.append(f"6M超额{momentum_6m_pct:.1f}%弱势")

    # ── 层²：资金流动量（主力净流入 + 北向斜率）──
    main_flow_score = 50.0
    north_flow_score = 50.0

    # 子层¹：主力资金（东财push2当日流入）
    if fund_flow_signal == "bullish":   main_flow_score = 85; notes.append("主力资金净流入")
    elif fund_flow_signal == "bearish": main_flow_score = 20; notes.append("主力资金净流出")
    elif fund_flow_signal == "neutral": main_flow_score = 50

    # 子层²：北向资金20日净流入斜率（亿元/天）
    if north_flow_slope is not None:
        if north_flow_slope >= 5:     north_flow_score = 90; notes.append(f"北向加速流入+{north_flow_slope:.1f}亿/天")
        elif north_flow_slope >= 1:   north_flow_score = 72; notes.append(f"北向持续流入+{north_flow_slope:.1f}亿/天")
        elif north_flow_slope >= -1:  north_flow_score = 50
        elif north_flow_slope >= -5:  north_flow_score = 30; notes.append(f"北向流出{north_flow_slope:.1f}亿/天")
        else:                         north_flow_score = 15; notes.append(f"北向加速流出{north_flow_slope:.1f}亿/天")
    else:
        north_flow_score = main_flow_score  # 北向不可用时，用主力信号替代

    flow_score = main_flow_score * 0.50 + north_flow_score * 0.50

    # ── 层³：产业链传导动量──
    if industry_chain_score is not None:
        chain_score = float(industry_chain_score)
        if chain_score >= 75: notes.append("产业链传导动量强")
        elif chain_score >= 50: notes.append("产业链动量中性")
        else: notes.append("产业链传导信号弱")
    else:
        # 产业链数据不可用：回落到研报评级趋势兼容模式
        if report_rating_trend == "upgrade":    chain_score = 80; notes.append("研报评级上调")
        elif report_rating_trend == "downgrade": chain_score = 20; notes.append("研报评级下调")
        elif report_rating_trend == "stable":    chain_score = 55
        # 无研报覆盖时保持50=中性

    m_score = price_score * 0.35 + flow_score * 0.35 + chain_score * 0.30
    return round(m_score, 1), " | ".join(notes) if notes else "动量数据有限"


def _score_r(lockup_risk: str,
             dragon_tiger_signal: str,
             cls_alerts: list) -> tuple[float, bool, str]:
    """
    R 风险因子评分（0-100）+ 一票否决检查。
    R分越高 = 风险健康度越高（越安全）
    返回: (score, veto_triggered, note)
    """
    score = 90.0  # 基础分（无风险时为90）
    veto = False
    notes = []

    # 限售解禁风险
    if lockup_risk == "high":
        score -= 20; notes.append("⚠️ 重大限售解禁(>5%)")
    elif lockup_risk == "medium":
        score -= 10; notes.append("限售解禁(1-5%)")
    elif lockup_risk == "low":
        score -= 3

    # 龙虎榜机构动向
    if dragon_tiger_signal == "block":
        score -= 25; notes.append("❌ 龙虎榜机构大幅净卖出")
    elif dragon_tiger_signal == "warning":
        score -= 12; notes.append("⚠️ 龙虎榜机构净卖出")
    elif dragon_tiger_signal == "pass" and score < 90:
        pass  # 不加分

    # 财联社风险告警
    if cls_alerts:
        kws = [kw for a in cls_alerts for kw in a.get("matched_keywords", [])]
        score -= min(30, len(kws) * 10)
        notes.append(f"财联社告警:{','.join(set(kws))[:30]}")
        # 一票否决触发词
        veto_kws = {"立案调查", "ST", "退市", "财务造假"}
        if veto_kws & set(kws):
            veto = True
            notes.append("🚫 一票否决触发")

    score = max(0, min(100, score))
    return round(score, 1), veto, " | ".join(notes) if notes else "风险健康"



def tencent_quote(codes: list[str]) -> dict[str, dict]:
    """
    腾讯财经实时行情（估值层）。
    覆盖：PE(TTM)/PE(静态)/PB/总市值/流通市值/换手率/涨跌停价/量比/振幅
    codes: 纯6位代码列表，如 ["600519", "000858"]
    返回: {code: {name, price, pe_ttm, pe_static, pb, mcap_yi, ...}}
    """
    import urllib.request

    prefixed = []
    for c in codes:
        nc = normalize_code(c)
        if nc.startswith(("6", "9")):
            prefixed.append(f"sh{nc}")
        elif nc.startswith("8"):
            prefixed.append(f"bj{nc}")
        else:
            prefixed.append(f"sz{nc}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
    except Exception as e:
        print(f"[ERROR] 腾讯财经请求失败: {e}")
        return {}

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name":          vals[1],
            "price":         float(vals[3]) if vals[3] else 0,
            "last_close":    float(vals[4]) if vals[4] else 0,
            "open":          float(vals[5]) if vals[5] else 0,
            "change_amt":    float(vals[31]) if vals[31] else 0,
            "change_pct":    float(vals[32]) if vals[32] else 0,
            "high":          float(vals[33]) if vals[33] else 0,
            "low":           float(vals[34]) if vals[34] else 0,
            "amount_wan":    float(vals[37]) if vals[37] else 0,
            "turnover_pct":  float(vals[38]) if vals[38] else 0,
            "pe_ttm":        float(vals[39]) if vals[39] else 0,
            "amplitude_pct": float(vals[43]) if vals[43] else 0,   # 振幅%（非PB！）
            "mcap_yi":       float(vals[44]) if vals[44] else 0,   # 总市值（亿）
            "float_mcap_yi": float(vals[45]) if vals[45] else 0,   # 流通市值（亿）
            "pb":            float(vals[46]) if vals[46] else 0,   # PB（索引46，非43）
            "limit_up":      float(vals[47]) if vals[47] else 0,   # 涨停价
            "limit_down":    float(vals[48]) if vals[48] else 0,   # 跌停价
            "vol_ratio":     float(vals[49]) if vals[49] else 0,   # 量比
            "pe_static":     float(vals[52]) if vals[52] else 0,   # PE静态
        }
    return result


# ─────────────────────────────────────────
# 东财 push2 个股基础信息
# ─────────────────────────────────────────

def eastmoney_stock_info(code: str) -> dict:
    """
    东财 push2 个股基础信息。盘后静默（push2 盘后不可用）。
    """
    if not is_trading_hours():
        return {}  # 盘后静默
    secid = get_secid(code)
    url = _push2_url("/api/qt/stock/get")
    params = {
        "secid": secid,
        "fields": "f57,f58,f84,f85,f116,f117,f127,f189",
        # f57=代码 f58=名称 f84=总股本 f85=流通股 f116=总市值 f117=流通市值
        # f127=行业 f189=上市日期
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json().get("data", {})
        return {
            "code":          d.get("f57", ""),
            "name":          d.get("f58", ""),
            "total_shares":  d.get("f84", 0),    # 总股本（股）
            "float_shares":  d.get("f85", 0),    # 流通股（股）
            "mcap_yuan":     d.get("f116", 0),   # 总市值（元）
            "float_mcap_yuan": d.get("f117", 0), # 流通市值（元）
            "industry":      d.get("f127", ""),  # 行业（东财分类）
            "list_date":     d.get("f189", ""),  # 上市日期
        }
    except Exception as e:
        print(f"[ERROR] 东财 stock_info 失败: {e}")
        return {}


# ─────────────────────────────────────────
# PE/PB 双源交叉校验
# ─────────────────────────────────────────

def cross_validate_valuation(code: str) -> dict:
    """
    PE/PB 双源交叉校验：腾讯财经 vs 东财 push2。
    用于发现数据延迟或异常，差异 > 5% 时打 warning。

    返回: {
        tencent: {pe_ttm, pb, mcap_yi},
        eastmoney: {pe_ttm, pb, mcap_yi},
        pe_diff_pct: float,
        pb_diff_pct: float,
        mcap_diff_pct: float,
        warnings: list[str],
        consistent: bool
    }
    """
    # 腾讯数据
    tc = tencent_quote([normalize_code(code)])
    tencent = tc.get(normalize_code(code), {})

    # 东财 push2 估值字段
    secid = get_secid(code)
    url = _push2_url("/api/qt/stock/get")
    params = {
        "secid": secid,
        "fields": "f9,f23,f116",
        # f9=PE(TTM动态) f23=PB f116=总市值
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    em_pe, em_pb, em_mcap_yi = None, None, None  # None = 不可用，区别于 0
    if is_trading_hours():
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            d = r.json().get("data", {})
            raw_pe = d.get("f9")
            raw_pb = d.get("f23")
            raw_mcap = d.get("f116")
            em_pe = float(raw_pe) / 100 if raw_pe else None
            em_pb = float(raw_pb) / 100 if raw_pb else None
            em_mcap_yi = float(raw_mcap) / 1e8 if raw_mcap else None
        except Exception as e:
            print(f"[WARN] 东财估值字段获取失败: {e}")
    # 盘后静默：不发请求，em_* 保持 None，校验函数会标记 em_available=False

    tc_pe = tencent.get("pe_ttm", 0)
    tc_pb = tencent.get("pb", 0)
    tc_mcap = tencent.get("mcap_yi", 0)

    def diff_pct(a, b):
        if a is None or b is None or not a or not b:
            return None
        return round(abs(a - b) / ((a + b) / 2) * 100, 2)

    pe_diff = diff_pct(tc_pe, em_pe)
    pb_diff = diff_pct(tc_pb, em_pb)
    mcap_diff = diff_pct(tc_mcap, em_mcap_yi)

    THRESHOLD = 5.0
    warnings = []
    em_available = em_pe is not None
    if not em_available:
        warnings.append("东财 push2 盘后不可用（push2delay 超时），仅腾讯数据有效")
    else:
        if pe_diff is not None and pe_diff > THRESHOLD:
            warnings.append(f"PE(TTM) 双源差异 {pe_diff}%（腾讯{tc_pe} vs 东财{em_pe}）")
        if pb_diff is not None and pb_diff > THRESHOLD:
            warnings.append(f"PB 双源差异 {pb_diff}%（腾讯{tc_pb} vs 东财{em_pb}）")
        if mcap_diff is not None and mcap_diff > THRESHOLD:
            warnings.append(f"市值双源差异 {mcap_diff}%（腾讯{tc_mcap}亿 vs 东财{em_mcap_yi:.1f}亿）")

    return {
        "code": code,
        "tencent":   {"pe_ttm": tc_pe, "pb": tc_pb, "mcap_yi": tc_mcap},
        "eastmoney": {"pe_ttm": em_pe, "pb": em_pb, "mcap_yi": round(em_mcap_yi, 2) if em_mcap_yi else None},
        "em_available": em_available,
        "pe_diff_pct":   pe_diff,
        "pb_diff_pct":   pb_diff,
        "mcap_diff_pct": mcap_diff,
        "warnings":  warnings,
        "consistent": em_available and len(warnings) == 0,
    }


# ─────────────────────────────────────────
# 行业分类口径映射工具
# ─────────────────────────────────────────

def map_industry(eastmoney_industry: str) -> str:
    """
    东财行业名称 → 申万一级行业映射。
    未知行业返回原名称并打印警告，需人工添加到 INDUSTRY_MAP。
    """
    mapped = INDUSTRY_MAP.get(eastmoney_industry)
    if mapped is None:
        print(f"[WARN] 行业口径未映射: '{eastmoney_industry}'，请更新 INDUSTRY_MAP")
        return eastmoney_industry
    return mapped


# ─────────────────────────────────────────
# 赛道质量评分（Phase 2 核心，嵌入 G/Q 因子）
# ─────────────────────────────────────────

# 赛道质量评分标准（与 execution-sop.md 步骤3 对齐）
# 三维：市场集中度(CR3) + 供需结构 + 价格趋势
# 分值：0-100，< 43 分触发 G 因子降级（不一票否决）

def score_sector_quality(
    cr3_pct: Optional[float] = None,          # 行业 CR3（前三名市占率%），越高越好
    supply_demand: Optional[str] = None,       # 供需状态: 'tight'/'balanced'/'oversupply'
    price_trend_12m: Optional[str] = None,     # 产品价格趋势: 'rising'/'stable'/'falling'
    competitive_moat: Optional[str] = None,    # 护城河类型: 'tech'/'scale'/'brand'/'resource'/'weak'
    cycle_position: Optional[str] = None,      # 大宗周期位置: 'early'/'mid'/'late'/'peak'/'none'
    notes: str = "",
) -> dict:
    """
    赛道质量评分（0-100）。

    设计原则：
    - 量化 + 定性结合，纯定性输入也能打分
    - CR3 > 60% = 强护城河（集中度高，定价权强）
    - 供需偏紧 = 正向信号（万华化学MDI就是典型）
    - 大宗超级周期判断：cycle_position='early'/'mid' 是加分项
    - 分数 < 43 → G 因子降级（成长总分削减，不直接否决标的）

    示例（万华化学）：
        score_sector_quality(
            cr3_pct=90,                    # 全球MDI：万华+巴斯夫+科思创 CR3≈90%
            supply_demand='tight',          # MDI供需偏紧
            price_trend_12m='rising',       # MDI价格上行
            competitive_moat='tech',        # 技术壁垒+规模壁垒
            cycle_position='mid',           # 化工大宗上行周期中期
        )
    """
    score = 50.0  # 基础分
    detail = []

    # 1. 市场集中度（CR3）
    if cr3_pct is not None:
        if cr3_pct >= 80:   score += 25; detail.append(f"CR3={cr3_pct}%极高垄断")
        elif cr3_pct >= 60: score += 18; detail.append(f"CR3={cr3_pct}%高集中度")
        elif cr3_pct >= 40: score += 8;  detail.append(f"CR3={cr3_pct}%中等集中")
        elif cr3_pct >= 20: score += 0;  detail.append(f"CR3={cr3_pct}%分散")
        else:               score -= 10; detail.append(f"CR3={cr3_pct}%高度分散")

    # 2. 供需结构
    if supply_demand:
        mapping = {
            "tight":       (20, "供需偏紧，价格有支撑"),
            "balanced":    (5,  "供需平衡"),
            "oversupply":  (-20, "产能过剩，价格承压"),
        }
        delta, note = mapping.get(supply_demand, (0, ""))
        score += delta
        if note:
            detail.append(note)

    # 3. 价格趋势（近12个月产品/服务价格）
    if price_trend_12m:
        mapping = {
            "rising":   (15, "产品价格上行"),
            "stable":   (5,  "价格平稳"),
            "falling":  (-15, "产品价格下行"),
        }
        delta, note = mapping.get(price_trend_12m, (0, ""))
        score += delta
        if note:
            detail.append(note)

    # 4. 护城河类型
    if competitive_moat:
        mapping = {
            "tech":     (15, "技术壁垒"),
            "scale":    (12, "规模壁垒"),
            "brand":    (12, "品牌壁垒"),
            "resource": (10, "资源壁垒"),
            "weak":     (-10, "护城河弱"),
        }
        delta, note = mapping.get(competitive_moat, (0, ""))
        score += delta
        if note:
            detail.append(note)

    # 5. 大宗周期位置（仅对周期性行业有意义）
    if cycle_position and cycle_position != "none":
        mapping = {
            "early": (15, "大宗周期早期，上行空间大"),
            "mid":   (8,  "大宗周期中期，趋势延续"),
            "late":  (-5, "大宗周期后期，注意拐点"),
            "peak":  (-20, "大宗周期顶部，下行风险"),
        }
        delta, note = mapping.get(cycle_position, (0, ""))
        score += delta
        if note:
            detail.append(note)

    score = round(max(0, min(100, score)), 1)
    below_threshold = score < 43

    return {
        "score": score,
        "below_threshold": below_threshold,
        "grade": "优质赛道" if score >= 70 else ("良好赛道" if score >= 55 else ("一般赛道" if score >= 43 else "⚠️ 赛道质量不足(<43)")),
        "detail": " | ".join(detail) if detail else "无输入，中性评分",
        "notes": notes,
        "g_factor_impact": "G因子降级（赛道质量<43）" if below_threshold else "正常",
    }


def _score_g_with_sector(
    revenue_cagr_3y: Optional[float],
    eps_cagr_3y: Optional[float],
    consensus_eps_growth: Optional[float],
    sector_quality: Optional[dict] = None,
) -> tuple[float, str]:
    """
    G 因子评分（含赛道质量加权）。
    赛道质量 < 43 → G_adjusted 打折 40%（成长不可持续风险）
    赛道质量 >= 70 → G_adjusted 加成 10%（强赛道溢价）
    """
    candidates = []
    if revenue_cagr_3y is not None:
        candidates.append(revenue_cagr_3y * 0.70)
    if eps_cagr_3y is not None:
        candidates.append(eps_cagr_3y * 0.70)
    if consensus_eps_growth is not None:
        candidates.append(consensus_eps_growth * 0.80)

    if not candidates:
        base_note = "无增速数据，给中性分50"
        g_adj = None
    else:
        g_adj = min(candidates)
        if g_adj >= 30:   base_score, base_note = 95, f"G_adj={g_adj:.1f}% 高成长"
        elif g_adj >= 20: base_score, base_note = 85, f"G_adj={g_adj:.1f}% 优质成长"
        elif g_adj >= 15: base_score, base_note = 75, f"G_adj={g_adj:.1f}% 中高成长"
        elif g_adj >= 10: base_score, base_note = 65, f"G_adj={g_adj:.1f}% 中等成长"
        elif g_adj >= 5:  base_score, base_note = 50, f"G_adj={g_adj:.1f}% 低成长"
        elif g_adj >= 0:  base_score, base_note = 35, f"G_adj={g_adj:.1f}% 微增长"
        else:             base_score, base_note = 15, f"G_adj={g_adj:.1f}% 负增长"

    if not candidates:
        return 50.0, base_note

    # 赛道质量修正
    sector_note = ""
    if sector_quality:
        sq = sector_quality.get("score", 50)
        if sq < 43:
            base_score = round(base_score * 0.6, 1)  # 40% 折扣
            sector_note = f" [赛道<43分降级→×0.6]"
        elif sq >= 70:
            base_score = min(100, round(base_score * 1.1, 1))  # 10% 加成
            sector_note = f" [强赛道({sq}分)加成→×1.1]"
        else:
            sector_note = f" [赛道质量{sq}分]"

    return float(base_score), base_note + sector_note


# ─────────────────────────────────────────
# Phase 2: 批量并发 GARP 评分
# ─────────────────────────────────────────

def batch_garp_score(
    stocks: list[dict],
    regime: str = "neutral",
    max_workers: int = 10,
    financial_data: Optional[dict] = None,
) -> list[dict]:
    """
    批量并发 GARP 五因子评分 — Phase 2 核心入口。

    stocks: 标的列表，格式为 pre_filter.load_candidate_pool() 返回值
            每个元素至少包含 {code, name}
            可选财务字段：revenue_cagr_3y, eps_cagr_3y, roe, gross_margin,
                         debt_ratio, momentum_6m_pct, sector_quality

    financial_data: {code: {revenue_cagr_3y, eps_cagr_3y, roe, ...}}
                    来自 baostock 财务接口，可选，不传则相应因子给中性分

    regime: 市场状态，'deep_bear'/'bear'/'neutral'/'bull'/'bubble'
    max_workers: 并发线程数，建议 8-15，过高可能触发限流

    返回: 按总分降序排列的评分列表
    耗时估算: 400只 × 3个接口 / 10线程 ≈ 2-4 分钟
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    financial_data = financial_data or {}

    def score_one(stock: dict) -> dict:
        code = stock["code"]
        fin = financial_data.get(code, {})
        sq = fin.get("sector_quality")  # 可选的赛道质量评分 dict

        try:
            result = auto_garp_score(
                code=code,
                regime=regime,
                revenue_cagr_3y=fin.get("revenue_cagr_3y"),
                eps_cagr_3y=fin.get("eps_cagr_3y"),
                consensus_eps_growth=fin.get("consensus_eps_growth"),
                roe=fin.get("roe"),
                gross_margin=fin.get("gross_margin"),
                debt_ratio=fin.get("debt_ratio"),
                domestic_substitution_slope=fin.get("domestic_substitution_slope"),
                replacement_cost_to_mcap=fin.get("replacement_cost_to_mcap"),
                customer_irreplaceability=fin.get("customer_irreplaceability"),
                scarcity_score=fin.get("scarcity_score"),
                industry_code=fin.get("industry_code") or stock.get("industry_code"),
                scarcity_tier=fin.get("scarcity_tier"),
                industry_avg_pe=fin.get("industry_avg_pe"),
                pe_percentile=fin.get("pe_percentile"),
                erp_pct=fin.get("erp_pct"),
                broad_index_1m_return_pct=fin.get("broad_index_1m_return_pct"),
                momentum_6m_pct=fin.get("momentum_6m_pct"),
                report_rating_trend=fin.get("report_rating_trend"),
                mx_signal=fin.get("mx_signal"),
                mx_score=fin.get("mx_score"),
                sector_quality=sq,
                north_flow_slope=fin.get("north_flow_slope"),
                industry_chain_score=fin.get("industry_chain_score"),
                data_asof={
                    "data_freshness": fin.get("data_freshness"),
                    "momentum_asof": fin.get("momentum_asof"),
                    "consensus_asof": fin.get("consensus_asof") or fin.get("latest_report_date"),
                },
            )
            return result
        except Exception as e:
            return {
                "code": code,
                "name": stock.get("name", ""),
                "total_score": 0,
                "tier": "❌ 评分失败",
                "error": str(e),
                "regime": regime,
            }

    results = []
    done = 0
    total = len(stocks)

    print(f"[batch_garp_score] 开始评分 {total} 只，{max_workers} 线程，市场状态={regime}")
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(score_one, s): s for s in stocks}
        for future in as_completed(futures):
            results.append(future.result())
            done += 1
            if done % 50 == 0:
                elapsed = time.time() - t0
                eta = elapsed / done * (total - done)
                print(f"  [{done}/{total}] 已完成，耗时{elapsed:.0f}s，预计剩余{eta:.0f}s")

    # 按总分降序排列
    results.sort(key=lambda x: x.get("total_score", 0), reverse=True)
    elapsed = time.time() - t0
    print(f"[batch_garp_score] 完成！耗时 {elapsed:.1f}s，有效结果 {len([r for r in results if r.get('total_score',0)>0])} 只")
    return results


def auto_garp_score(
    code: str,
    regime: str = "neutral",
    revenue_cagr_3y: Optional[float] = None,
    eps_cagr_3y: Optional[float] = None,
    consensus_eps_growth: Optional[float] = None,
    roe: Optional[float] = None,
    gross_margin: Optional[float] = None,
    debt_ratio: Optional[float] = None,
    domestic_substitution_slope: Optional[float] = None,
    replacement_cost_to_mcap: Optional[float] = None,
    customer_irreplaceability: Optional[Any] = None,
    scarcity_score: Optional[float] = None,
    industry_code: Optional[Any] = None,
    scarcity_tier: Optional[Any] = None,
    industry_avg_pe: Optional[float] = None,
    pe_percentile: Optional[float] = None,
    erp_pct: Optional[float] = None,
    broad_index_1m_return_pct: Optional[float] = None,
    momentum_6m_pct: Optional[float] = None,
    report_rating_trend: Optional[str] = None,
    mx_signal: Optional[str] = None,
    mx_score: Optional[float] = None,
    sector_quality: Optional[dict] = None,
    north_flow_slope: Optional[float] = None,
    industry_chain_score: Optional[float] = None,
    data_asof: Optional[dict] = None,
) -> dict:
    """
    GARP 五因子 AI 自动评分（轻量版）。
    自动获取：PE/PB（腾讯财经）、资金流（东财push2，盘中）、龙虎榜/解禁/财联社。
    手动传入：财务字段（baostock 或 MX-Data）、赛道质量（score_sector_quality()）。
    sector_quality: 传入则 G 因子根据赛道质量做加成/降级调整。
    """
    trade_date = datetime.now().strftime("%Y-%m-%d")
    requested_regime = regime
    regime, regime_adjustment = _canonical_regime(regime)
    if is_overheat_bubble_warning(pe_percentile, erp_pct, broad_index_1m_return_pct):
        regime = "bubble"
        trigger_note = "状态5b触发：全A PE分位>90%且ERP<0.5%"
        if broad_index_1m_return_pct is not None:
            trigger_note += f"，宽基1月涨幅={broad_index_1m_return_pct:.1f}%"
        regime_adjustment = (regime_adjustment + "；" if regime_adjustment else "") + trigger_note
    weights = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["neutral"])

    # 自动获取行情
    tc_data = {}
    try:
        tc = tencent_quote([normalize_code(code)])
        tc_data = tc.get(normalize_code(code), {})
    except Exception as e:
        print(f"[WARN] 腾讯财经行情获取失败: {e}")

    pe_ttm = tc_data.get("pe_ttm") or None
    pb = tc_data.get("pb") or None

    # 自动获取信号层（盘中时有效，盘后静默）
    fund_flow_signal = "neutral"
    try:
        ff = get_fund_flow_summary(code)
        fund_flow_signal = ff.get("signal", "neutral")
    except Exception:
        pass

    if north_flow_slope is None:
        try:
            north_flow_slope = get_north_flow_slope()
        except Exception:
            north_flow_slope = None

    lockup_risk = "none"
    try:
        lk = get_lockup_expiry(code, trade_date)
        lockup_risk = lk.get("risk_label", "none")
    except Exception:
        pass

    dragon_tiger_signal = "pass"
    try:
        dt = get_dragon_tiger(code, trade_date)
        dragon_tiger_signal = dt.get("layer4_signal", "pass")
    except Exception:
        pass

    cls_alerts = []
    try:
        cls_news = get_cls_telegraph(50)
        cls_alerts = cls_keyword_alert(
            filter_cls_by_holdings(cls_news, [normalize_code(code)])
        )
    except Exception:
        pass

    # 研报评级趋势
    if report_rating_trend is None:
        try:
            reports = get_eastmoney_reports(code, max_pages=1)
            fresh_reports = [r for r in reports if (_days_since(r.get("date")) is not None and _days_since(r.get("date")) <= 150)]
            if len(fresh_reports) >= 2:
                recent_ratings = [r["rating"] for r in fresh_reports[:5] if r.get("rating")]
                buy_count = sum(1 for r in recent_ratings if "买入" in r or "增持" in r)
                sell_count = sum(1 for r in recent_ratings if "减持" in r or "卖出" in r)
                if buy_count >= 3:
                    report_rating_trend = "upgrade"
                elif sell_count >= 2:
                    report_rating_trend = "downgrade"
                else:
                    report_rating_trend = "stable"
            else:
                report_rating_trend = "stable"
        except Exception:
            report_rating_trend = "stable"

    # G_adjusted for V factor PEG
    g_candidates = []
    if revenue_cagr_3y: g_candidates.append(revenue_cagr_3y * 0.70)
    if eps_cagr_3y:     g_candidates.append(eps_cagr_3y * 0.70)
    if consensus_eps_growth: g_candidates.append(consensus_eps_growth * 0.80)
    g_adjusted_pct = min(g_candidates) if g_candidates else None

    # 五因子打分
    g_score, g_note = _score_g_with_sector(revenue_cagr_3y, eps_cagr_3y, consensus_eps_growth, sector_quality)
    q_score, q_note = _score_q(
        roe,
        gross_margin,
        debt_ratio,
        domestic_substitution_slope=domestic_substitution_slope,
        replacement_cost_to_mcap=replacement_cost_to_mcap,
        customer_irreplaceability=customer_irreplaceability,
        scarcity_score=scarcity_score,
    )
    v_score, v_note = _score_v(
        pe_ttm, pb, g_adjusted_pct, regime,
        industry_code=industry_code,
        scarcity_tier=scarcity_tier,
        industry_avg_pe=industry_avg_pe,
    )
    m_score, m_note = _score_m(
        momentum_6m_pct,
        fund_flow_signal,
        report_rating_trend,
        north_flow_slope=north_flow_slope,
        industry_chain_score=industry_chain_score,
    )
    r_score, veto, r_note = _score_r(lockup_risk, dragon_tiger_signal, cls_alerts)

    # 加权总分
    if veto:
        total = 0.0
        tier = "❌ 一票否决"
    else:
        total = round(
            g_score * weights["G"] + q_score * weights["Q"] +
            v_score * weights["V"] + m_score * weights["M"] +
            r_score * weights["R"], 1
        )
        if total >= 85:   tier = "💎 钻石"
        elif total >= 75: tier = "🥇 黄金"
        elif total >= 60: tier = "🥈 白银"
        else:             tier = "🗑️ 剔除"

    # MX-StockPick 并联交叉验证
    mx_cross = {"available": False, "consistent": None, "note": "MX信号未传入"}
    if mx_signal and mx_score is not None:
        mx_cross["available"] = True
        mx_bullish = mx_signal in ("strong_buy", "buy")
        garp_bullish = total >= 70
        mx_cross["consistent"] = mx_bullish == garp_bullish
        if mx_cross["consistent"]:
            mx_cross["note"] = f"✅ MX({mx_signal}/{mx_score:.0f}分) 与 GARP({total}分) 方向一致"
            if mx_bullish and garp_bullish:
                total = min(100, total + 3)
        else:
            mx_cross["note"] = f"⚠️ MX({mx_signal}/{mx_score:.0f}分) 与 GARP({total}分) 方向背离，需人工复核"

    # 状态5b过热期估值刹车：PEG>2.0 时限制最高等级。
    if regime == "bubble" and pe_ttm and g_adjusted_pct and g_adjusted_pct > 0 and not veto:
        bubble_peg = pe_ttm / g_adjusted_pct
        if bubble_peg > 2.0:
            total = min(total, 59.9)
            tier = "🗑️ 剔除"
            regime_adjustment = (regime_adjustment + "；" if regime_adjustment else "") + f"状态5b估值刹车：PEG={bubble_peg:.2f}>2.0，最高限制为剔除档"
        elif bubble_peg > 1.5:
            total = min(total, 74.9)
            tier = "🥈 白银"
            regime_adjustment = (regime_adjustment + "；" if regime_adjustment else "") + f"状态5b估值刹车：PEG={bubble_peg:.2f}>1.5，最高限制为白银档"

    # R < 90 强制风险披露
    risk_disclosure = None
    if r_score < 90 and not veto:
        level = "高风险" if r_score < 60 else ("中风险" if r_score < 80 else "中低风险")
        risk_disclosure = {
            "level": f"⚠️ {level}（R={r_score}）",
            "note": r_note,
            "action": "下次复核重点关注龙虎榜机构动向、限售解禁进度、快讯风险告警",
        }

    # 建议
    if veto:
        recommendation = "❌ 一票否决 — 立即复核，暂停建仓"
    elif total >= 85:
        recommendation = "强烈建议持有/加仓，各因子全面优秀"
    elif total >= 75:
        recommendation = "建议持有，可适量加仓，注意估值上限"
    elif total >= 60:
        recommendation = "观察仓，不加仓，等待因子改善"
    else:
        recommendation = "建议减仓或剔除"

    freshness_input = {
        "code": code,
        "data_freshness": (data_asof or {}).get("data_freshness") if data_asof else None,
        "momentum_asof": (data_asof or {}).get("momentum_asof") if data_asof else None,
        "consensus_asof": (data_asof or {}).get("consensus_asof") if data_asof else None,
        "report_rating_trend": report_rating_trend,
    }
    freshness_checked = check_data_freshness(freshness_input)

    return {
        "code": code,
        "name": tc_data.get("name", ""),
        "regime": regime,
        "requested_regime": requested_regime,
        "regime_adjustment": regime_adjustment,
        "scores": {"G": g_score, "Q": q_score, "V": v_score, "M": m_score, "R": r_score},
        "weights": {k: f"{v*100:.0f}%" for k, v in weights.items()},
        "factor_notes": {"G": g_note, "Q": q_note, "V": v_note, "M": m_note, "R": r_note},
        "total_score": total,
        "tier": tier,
        "veto": veto,
        "mx_cross_check": mx_cross,
        "risk_disclosure": risk_disclosure,
        "recommendation": recommendation,
        "data_snapshot": {
            "pe_ttm": pe_ttm, "pb": pb,
            "industry_code": industry_code, "scarcity_tier": scarcity_tier,
            "industry_avg_pe": industry_avg_pe,
            "fund_flow": fund_flow_signal,
            "lockup_risk": lockup_risk,
            "dragon_tiger": dragon_tiger_signal,
            "report_trend": report_rating_trend,
            "north_flow_slope": north_flow_slope,
            "industry_chain_score": industry_chain_score,
        },
        "freshness": freshness_checked.get("freshness", {}),
        "freshness_flags": freshness_checked.get("freshness_flags", []),
        "sector_quality": sector_quality,
    }

if __name__ == "__main__":
    import json

    TEST_CODE = "600519"
    TODAY = datetime.now().strftime("%Y-%m-%d")

    print("=" * 60)
    print(f"a_stock_supplement 验证 — {TEST_CODE} @ {TODAY}")
    print("=" * 60)

    # 1. 财联社快讯
    print("\n[1] 财联社快讯（前3条）")
    cls = get_cls_telegraph(10)
    for n in cls[:3]:
        print(f"  {n['time']} | {n['title'][:50]}")

    # 2. 限售解禁
    print(f"\n[2] 限售解禁日历 — {TEST_CODE}")
    try:
        lockup = get_lockup_expiry(TEST_CODE, TODAY)
        print(f"  风险等级: {lockup['risk_label']}")
        print(f"  未来90天解禁批次: {len(lockup['upcoming'])}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")

    # 3. 龙虎榜
    print(f"\n[3] 龙虎榜 — {TEST_CODE}")
    try:
        dt = get_dragon_tiger(TEST_CODE, TODAY)
        print(f"  近30日上榜次数: {len(dt['records'])}")
        print(f"  机构净买入: {dt['institution']['net_wan']}万")
        print(f"  Layer4信号: {dt['layer4_signal']}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")

    # 4. 东财研报
    print(f"\n[4] 东财研报（前3条）— {TEST_CODE}")
    reports = get_eastmoney_reports(TEST_CODE, max_pages=1)
    for r in reports[:3]:
        print(f"  {r['date']} | {r['org']} | {r['title'][:40]} | 评级:{r['rating']}")

    # 5. 巨潮公告
    print(f"\n[5] 巨潮公告（前3条）— {TEST_CODE}")
    anns = get_cninfo_announcements(TEST_CODE, page_size=5)
    for a in anns[:3]:
        print(f"  {a['date']} | {a['title'][:50]}")

    # 6. Layer4 综合风险检查
    print(f"\n[6] GARP Layer4 风险检查 — {TEST_CODE}")
    result = layer4_risk_check(TEST_CODE, TODAY)
    print(f"  整体信号: {result['overall_signal']}")
    if result["block_reasons"]:
        print(f"  ❌ 阻断原因: {result['block_reasons']}")
    if result["caution_reasons"]:
        print(f"  ⚠️  注意原因: {result['caution_reasons']}")

    # 7. PE/PB 双源交叉校验
    print(f"\n[7] PE/PB 双源交叉校验 — {TEST_CODE}")
    try:
        cv = cross_validate_valuation(TEST_CODE)
        print(f"  腾讯: PE={cv['tencent']['pe_ttm']} PB={cv['tencent']['pb']} 市值={cv['tencent']['mcap_yi']}亿")
        print(f"  东财: PE={cv['eastmoney']['pe_ttm']} PB={cv['eastmoney']['pb']} 市值={cv['eastmoney']['mcap_yi']}亿")
        if cv["consistent"]:
            print("  ✅ 双源一致")
        else:
            for w in cv["warnings"]:
                print(f"  ⚠️  {w}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")

    # 8. auto_garp_score 轻量评分
    print(f"\n[8] GARP 自动评分 — {TEST_CODE}（neutral 状态，部分财务数据模拟）")
    try:
        result = auto_garp_score(
            TEST_CODE,
            regime="neutral",
            revenue_cagr_3y=12.0,       # 模拟：营收3年CAGR 12%
            eps_cagr_3y=15.0,           # 模拟：EPS CAGR 15%
            consensus_eps_growth=14.0,  # 模拟：一致预期EPS增速 14%
            roe=30.0,                   # 模拟：ROE 30%（茅台实际水平）
            gross_margin=92.0,          # 模拟：毛利率 92%
            debt_ratio=20.0,            # 模拟：负债率 20%
            momentum_6m_pct=5.0,        # 模拟：6M超额收益 +5%
        )
        print(f"  {result['name']}({TEST_CODE}) | 市场状态: {result['regime']}")
        print(f"  因子得分: G={result['scores']['G']} Q={result['scores']['Q']} "
              f"V={result['scores']['V']} M={result['scores']['M']} R={result['scores']['R']}")
        print(f"  权重: {result['weights']}")
        print(f"  总分: {result['total_score']} → {result['tier']}")
        print(f"  建议: {result['recommendation']}")
        if result['risk_disclosure']:
            print(f"  风险: {result['risk_disclosure']['level']}")
        print(f"  数据快照: PE={result['data_snapshot']['pe_ttm']} "
              f"资金流={result['data_snapshot']['fund_flow']} "
              f"解禁风险={result['data_snapshot']['lockup_risk']}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")

    print("\n✅ 验证完成")
