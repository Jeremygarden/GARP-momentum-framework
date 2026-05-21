"""
pre_filter.py
=============
GARP 框架全市场预筛选模块 — Phase 1

流程：
  Step 1 — 从 mootdx 获取全市场股票列表（~5000+只）
  Step 2 — 静态黑名单过滤（ST/退市/新股/金融/极小市值）
  Step 3 — 动态预筛选（市值/PE/换手率/涨跌幅批量拉腾讯财经）
  Step 4 — 行业赛道过滤（优质成长赛道白名单）
  Step 5 — 质量门槛（ROE/毛利率快照，来自 mootdx 37字段）
  输出   — data/candidate_pool.json（候选池，供 batch_garp_score 使用）

设计原则：
  - 每周一执行一次，耗时目标 < 3 分钟
  - 候选池目标：50-200 只
  - 完全基于已有数据链路，无新依赖
"""

import json
import time
import sys
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import urllib.request
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

# ─────────────────────────────────────────
# 全局配置
# ─────────────────────────────────────────

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "candidate_pool.json")

# mootdx industry 字段 → 证监会行业名称映射
MOOTDX_INDUSTRY_MAP = {
    1:'农业',2:'林业',3:'牧业',4:'渔业',5:'农林牧渔辅助',
    6:'煤炭开采',7:'石油天然气开采',8:'黑色金属矿采',9:'有色金属矿采',10:'非金属矿采',
    13:'农副食品加工',14:'食品制造',15:'酒饮料茶',16:'烟草',
    17:'纺织',18:'纺织服装',19:'化学制品',20:'医药制造',
    21:'化学纤维',22:'橡胶塑料',23:'非金属矿物制品',
    24:'电子设备制造',  # 半导体/光模块/消费电子 ← 重点赛道
    25:'仪器仪表',
    26:'专用设备',      # 工控/机器人 ← 重点赛道
    27:'通用设备',
    28:'汽车制造',
    29:'航空航天运输设备',
    30:'电气机械',      # 电力设备/储能 ← 重点赛道
    31:'黑色金属冶炼',32:'有色金属冶炼',33:'金属制品',
    34:'木材加工',35:'电力热力',36:'燃气',
    37:'食品饮料烟草',  # 白酒/消费品 ← 重点赛道
    38:'住宿餐饮',39:'交通运输仓储',
    40:'信息技术服务',  # 软件/互联网/计算机 ← 重点赛道
    41:'金融',42:'房地产',43:'租赁商务服务',
    44:'科学研究技术服务',
    45:'水利环境',46:'居民服务',47:'教育',48:'卫生社会工作',
    49:'文化体育娱乐',50:'公共管理',52:'综合',53:'建筑',54:'批发零售',
}

# 目标赛道（mootdx industry 代码）
TARGET_INDUSTRY_CODES = {
    24,   # 电子设备制造（半导体/光模块/消费电子）
    25,   # 仪器仪表
    26,   # 专用设备（工控/机器人）
    27,   # 通用设备
    28,   # 汽车制造（新能源汽车零部件）
    30,   # 电气机械（电力设备/储能）
    20,   # 医药制造
    37,   # 食品饮料（白酒/消费品）
    40,   # 信息技术服务（软件/互联网）
    44,   # 科学研究技术服务
    15,   # 酒饮料茶
    19,   # 化学制品（万华化学等特例）
    49,   # 文化体育娱乐（消费IP：泡泡玛特等）
}

# 直接排除行业代码
EXCLUDED_INDUSTRY_CODES = {
    41,   # 金融
    42,   # 房地产
    6,    # 煤炭
    7,    # 石油天然气
    8,    # 黑色金属矿
    31,   # 黑色金属冶炼（钢铁）
    38,   # 住宿餐饮
    50,   # 公共管理
}


# ─────────────────────────────────────────
# Step 1：获取全市场股票列表
# ─────────────────────────────────────────

