# 情绪分析（Sentiment Agent）

来源：`ai-hedge-fund/src/agents/sentiment.py`

## 两类信号来源

### 1. 内部交易信号（Insider Trades）
权重：**30%**

```
insider_trades = 获取近1000条内部人员交易记录

transaction_shares = 每笔交易的股数（正数=买入，负数=卖出）

insider_signals = [
    "bullish" if shares > 0 else "bearish"
    for shares in transaction_shares
]
```

### 2. 新闻情绪信号（Company News）
权重：**70%**

```
company_news = 获取近100条公司新闻（含情绪标注）

news_signals = [
    "bullish"  if sentiment == "positive" else
    "bearish"  if sentiment == "negative" else
    "neutral"
    for each news_item
]
```

---

## 综合信号计算

```python
insider_weight = 0.30
news_weight    = 0.70

bullish_score = (
    insider_signals.count("bullish") × insider_weight +
    news_signals.count("bullish")    × news_weight
)
bearish_score = (
    insider_signals.count("bearish") × insider_weight +
    news_signals.count("bearish")    × news_weight
)

if bullish_score > bearish_score:
    signal = "bullish"
    confidence = bullish_score / (bullish_score + bearish_score) × 100
elif bearish_score > bullish_score:
    signal = "bearish"
    confidence = bearish_score / (bullish_score + bearish_score) × 100
else:
    signal = "neutral"
    confidence = 50
```

---

## 使用指引

**优先级**：情绪分析作为辅助过滤器，而非主信号。

| 情景 | 建议 |
|---|---|
| 基本面 bullish + 情绪 bullish | 加强确信度 |
| 基本面 bullish + 情绪 bearish | 降低仓位或等待情绪改善 |
| 大量内部人净卖出（>70% bearish） | 重要警告信号，不宜追涨 |
| 大量内部人净买入（>70% bullish） | 支持性信号 |

---

## 数据来源建议

| 场景 | 内部交易数据 | 新闻情绪数据 |
|---|---|---|
| 美股 | yfinance `insider_transactions` | `company_news`（需情绪API）|
| A股 | baostock `query_stock_basic` | 东方财富 mx-search skill |
| 全市场 | thsdk `news()` | thsdk `news()` 配合 LLM 情绪分析 |

**简单代替方案**：用 mx-search skill 搜索公司最新资讯，让 investor agent 自行判断情绪倾向（正面/负面/中性）。
