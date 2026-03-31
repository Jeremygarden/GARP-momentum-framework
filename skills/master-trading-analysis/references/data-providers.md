# 数据源接入指南

本框架通过两个全局变量切换数据源，分析逻辑与数据获取完全解耦。

## 全局变量

```python
DATA_PROVIDER = "yfinance"   # 数据源：yfinance | baostock | thsdk | alphavantage
DATA_API_KEY  = ""           # API Key（yfinance/financialdatasets/alphavantage 需要；thsdk 使用账号体系）

# Alpha Vantage（备选 API 接口数据源）
ALPHAVANTAGE_API_KEY = "P1X33VRNKH044K7N"
```

---

## 数据字段统一映射

无论使用哪种数据源，分析模块期望以下标准字段：

### 价格数据（price_data）
| 字段 | 说明 |
|---|---|
| `close` | 收盘价序列（list/Series） |
| `open` / `high` / `low` | 开/高/低价 |
| `volume` | 成交量 |
| `date` | 日期索引 |

### 财务指标（financial_metrics）
| 字段 | 说明 |
|---|---|
| `revenue` | 营收 |
| `net_income` | 净利润 |
| `operating_income` / `ebit` | 营业利润 |
| `free_cash_flow` | 自由现金流 |
| `total_assets` / `total_debt` | 总资产/总债务 |
| `shareholders_equity` | 股东权益 |
| `current_assets` / `current_liabilities` | 流动资产/负债 |
| `market_cap` | 市值 |
| `eps` | 每股收益 |
| `book_value_per_share` | 每股净资产 |
| `return_on_equity` | ROE |
| `return_on_invested_capital` | ROIC |
| `gross_margin` / `net_margin` / `operating_margin` | 毛/净/营业利润率 |
| `revenue_growth` | 营收增速 |
| `earnings_growth` | 盈利增速 |
| `price_to_earnings` | PE |
| `price_to_book` | PB |
| `price_to_sales` | PS |
| `price_to_free_cash_flow` | P/FCF |
| `debt_to_equity` | D/E |
| `current_ratio` | 流动比率 |
| `beta` | Beta |
| `insider_ownership` | 内部持股比例 |

---

## 方式一：yfinance（美股/港股/国际）

### 适用场景
- 美股、港股、ETF、指数
- 免费使用，数据延迟约15分钟
- 财务数据覆盖较全，历史数据充足

### 安装
```bash
pip install yfinance
```

### 使用示例
```python
import yfinance as yf

ticker = "AAPL"
stock = yf.Ticker(ticker)

# 价格数据
price_data = stock.history(period="1y")  # 1年日K线
# 字段：Open, High, Low, Close, Volume

# 财务数据
info = stock.info
financials = stock.financials          # 损益表（年度）
balance_sheet = stock.balance_sheet    # 资产负债表
cashflow = stock.cashflow              # 现金流量表
quarterly_financials = stock.quarterly_financials

# 常用指标直取
market_cap   = info.get("marketCap")
pe_ratio     = info.get("trailingPE")
pb_ratio     = info.get("priceToBook")
roe          = info.get("returnOnEquity")
debt_equity  = info.get("debtToEquity")
revenue_growth = info.get("revenueGrowth")
eps          = info.get("trailingEps")
beta         = info.get("beta")

# 内部交易
insider_trades = stock.insider_transactions
```

### 变量配置
```python
DATA_PROVIDER = "yfinance"
DATA_API_KEY  = ""           # 免费版不需要 key
# 如使用 financialdatasets.ai（原项目数据源）：
# DATA_API_KEY = "your_financial_datasets_api_key"
```

---

## 方式二：baostock（A股首选）

### 适用场景
- A 股（沪深）行情和财务数据
- 完全免费，无需注册
- 财务数据延迟约一个季度，适合基本面分析

### 安装
```bash
pip install baostock
```