def get_all_a_stocks() -> pd.DataFrame:
    """从 mootdx 获取全市场 A 股列表，过滤指数/ETF/基金。"""
    from mootdx.quotes import Quotes
    client = Quotes.factory(market="std")

    stocks_sh = client.stocks(market=1)
    stocks_sz = client.stocks(market=0)

    # 沪市：6开头（主板）、9开头（科创板）
    sh = stocks_sh[stocks_sh["code"].str.match(r"^[69]\d{5}$")]
    sh = sh[~sh["name"].str.contains("ETF|LOF|基金|债|权证|DR|存托", na=False)]

    # 深市：0开头（主板/中小板）、3开头（创业板）、8开头（北交所）
    sz = stocks_sz[stocks_sz["code"].str.match(r"^[038]\d{5}$")]
    sz = sz[~sz["name"].str.contains("ETF|LOF|基金|债|权证|DR|存托", na=False)]

    all_stocks = pd.concat([
        sh[["code", "name"]].assign(market="SH"),
        sz[["code", "name"]].assign(market="SZ"),
    ])
    # 过滤掉纯数字名称（指数残留）
    all_stocks = all_stocks[~all_stocks["name"].str.match(r"^\d")]
    all_stocks = all_stocks.reset_index(drop=True)
    return all_stocks


# ─────────────────────────────────────────
# Step 2：静态黑名单过滤
# ─────────────────────────────────────────

def apply_static_blacklist(df: pd.DataFrame) -> pd.DataFrame:
    """
    静态黑名单：
    - ST / *ST / 退市整理 / 退市
    - 代码以 9 开头的 B 股残留
    过滤后约剔除 200-400 只。
    """
    # ST 系列
    mask_st = df["name"].str.contains(r"^ST|^\*ST|^退市|^摘牌", na=False)
    # B股（沪B：900xxx，深B：200xxx）
    mask_b = df["code"].str.match(r"^(900|200)\d{3}$")

    removed = df[mask_st | mask_b]["name"].tolist()
    df_clean = df[~(mask_st | mask_b)].copy()

    print(f"  [黑名单] 剔除 {len(removed)} 只（ST/B股）→ 剩余 {len(df_clean)} 只")
    return df_clean


# ─────────────────────────────────────────
# Step 3：动态预筛选（腾讯财经批量行情）
# ─────────────────────────────────────────

def batch_tencent_quote(codes: list[str], batch_size: int = 100) -> dict[str, dict]:
    """
    腾讯财经批量实时行情。
    每批 100 只，约 0.3-0.5s，全市场 5000 只约 25-50s。
    返回 {code: {pe_ttm, pb, mcap_yi, float_mcap_yi, turnover_pct, change_pct, name}}
    """
    result = {}
    total_batches = (len(codes) + batch_size - 1) // batch_size

    for i in range(0, len(codes), batch_size):
        batch = codes[i: i + batch_size]
        prefixed = []
        for c in batch:
            if c.startswith(("6", "9")):
                prefixed.append(f"sh{c}")
            elif c.startswith("8"):
                prefixed.append(f"bj{c}")
            else:
                prefixed.append(f"sz{c}")

        url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read().decode("gbk")
        except Exception as e:
            print(f"  [WARN] 腾讯行情批次 {i//batch_size+1}/{total_batches} 失败: {e}")
            time.sleep(1)
            continue

        for line in data.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
            if len(vals) < 53:
                continue
            code = key[2:]
            try:
                result[code] = {
                    "name":          vals[1],
                    "price":         float(vals[3]) if vals[3] else 0,
                    "change_pct":    float(vals[32]) if vals[32] else 0,
                    "turnover_pct":  float(vals[38]) if vals[38] else 0,
                    "pe_ttm":        float(vals[39]) if vals[39] else 0,
                    "mcap_yi":       float(vals[44]) if vals[44] else 0,
                    "float_mcap_yi": float(vals[45]) if vals[45] else 0,
                    "pb":            float(vals[46]) if vals[46] else 0,
                }
            except (ValueError, IndexError):
                continue

        batch_num = i // batch_size + 1
        if batch_num % 10 == 0:
            print(f"  [进度] {batch_num}/{total_batches} 批次完成...")
        time.sleep(0.1)  # 礼貌性间隔，避免封IP

    return result


def apply_dynamic_filter(
    df: pd.DataFrame,
    quotes: dict,
    mcap_min: float = 30,
    mcap_max: float = 5000,
    pe_min: float = 0,
    pe_max: float = 150,
    turnover_min: float = 0.2,
    change_pct_min: float = -20,
) -> pd.DataFrame:
    """
    动态预筛选：市值/PE/换手率/涨跌幅。
    PE上限设150，覆盖高成长赛道（光模块/半导体等高PE标的）。
    """
    rows = []
    for _, row in df.iterrows():
        code = row["code"]
        q = quotes.get(code, {})
        if not q:
            continue

        pe = q.get("pe_ttm", 0)
        mcap = q.get("mcap_yi", 0)
        turnover = q.get("turnover_pct", 0)
        change = q.get("change_pct", 0)

        if mcap < mcap_min or mcap > mcap_max:
            continue
        if pe <= pe_min or pe > pe_max:
            continue
        if turnover < turnover_min:
            continue
        if change < change_pct_min:
            continue

        rows.append({
            "code": code,
            "name": q.get("name", row["name"]),
            "market": row["market"],
            "pe_ttm": pe,
            "pb": q.get("pb", 0),
            "mcap_yi": mcap,
            "float_mcap_yi": q.get("float_mcap_yi", 0),
            "turnover_pct": turnover,
            "change_pct": change,
            "price": q.get("price", 0),
        })

    df_filtered = pd.DataFrame(rows)
    print(f"  [动态筛选] 通过 {len(df_filtered)} 只")
    return df_filtered


