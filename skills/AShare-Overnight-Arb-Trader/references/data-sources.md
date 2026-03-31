# 数据接入指南（隔夜套利专用）

本策略所需数据全部为 **A股实时/日内数据**，以 thsdk 为主要接入方式，tavily_extract 爬取东方财富作为补充和验证。

---

## 数据源配置

```python
# 主数据源：同花顺 SDK（实时行情、板块、大单）
# 认证通过环境变量（THS_USERNAME / THS_PASSWORD）或游客模式
from thsdk import THS
ths = THS()
ths.connect()

# 补充数据源：tavily_extract 爬取东方财富/财联社
# 无需配置，OpenClaw 内置
```

---

## 第一层数据：大盘&情绪环境

### 1.1 指数行情（上证/创业板 MA20）

```python
from datetime import datetime, timedelta

# 上证指数：代码 USHI000001
# 创业板指：代码 USHI399006

# 获取近30日日K线（计算MA20）
resp = ths.klines(
    ths_code="USHI000001",          # 上证指数
    start_time=datetime.now() - timedelta(days=45),
    end_time=datetime.now(),
    interval="day"
)
sh_df = resp.to_dataframe()
sh_df["MA20"] = sh_df["close"].rolling(20).mean()

# 判断条件
price_above_ma20 = sh_df["close"].iloc[-1] > sh_df["MA20"].iloc[-1]
ma20_rising = sh_df["MA20"].iloc[-1] > sh_df["MA20"].iloc[-2]

# 创业板同理，代码换成 USHI399006
```

### 1.2 全市场涨跌停数量

```python
# thsdk market_data 获取全市场快照
# 方式1：thsdk（需要遍历，适合精确统计）
resp_cn = ths.market_data_cn("USHA000001")  # A股整体数据

# 方式2（推荐）：tavily_extract 爬取东方财富涨跌停数据
# 东方财富涨停数据页面
urls = ["https://quote.eastmoney.com/ztb/"]
# 爬取内容包含：涨停数、跌停数、炸板数等
```

### 1.3 北向资金净流入

```python
# tavily_extract 爬取东方财富北向资金页面
urls = ["https://data.eastmoney.com/hsgt/index.html"]
# 关注：北向当日净买入额（亿元）
# 警戒线：净流出 > 50亿

# 或爬取财联社快讯获取实时北向资金动态
urls = ["https://www.cls.cn/telegraph"]
```

### 1.4 情绪周期判断（连板高度/炸板率）

```python
# 爬取东方财富连板数据
urls = [
    "https://quote.eastmoney.com/ztb/",          # 涨停板数据
    "https://data.eastmoney.com/stockdata/lhb/"  # 龙虎榜数据
]
# 关注：
# - 当前最高连板数（情绪高度）
# - 前日涨停股今日平均表现（溢价率/炸板率）
# - 近3日连板高度趋势
```

---

## 第二层数据：板块强度

### 2.1 当日板块涨幅排行

```python
# thsdk 获取行业/概念板块数据
industry_resp = ths.ths_industry()   # 行业板块
concept_resp = ths.ths_concept()     # 概念板块
industry_df = industry_resp.to_dataframe()

# 按涨幅排序，取前3
top3_sectors = industry_df.sort_values("pct_chg", ascending=False).head(3)

# 补充：tavily_extract 东方财富板块排行
urls = ["https://quote.eastmoney.com/bk/"]
```

### 2.2 板块内涨停个股数量

```python
# 获取特定板块成分股
block_code = "板块代码"
resp = ths.block_constituents(block_code)
stocks_df = resp.to_dataframe()

# 统计涨停数（涨幅 >= 9.9%）
limit_up_count = len(stocks_df[stocks_df["pct_chg"] >= 9.9])
```

---

## 第三层数据：个股核心指标

### 3.1 日K线 + 均线 + 涨幅

```python
# 获取单只股票近20日K线
resp = ths.klines(
    ths_code="USHA600519",           # 股票代码（沪市：USHA，深市：USZA）
    start_time=datetime.now() - timedelta(days=30),
    end_time=datetime.now(),
    interval="day",
    adjust="前复权"
)
kline_df = resp.to_dataframe()

# 计算涨幅（当日）
today_pct = (kline_df["close"].iloc[-1] - kline_df["close"].iloc[-2]) / kline_df["close"].iloc[-2]

# 均线
kline_df["MA5"]  = kline_df["close"].rolling(5).mean()
kline_df["MA10"] = kline_df["close"].rolling(10).mean()
kline_df["MA20"] = kline_df["close"].rolling(20).mean()

# 近10日是否有涨停（涨幅≥9.9%）
recent_10 = kline_df.tail(10)
has_limit_up = any(recent_10["pct_chg"] >= 9.9)
```

### 3.2 量比 + 换手率

```python
# 实时快照数据（包含量比、换手率）
resp = ths.market_data_cn("USHA600519", query_key="基础数据")
snapshot = resp.to_dataframe()

volume_ratio = snapshot["量比"]      # 量比
turnover_rate = snapshot["换手率"]   # 换手率(%)
```

### 3.3 成交量分布（尾盘占比）

