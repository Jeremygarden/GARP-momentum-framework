"""
a_stock_supplement.py
=====================
GARP 框架数据链路补强模块 — 基于 a-stock-data V3.1
补强方向：
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

import requests
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

# ─────────────────────────────────────────
# 全局配置
# ─────────────────────────────────────────

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

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
    主力: 东财 push2（实时）
    兜底: thsdk（fallback_thsdk=True 时启用，需 thsdk 已安装）

    返回字段（统一单位：万元）:
      time, main_net_wan, large_net_wan, mid_net_wan,
      small_net_wan, super_net_wan
    """
    secid = get_secid(code)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
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

    return {
        "em_count": len(eastmoney_reports),
        "mx_count": len(miaoxiang_reports),
        "em_latest_rating": em_latest,
        "mx_latest_rating": mx_latest,
        "rating_consistent": em_latest == mx_latest,
        "eps_consensus_from_em": eps_consensus,
    }


# ─────────────────────────────────────────
# 5. 财联社快讯（直连 cls.cn）
# ─────────────────────────────────────────

def get_cls_telegraph(page_size: int = 50) -> list[dict]:
    """
    财联社电报（全市场实时快讯）— 直连 cls.cn。
    替代 Tavily 爬取方案，稳定性更高。
    返回: [{title, content, time, stocks}]
    stocks: 关联股票代码列表（cls 直接提供，可 JOIN 持仓）
    """
    url = "https://www.cls.cn/nodeapi/telegraphList"
    params = {"rn": str(page_size), "page": "1"}
    headers = {"User-Agent": UA, "Referer": "https://www.cls.cn/"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        rows = []
        for item in d.get("data", {}).get("roll_data", []):
            # 提取关联股票代码
            stocks = []
            for s in item.get("stock_list", []) or []:
                if s.get("StockCode"):
                    stocks.append(s["StockCode"])
            rows.append({
                "title": item.get("title", "") or item.get("brief", ""),
                "content": (item.get("content", "") or item.get("brief", ""))[:300],
                "time": item.get("ctime", ""),
                "stocks": stocks,
            })
        return rows
    except Exception as e:
        print(f"[ERROR] 财联社快讯获取失败: {e}")
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
# 快速验证入口
# ─────────────────────────────────────────

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

    print("\n✅ 验证完成")