# ─────────────────────────────────────────
# Step 4：行业赛道过滤（东财行业标签）
# ─────────────────────────────────────────

def get_industry_batch(codes: list[str], max_workers: int = 20) -> dict[str, str]:
    """
    批量获取行业代码（mootdx finance industry 字段，证监会行业代码）。
    注意：mootdx finance 行业字段覆盖率约 1-5%，大量标的返回空。
    无法获取行业的标的在 apply_sector_filter 中默认保留，不丢弃。
    """
    from mootdx.quotes import Quotes

    results = {code: "" for code in codes}
    client = Quotes.factory(market="std")

    def fetch_mootdx(code: str) -> tuple[str, str]:
        try:
            fin = client.finance(symbol=code)
            if fin is not None and not (hasattr(fin, "empty") and fin.empty):
                ind = fin.iloc[0].get("industry", "") if hasattr(fin, "iloc") else ""
                return code, str(int(float(ind))) if ind and str(ind) not in ("", "nan", "None") else ""
        except Exception:
            pass
        return code, ""

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_mootdx, c): c for c in codes}
        done = 0
        for future in as_completed(futures):
            code, industry = future.result()
            results[code] = industry
            done += 1
            if done % 200 == 0:
                print(f"  [行业标签] {done}/{len(codes)}...")

    found = sum(1 for v in results.values() if v)
    print(f"  [行业标签] 获取 {found}/{len(codes)} 只（覆盖率低属正常，无数据标的全部保留）")
    return results


def apply_sector_filter(
    df: pd.DataFrame,
    industry_map: dict[str, str],  # code -> industry_code (int as str)
    use_whitelist: bool = True,
) -> pd.DataFrame:
    """
    行业赛道过滤（基于 mootdx 证监会行业代码）。
    use_whitelist=True：只保留 TARGET_INDUSTRY_CODES（严格，约80-150只）
    use_whitelist=False：排除 EXCLUDED_INDUSTRY_CODES（宽松，约200-300只）
    """
    rows = []
    for _, row in df.iterrows():
        code = row["code"]
        raw = industry_map.get(code, "")
        try:
            ind_code = int(float(raw)) if raw else None
        except (ValueError, TypeError):
            ind_code = None

        ind_name = MOOTDX_INDUSTRY_MAP.get(ind_code, "") if ind_code else ""
        row = row.copy()
        row["industry"] = ind_name
        row["industry_code"] = ind_code

        if ind_code is None:
            # 无行业数据，保留（宁可多扫不漏）
            rows.append(row)
            continue

        if use_whitelist:
            if ind_code in TARGET_INDUSTRY_CODES:
                rows.append(row)
        else:
            if ind_code not in EXCLUDED_INDUSTRY_CODES:
                rows.append(row)

    df_filtered = pd.DataFrame(rows)
    mode = "白名单" if use_whitelist else "黑名单排除"
    print(f"  [行业过滤({mode})] 通过 {len(df_filtered)} 只")
    return df_filtered


# ─────────────────────────────────────────
# Step 5：质量门槛（mootdx 37字段快照）
# ─────────────────────────────────────────

def get_quality_batch(codes: list[str], max_workers: int = 15) -> dict[str, dict]:
    """
    mootdx 财务37字段批量获取（ROE/毛利率快照）。
    用于质量门槛过滤，剔除低质量标的。
    """
    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std")

    def fetch_one(code: str) -> tuple[str, dict]:
        try:
            fin = client.finance(symbol=code)
            if fin is None or (hasattr(fin, "empty") and fin.empty):
                return code, {}
            if hasattr(fin, "to_dict"):
                d = fin.iloc[0].to_dict() if hasattr(fin, "iloc") else {}
            else:
                d = {}
            return code, d
        except Exception:
            return code, {}

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, c): c for c in codes}
        done = 0
        for future in as_completed(futures):
            code, data = future.result()
            results[code] = data
            done += 1
            if done % 50 == 0:
                print(f"  [财务快照] {done}/{len(codes)} 完成...")

    return results