```python
# 分钟级数据（计算尾盘半小时成交量占比）
resp = ths.min_snapshot("USHA600519")
min_df = resp.to_dataframe()

# 计算尾盘半小时（14:30-15:00）成交量占比
total_vol = min_df["volume"].sum()
tail_vol = min_df[min_df["time"] >= "14:30"]["volume"].sum()
tail_ratio = tail_vol / total_vol  # 应 ≤ 18%
```

### 3.4 分时走势（均价线上方时间占比）

```python
# 分时数据
resp = ths.intraday_data("USHA600519")
intraday_df = resp.to_dataframe()

# 均价线 = 累计成交额 / 累计成交量
intraday_df["avg_price"] = intraday_df["amount"].cumsum() / intraday_df["volume"].cumsum()

# 价格在均价线上方的时间占比（应 ≥ 70%）
above_avg = (intraday_df["price"] > intraday_df["avg_price"]).sum()
total_ticks = len(intraday_df)
above_ratio = above_avg / total_ticks
```

### 3.5 流通市值（流动性筛选）

```python
# 基础数据包含流通市值
resp = ths.market_data_cn("USHA600519", query_key="基础数据")
data = resp.to_dataframe()

float_cap = data["流通市值"]  # 单位：元，换算亿：/ 1e8
# 要求：65亿 ≤ float_cap ≤ 200亿
```

---

## 第四层数据：资金确认

### 4.1 大单净流入

```python
# 大单/超大单资金流向
resp = ths.big_order_flow("USHA600519")
flow_df = resp.to_dataframe()

# 计算净流入（大单买入 - 大单卖出）
net_inflow = flow_df["大单净流入"].sum()  # 正值=净流入，负值=净流出

# 尾盘大单净流入（13:00后）
tail_inflow = flow_df[flow_df["time"] >= "13:00"]["大单净流入"].sum()
```

### 4.2 龙虎榜数据

```python
# tavily_extract 爬取东方财富龙虎榜
urls = [
    f"https://data.eastmoney.com/stock/lhb/{stock_code}.html",
    "https://data.eastmoney.com/stockdata/lhb/"   # 今日龙虎榜汇总
]
# 关注：近3日是否上榜、游资席位净买入额
```

---

## 快速数据获取脚本（完整流程）

```python
#!/usr/bin/env python3
"""
AShare-Overnight-Arb-Trader 数据采集脚本
在14:45前运行，获取所有所需数据
"""
from thsdk import THS
from datetime import datetime, timedelta

ths = THS()
ths.connect()

def get_market_status():
    """第一层：大盘数据"""
    # 上证指数MA20
    sh = ths.klines("USHI000001", datetime.now()-timedelta(45), datetime.now(), interval="day").to_dataframe()
    sh["MA20"] = sh["close"].rolling(20).mean()

    # 创业板指MA20
    cyb = ths.klines("USHI399006", datetime.now()-timedelta(45), datetime.now(), interval="day").to_dataframe()
    cyb["MA20"] = cyb["close"].rolling(20).mean()

    return {
        "sh_above_ma20": sh["close"].iloc[-1] > sh["MA20"].iloc[-1],
        "sh_ma20_rising": sh["MA20"].iloc[-1] > sh["MA20"].iloc[-2],
        "cyb_above_ma20": cyb["close"].iloc[-1] > cyb["MA20"].iloc[-1],
        "cyb_ma20_rising": cyb["MA20"].iloc[-1] > cyb["MA20"].iloc[-2],
    }

def get_top_sectors():
    """第二层：板块数据"""
    industry = ths.ths_industry().to_dataframe()
    return industry.sort_values("pct_chg", ascending=False).head(3)

def get_stock_data(ths_code):
    """第三层：个股数据"""
    kline = ths.klines(ths_code, datetime.now()-timedelta(30), datetime.now(), interval="day", adjust="前复权").to_dataframe()
    snapshot = ths.market_data_cn(ths_code, query_key="基础数据").to_dataframe()
    intraday = ths.intraday_data(ths_code).to_dataframe()
    flow = ths.big_order_flow(ths_code).to_dataframe()
    return kline, snapshot, intraday, flow

ths.disconnect()
```

---

## 数据来源汇总

| 数据类型 | 主数据源 | 备用数据源 |
|---|---|---|
| 指数K线/MA20 | thsdk `klines("USHI000001")` | 东方财富网页 |
| 全市场涨跌停数 | tavily_extract → eastmoney ztb | thsdk 全市场扫描 |
| 北向资金 | tavily_extract → eastmoney hsgt | 财联社快讯 cls.cn |
| 情绪周期/连板高度 | tavily_extract → eastmoney ztb | 人工判断 |
| 板块涨幅排行 | thsdk `ths_industry()` | eastmoney 板块页 |
| 板块成分股涨停数 | thsdk `block_constituents()` | eastmoney 板块详情 |
| 个股日K线 | thsdk `klines()` | baostock |
| 量比/换手率 | thsdk `market_data_cn()` | eastmoney 个股页 |
| 分时数据 | thsdk `intraday_data()` | eastmoney 分时图 |
| 大单净流入 | thsdk `big_order_flow()` | eastmoney 资金流向 |
| 龙虎榜 | tavily_extract → eastmoney lhb | 手动查询 |