### 使用示例
```python
import baostock as bs
import pandas as pd

# 登录（无需账号）
lg = bs.login()

# 股票代码格式：sh.600519（贵州茅台）、sz.000001（平安银行）
code = "sh.600519"

# K线数据（日线）
rs = bs.query_history_k_data_plus(
    code,
    "date,open,high,low,close,volume,amount,turn,pctChg",
    start_date="2023-01-01",
    end_date="2024-12-31",
    frequency="d",       # d=日, w=周, m=月, 5=5分钟
    adjustflag="3"       # 1=后复权, 2=前复权, 3=不复权
)
price_df = rs.get_data()

# 财务数据
# 盈利能力
rs_profit = bs.query_profit_data(code=code, year=2023, quarter=4)
profit_df = rs_profit.get_data()
# 字段：roeAvg, npMargin, gpMargin, netProfit, epsTTM, MBRevenue, totalShare

# 运营能力
rs_operation = bs.query_operation_data(code=code, year=2023, quarter=4)
# 字段：NRTurnRatio, NRTurnDays, INVTurnRatio, INVTurnDays, CATurnRatio, AssetTurnRatio

# 成长能力
rs_growth = bs.query_growth_data(code=code, year=2023, quarter=4)
# 字段：YOYEquity, YOYAsset, YOYNI, YOYEPSBasic, YOYPNI

# 偿债能力
rs_balance = bs.query_balance_data(code=code, year=2023, quarter=4)
# 字段：liquidityRatio, quickRatio, cashRatio, YOYLiability, liabilityToAsset, assetToEquity

# 市值数据（实时）
rs_market = bs.query_stock_basic(code=code)

bs.logout()
```

### 变量配置
```python
DATA_PROVIDER = "baostock"
DATA_API_KEY  = ""    # 不需要
```

---

## 方式三：thsdk（同花顺 SDK）

### 适用场景
- A股/港股/美股/期货/外汇 全市场
- 实时行情、Level2、大单流向
- 需要同花顺账号（可使用临时游客账号测试）
- **注意**：底层依赖同花顺 C 动态库，Linux 服务器环境需要验证兼容性

### 安装
```bash
pip install thsdk
```

### 认证方式
thsdk 使用同花顺账号体系（非 API Key），支持三种配置方式：

**方式A：环境变量（推荐生产使用）**
```bash
export THS_USERNAME="your_ths_username"
export THS_PASSWORD="your_ths_password"
export THS_MAC="your_mac_address"       # 可选，不填自动生成
```

**方式B：代码传参**
```python
from thsdk import THS
ths = THS({
    "username": "your_username",
    "password": "your_password",
    "mac": "AA:BB:CC:DD:EE:FF"    # 可选
})
```

**方式C：临时游客账号（仅测试）**
```python
from thsdk import THS
ths = THS()    # 自动使用游客账号，随时可能失效
```

### 使用示例
```python
from thsdk import THS
from datetime import datetime

# 股票代码格式：4位市场代码 + 6位数字
# A股沪市：USHA600519  A股深市：USZA000001
# 美股：UNQQTSLA（纳斯达克TSLA）  港股：USHK00700

ths = THS()
ths.connect()

# K线数据
resp = ths.klines(
    ths_code="USHA600519",
    start_time=datetime(2023, 1, 1),
    end_time=datetime(2024, 12, 31),
    interval="day",     # day/week/month/60/30/15/5/1（分钟）
    adjust=""           # "前复权" / "后复权" / ""
)
kline_df = resp.to_dataframe()
# 字段：time, open, high, low, close, volume, amount

# 实时行情（A股）
resp = ths.market_data_cn("USHA600519", query_key="基础数据")

# 美股实时行情
resp = ths.market_data_us("UNQQTSLA", query_key="基础数据")

# 港股实时行情
resp = ths.market_data_hk("USHK00700", query_key="基础数据")

# 大单流向
resp = ths.big_order_flow("USHA600519")

# 资讯/新闻
resp = ths.news(code="600519", market="USHA")

# 板块数据
resp = ths.ths_industry()   # 行业列表
resp = ths.ths_concept()    # 概念列表

# 分时数据（当日）
resp = ths.intraday_data("USHA600519")

# Tick 数据
resp = ths.tick_level1("USHA600519")

ths.disconnect()
```

### 变量配置
```python
DATA_PROVIDER = "thsdk"
DATA_API_KEY  = ""    # thsdk 不使用 API Key，通过账号体系认证
# 账号通过环境变量配置：THS_USERNAME / THS_PASSWORD / THS_MAC
```

### ⚠️ thsdk 局限性

| 项目 | 说明 |
|---|---|
| 财务数据 | thsdk 主要提供行情数据，**财务报表数据有限**，建议配合 baostock 补充 |
| Linux 兼容 | 底层 C 库依赖系统环境，VPS/云服务器需测试后确认可用 |
| 账号限制 | 游客账号受限，生产建议使用正式同花顺账号 |
| 实时 vs 历史 | 强项在实时行情，历史财务数据不如 baostock 完整 |