def apply_quality_filter(
    df: pd.DataFrame,
    financials: dict[str, dict],
    roe_min: float = 10.0,       # ROE 最低门槛（%）
) -> pd.DataFrame:
    """
    质量门槛过滤。
    ROE < 10% 的剔除，无财务数据的保留（给 GARP 精算）。
    注意：mootdx 37字段 ROE 字段名需实测确认，当前用 jinglirun/total_assets 估算
    """
    rows = []
    skipped = 0
    for _, row in df.iterrows():
        code = row["code"]
        fin = financials.get(code, {})

        if not fin:
            rows.append(row)  # 无财务数据，保留
            continue

        # mootdx 37字段：jinglirun(净利润) / meigujingzichan(每股净资产)
        # ROE 近似：净利润 / (每股净资产 × 总股本) — 精度有限，仅做粗筛
        # 更精确的 ROE 来自 baostock，这里只做一刀粗切
        roe_approx = None
        jlr = fin.get("jinglirun", 0) or 0
        mgzc = fin.get("meigujingzichan", 0) or 0
        liutong = fin.get("liutongguben", 0) or 0

        if mgzc and liutong and float(mgzc) > 0 and float(liutong) > 0:
            net_asset = float(mgzc) * float(liutong)
            if net_asset > 0:
                roe_approx = float(jlr) / net_asset * 100

        if roe_approx is not None and roe_approx < roe_min:
            skipped += 1
            continue

        row = row.copy()
        row["roe_approx"] = round(roe_approx, 1) if roe_approx else None
        rows.append(row)

    df_filtered = pd.DataFrame(rows)
    print(f"  [质量过滤] 剔除 ROE<{roe_min}% 的标的 {skipped} 只 → 剩余 {len(df_filtered)} 只")
    return df_filtered


# ─────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────

