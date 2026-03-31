# 组合管理（Portfolio Manager）

来源：`ai-hedge-fund/src/agents/portfolio_manager.py`

## 功能

汇聚所有分析师信号 + 风险管理输出，由 LLM 生成最终交易决策。

---

## 一、信号聚合格式

```json
{
  "AAPL": {
    "warren_buffett_agent":       {"sig": "bullish",  "conf": 85},
    "fundamentals_agent":         {"sig": "bullish",  "conf": 70},
    "technicals_agent":           {"sig": "neutral",  "conf": 55},
    "valuation_agent":            {"sig": "bullish",  "conf": 78},
    "sentiment_analyst_agent":    {"sig": "bullish",  "conf": 65},
    "michael_burry_agent":        {"sig": "bearish",  "conf": 60}
  }
}
```

风险管理器提供的约束：
```json
{
  "AAPL": {
    "remaining_position_limit": 18000,
    "max_shares": 97,
    "current_price": 185.50
  }
}
```

---

## 二、允许操作集合

```python
# 对每只股票计算允许操作
allowed_actions = {}

# 买入（多头）
if cash >= price:
    max_buy = min(cash // price, max_shares)
    if max_buy > 0:
        allowed_actions["buy"] = max_buy

# 卖出（平多头）
if long_position > 0:
    allowed_actions["sell"] = long_position

# 做空
if margin_available > 0:
    max_short = min(max_shares, margin_available // price)
    if max_short > 0:
        allowed_actions["short"] = max_short

# 平空
if short_position > 0:
    allowed_actions["cover"] = short_position

# 持有（始终允许）
allowed_actions["hold"] = 0
```

---

## 三、LLM 决策 Prompt 框架

```
你是组合经理，整合以下分析师信号和风险约束生成交易决策。

原则：
1. 信号一致性越高，执行力度越大
2. 置信度越高，权重越重
3. 严格遵守风险经理设定的仓位上限
4. 当信号混合时，倾向保守（hold 或小仓位）
5. 不发明数据，不超出 allowed_actions 的范围

输入：
- 分析师信号：{signals_by_ticker}
- 允许操作：{allowed_actions}
- 当前组合：{portfolio}

输出 JSON：
{
  "AAPL": {
    "action": "buy" | "sell" | "short" | "cover" | "hold",
    "quantity": int,
    "confidence": 0-100,
    "reasoning": "简短说明"
  }
}
```

---

## 四、信号一致性快速判断

| bullish 信号数 / 总信号数 | 建议操作 |
|---|---|
| ≥ 70% 且 avg_confidence > 70 | **积极买入**（接近 max_shares）|
| 60%-70% | **适量买入**（max_shares × 50-70%）|
| 40%-60%（混合） | **观望/小仓位试探** |
| ≤ 30% | **卖出 / 做空** |

---

## 五、决策输出格式

```json
{
  "AAPL": {
    "action": "buy",
    "quantity": 50,
    "confidence": 78,
    "reasoning": "5/6 analysts bullish, avg confidence 74%, within risk limits"
  },
  "TSLA": {
    "action": "hold",
    "quantity": 0,
    "confidence": 52,
    "reasoning": "Mixed signals: 3 bullish, 2 bearish, 1 neutral. Await clarity."
  }
}
```