---

---

## 方式四：Alpha Vantage（API 接口备选）

### 适用场景
- 美股/港股/外汇/加密货币
- 财务报表、技术指标、基本面数据均有覆盖
- 免费版每分钟 5 次、每天 500 次调用
- 无需安装额外库，直接 HTTP 请求

### API Key 配置
```python
ALPHAVANTAGE_API_KEY = "P1X33VRNKH044K7N"
BASE_URL = "https://www.alphavantage.co/query"
```

### 使用示例
```python
import requests

key = ALPHAVANTAGE_API_KEY

# 日K线（全历史）
resp = requests.get(BASE_URL, params={
    "function": "TIME_SERIES_DAILY_ADJUSTED",
    "symbol": "AAPL",
    "outputsize": "full",    # full=全历史, compact=近100条
    "apikey": key
}).json()

# 公司基本信息与估值指标
resp = requests.get(BASE_URL, params={
    "function": "OVERVIEW",
    "symbol": "AAPL",
    "apikey": key
}).json()
# 返回：MarketCapitalization, PERatio, PEGRatio, BookValue, DividendYield,
#        EPS, RevenuePerShareTTM, ProfitMargin, OperatingMarginTTM,
#        ReturnOnAssetsTTM, ReturnOnEquityTTM, RevenueTTM, GrossProfitTTM,
#        Beta, 52WeekHigh, 52WeekLow, AnalystTargetPrice 等

# 损益表（年度/季度）
resp = requests.get(BASE_URL, params={
    "function": "INCOME_STATEMENT",
    "symbol": "AAPL",
    "apikey": key
}).json()

# 资产负债表
resp = requests.get(BASE_URL, params={
    "function": "BALANCE_SHEET",
    "symbol": "AAPL",
    "apikey": key
}).json()

# 现金流量表
resp = requests.get(BASE_URL, params={
    "function": "CASH_FLOW",
    "symbol": "AAPL",
    "apikey": key
}).json()

# 技术指标（RSI）
resp = requests.get(BASE_URL, params={
    "function": "RSI",
    "symbol": "AAPL",
    "interval": "daily",
    "time_period": 14,
    "series_type": "close",
    "apikey": key
}).json()
```

### 变量配置
```python
DATA_PROVIDER = "alphavantage"
DATA_API_KEY  = ALPHAVANTAGE_API_KEY   # "P1X33VRNKH044K7N"
```

### ⚠️ Alpha Vantage 局限性
| 项目 | 说明 |
|---|---|
| 频率限制 | 免费版 5次/分钟，500次/天，分析多只股票时需间隔调用 |
| A股支持 | 不支持 A 股，A 股请用 baostock 或 thsdk |
| 实时性 | 免费版延迟 15-20 分钟 |

---

## 网页搜索数据源（tavily_extract / tavily_search）

当无 API Key 或需要补充特定资讯时，使用 OpenClaw 内置工具直接爬取或限域名搜索。

### 调用方式

**直接爬取指定页面（精准）：**
```
工具：tavily_extract
参数：urls=["https://目标页面URL"]
```

**限定域名搜索（语义搜索 + 指定来源）：**
```
工具：tavily_search
参数：query="贵州茅台 2024年报", include_domains=["eastmoney.com", "cninfo.com.cn"]
```

---

### A股/港股数据网站

| 网站 | 域名 | 适合获取 | 推荐用途 |
|---|---|---|---|
| 东方财富 | `eastmoney.com` | 行情/资讯/财报/研报/公告 | A 股综合首选 |
| 雪球 | `xueqiu.com` | 财务数据/估值/讨论 | 基本面分析+舆情 |
| 财联社电报 | `cls.cn` | 实时财经快讯 | 新闻情绪分析 |
| Macrotrends | `macrotrends.net` | 港股/全球长期财务历史 | 历史趋势分析 |
| 亿牛网 | `eniu.com` | A 股数据分析/估值 | 指标速查 |
| 巨潮资讯 | `cninfo.com.cn` | A 股官方公告/年报/季报 | 权威公告来源 |