def run_pre_filter(
    use_sector_whitelist: bool = True,
    skip_quality_filter: bool = False,
    output_path: str = OUTPUT_PATH,
) -> dict:
    """
    执行全流程预筛选，输出候选池 JSON。

    use_sector_whitelist: True=只保留目标赛道（严格，约50-100只）
                          False=仅排除黑名单行业（宽松，约150-250只）
    skip_quality_filter: True=跳过 mootdx 质量过滤（节省时间）
    """
    t_start = time.time()
    print(f"\n{'='*60}")
    print(f"GARP 预筛选启动 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # Step 1: 全市场股票列表
    print("\n[Step 1] 获取全市场股票列表...")
    all_stocks = get_all_a_stocks()
    print(f"  全市场 A股: {len(all_stocks)} 只")

    # Step 2: 静态黑名单
    print("\n[Step 2] 静态黑名单过滤...")
    stocks = apply_static_blacklist(all_stocks)

    # Step 3: 动态预筛选（腾讯财经批量行情）
    print(f"\n[Step 3] 动态预筛选（腾讯财经批量，{len(stocks)}只）...")
    t3 = time.time()
    quotes = batch_tencent_quote(stocks["code"].tolist())
    print(f"  行情拉取完成，耗时 {time.time()-t3:.1f}s，获取 {len(quotes)} 只")
    stocks = apply_dynamic_filter(stocks, quotes,
                                  mcap_min=100,   # 100亿以上（聚焦中大盘）
                                  mcap_max=10000,
                                  pe_min=8,       # PE>8，剔除亏损和极低质量
                                  pe_max=120,     # 保留高成长赛道
                                  turnover_min=1.5,  # 换手率>1.5%，确保流动性和市场关注度
                                  change_pct_min=-20)

    if stocks.empty:
        print("  ❌ 动态筛选后为空")
        return {}

    # PB 质量门槛（护城河代理指标：PB>=3 表示市场愿意为质量付溢价）
    before = len(stocks)
    stocks = stocks[stocks["pb"] >= 3.0]
    print(f"  [PB≥3 质量门槛] 通过 {len(stocks)} 只（剔除 {before-len(stocks)} 只低PB）")

    # Step 4: 行业过滤（有数据时附加标注，无数据保留）
    print(f"\n[Step 4] 行业标签附加（{len(stocks)}只，仅标注用，不强制过滤）...")
    t4 = time.time()
    industry_map = get_industry_batch(stocks["code"].tolist(), max_workers=20)
    print(f"  行业标签耗时 {time.time()-t4:.1f}s")
    stocks = apply_sector_filter(stocks, industry_map, use_whitelist=use_sector_whitelist)

    # Step 5: 质量门槛（可选）
    if not skip_quality_filter and len(stocks) > 0:
        print(f"\n[Step 5] 质量门槛过滤（mootdx 37字段，{len(stocks)}只）...")
        t5 = time.time()
        financials = get_quality_batch(stocks["code"].tolist(), max_workers=15)
        print(f"  财务数据获取完成，耗时 {time.time()-t5:.1f}s")
        stocks = apply_quality_filter(stocks, financials)
    else:
        print(f"\n[Step 5] 跳过质量过滤")
        stocks["roe_approx"] = None

    # 输出
    total_time = time.time() - t_start
    candidate_list = []
    for _, row in stocks.iterrows():
        candidate_list.append({
            "code": row["code"],
            "name": row["name"],
            "market": row.get("market", ""),
            "industry": row.get("industry", ""),
            "pe_ttm": row.get("pe_ttm", 0),
            "pb": row.get("pb", 0),
            "mcap_yi": row.get("mcap_yi", 0),
            "float_mcap_yi": row.get("float_mcap_yi", 0),
            "turnover_pct": row.get("turnover_pct", 0),
            "change_pct": row.get("change_pct", 0),
            "roe_approx": row.get("roe_approx"),
        })

    # 按市值排序
    candidate_list.sort(key=lambda x: x["mcap_yi"], reverse=True)

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_market": len(all_stocks),
        "candidate_count": len(candidate_list),
        "elapsed_seconds": round(total_time, 1),
        "filter_config": {
            "sector_whitelist": use_sector_whitelist,
            "quality_filter": not skip_quality_filter,
        },
        "candidates": candidate_list,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ 预筛选完成！")
    print(f"   全市场 {len(all_stocks)} 只 → 候选池 {len(candidate_list)} 只")
    print(f"   总耗时: {total_time:.1f}s")
    print(f"   输出文件: {output_path}")
    print(f"{'='*60}")
    return output


# ─────────────────────────────────────────
# 候选池读取工具（供 batch_garp_score 使用）
# ─────────────────────────────────────────

def load_candidate_pool(path: str = OUTPUT_PATH) -> list[dict]:
    """读取候选池，返回标的列表。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"[候选池] {data['candidate_count']} 只，生成于 {data['generated_at']}")
    return data["candidates"]


def print_candidate_summary(path: str = OUTPUT_PATH):
    """打印候选池摘要。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    candidates = data["candidates"]
    print(f"\n候选池摘要（{data['generated_at']}）")
    print(f"  总数: {data['candidate_count']} 只（全市场 {data['total_market']} 只的 {data['candidate_count']/data['total_market']*100:.1f}%）")
    print(f"  耗时: {data['elapsed_seconds']}s")
    print(f"\n  行业分布 TOP10:")
    from collections import Counter
    industries = Counter(c["industry"] for c in candidates if c["industry"])
    for ind, cnt in industries.most_common(10):
        print(f"    {ind}: {cnt}只")
    print(f"\n  市值分布:")
    mcaps = [c["mcap_yi"] for c in candidates]
    print(f"    最大: {max(mcaps):.0f}亿  最小: {min(mcaps):.0f}亿  中位: {sorted(mcaps)[len(mcaps)//2]:.0f}亿")
    print(f"\n  前20只标的:")
    for c in candidates[:20]:
        print(f"    {c['code']} {c['name']:<8} {c['industry']:<10} PE={c['pe_ttm']:.1f} 市值={c['mcap_yi']:.0f}亿")


# ─────────────────────────────────────────
# 入口
# ─────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GARP 预筛选")
    parser.add_argument("--wide", action="store_true", help="宽松模式（行业黑名单排除，而非白名单）")
    parser.add_argument("--skip-quality", action="store_true", help="跳过质量过滤（节省~1分钟）")
    parser.add_argument("--summary", action="store_true", help="打印已有候选池摘要")
    args = parser.parse_args()

    if args.summary:
        if os.path.exists(OUTPUT_PATH):
            print_candidate_summary()
        else:
            print("候选池文件不存在，请先运行预筛选")
    else:
        run_pre_filter(
            use_sector_whitelist=not args.wide,
            skip_quality_filter=args.skip_quality,
        )