**常用爬取示例（A股）：**
```python
# 东方财富个股（贵州茅台）
urls = ["https://quote.eastmoney.com/sh600519.html"]

# 巨潮官方公告
urls = ["https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"]

# 财联社快讯
urls = ["https://www.cls.cn/telegraph"]

# 雪球个股
urls = ["https://xueqiu.com/S/SH600519"]

# 亿牛网估值
urls = ["https://eniu.com/gu/sh600519"]
```

---

### 美股数据网站

| 网站 | 域名 | 适合获取 | 推荐用途 |
|---|---|---|---|
| Finviz | `finviz.com` | 多因子指标一览/筛股 | 快速筛股 |
| Investing.com | `investing.com` | 全球行情/分析师评级 | 多市场报价 |
| Stock Analysis | `stockanalysis.com` | 财务报表/比率/历史数据 | 免费财务数据首选 |
| Market Chameleon | `marketchameleon.com` | 期权数据/波动率/财报日历 | 期权策略参考 |
| ETF DB | `etfdb.com` | ETF 持仓/分类/资金流 | ETF 研究 |

**常用爬取示例（美股）：**
```python
# Stock Analysis 财务报表（AAPL）
urls = ["https://stockanalysis.com/stocks/aapl/financials/"]
urls = ["https://stockanalysis.com/stocks/aapl/financials/balance-sheet/"]
urls = ["https://stockanalysis.com/stocks/aapl/financials/cash-flow-statement/"]

# Finviz 股票概览
urls = ["https://finviz.com/quote.ashx?t=AAPL"]

# Market Chameleon 期权与波动率
urls = ["https://marketchameleon.com/Overview/AAPL/"]

# ETF DB 特定 ETF
urls = ["https://etfdb.com/etf/QQQ/"]

# Investing.com 股票详情
urls = ["https://www.investing.com/equities/apple-computer-inc"]
```

---

### 限域名搜索示例

```python
# 只在东方财富和雪球搜索 A 股资讯
tavily_search(
    query="宁德时代 2024 财报 分析",
    include_domains=["eastmoney.com", "xueqiu.com"]
)

# 只在巨潮搜索官方公告
tavily_search(
    query="贵州茅台 2024年报",
    include_domains=["cninfo.com.cn"]
)

# 只在美股数据站搜索
tavily_search(
    query="NVDA revenue growth 2024",
    include_domains=["stockanalysis.com", "macrotrends.net"]
)
```

---

## 推荐组合策略

| 场景 | 推荐方案 |
|---|---|
| 美股深度分析 | `yfinance` 或 `alphavantage`（财务全面）|
| 美股无 key 快速分析 | `tavily_extract` → `stockanalysis.com` / `finviz.com` |
| 美股期权/波动率 | `tavily_extract` → `marketchameleon.com` |
| 美股 ETF 研究 | `tavily_extract` → `etfdb.com` |
| A股基本面分析 | `baostock`（免费、财务季报完整）|
| A股实时行情+大单 | `thsdk`（Level2实时）|
| A股综合（基本面+行情） | `baostock`（财务）+ `thsdk`（行情）|
| A股资讯/舆情 | `tavily_search` → `eastmoney.com` + `cls.cn` + `xueqiu.com` |
| A股官方公告 | `tavily_extract` → `cninfo.com.cn` |
| A股历史估值 | `tavily_extract` → `eniu.com` / `macrotrends.net` |

---

## 数据适配器伪代码

在 skill 中使用时，用以下伪代码模式适配不同数据源：

```python
def get_price_data(symbol, start, end, provider=DATA_PROVIDER):
    if provider == "yfinance":
        import yfinance as yf
        return yf.Ticker(symbol).history(start=start, end=end)
    elif provider == "baostock":
        import baostock as bs
        bs.login()
        rs = bs.query_history_k_data_plus(symbol, "date,open,high,low,close,volume", start, end, frequency="d", adjustflag="2")
        return rs.get_data()
    elif provider == "thsdk":
        from thsdk import THS
        from datetime import datetime
        ths = THS(); ths.connect()
        resp = ths.klines(symbol, datetime.fromisoformat(start), datetime.fromisoformat(end), interval="day")
        ths.disconnect()
        return resp.to_dataframe()

def get_financial_metrics(symbol, provider=DATA_PROVIDER):
    if provider == "yfinance":
        import yfinance as yf
        info = yf.Ticker(symbol).info
        return {field: info.get(yf_key) for field, yf_key in FIELD_MAP.items()}
    elif provider == "baostock":
        import baostock as bs
        bs.login()
        # 组合多个 query_*_data 接口
        ...
```
