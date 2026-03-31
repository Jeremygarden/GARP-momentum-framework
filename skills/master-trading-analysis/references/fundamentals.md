# 基本面分析（Fundamentals Agent）

来源：`ai-hedge-fund/src/agents/fundamentals.py`

## 四维评分体系

总分 = 盈利能力 + 增长能力 + 财务健康 + 估值比率，每维最高若干分，综合判断 bullish/neutral/bearish。

---

## 1. 盈利能力评分

| 指标 | 阈值 | 分值 |
|---|---|---|
| ROE | > 15% | +1 |
| 净利润率 | > 20% | +1 |
| 营业利润率 | > 15% | +1 |

**信号规则：**
- 得分 ≥ 2 → **bullish**
- 得分 = 0 → **bearish**
- 得分 = 1 → **neutral**

---

## 2. 增长能力评分

| 指标 | 阈值 | 分值 |
|---|---|---|
| 营收增速（YoY） | > 10% | +1 |
| 盈利增速（EPS YoY） | > 10% | +1 |
| 连续增长期数（≥4期） | 营收/利润均正 | +1 |

**信号规则：**
- 得分 ≥ 2 → **bullish**
- 得分 = 0 → **bearish**
- 得分 = 1 → **neutral**

---

## 3. 财务健康评分

| 指标 | 阈值 | 分值 | 说明 |
|---|---|---|---|
| 流动比率 | > 1.5 | +1 | 强流动性 |
| D/E（负债权益比） | < 0.5 | +1 | 保守负债水平 |
| FCF/EPS | FCF > EPS × 0.8 | +1 | 强自由现金流转化 |

**信号规则：**
- 得分 ≥ 2 → **bullish**
- 得分 = 0 → **bearish**
- 得分 = 1 → **neutral**

---

## 4. 估值比率评分（价格比率）

| 指标 | 警戒阈值（过高=bearish倾向） | 说明 |
|---|---|---|
| P/E | > 25 | 偏高 |
| P/B | > 3 | 偏高 |
| P/S | > 5 | 偏高 |

**评分逻辑（反向）：**
- 超过阈值数量 = 0 → **bullish**
- 超过阈值数量 = 1-2 → **neutral**
- 超过阈值数量 ≥ 3 → **bearish**

---

## 综合信号聚合

将以上四个维度的信号计票：
```
bullish_count = [维度1信号, 维度2信号, 维度3信号, 维度4信号].count("bullish")
bearish_count = 同上

if bullish_count > bearish_count:
    final_signal = "bullish"
    confidence = (bullish_count / 4) × 100
elif bearish_count > bullish_count:
    final_signal = "bearish"
    confidence = (bearish_count / 4) × 100
else:
    final_signal = "neutral"
    confidence = 50
```

---

## 关键数据需求

```
必需：revenue, net_income, operating_income, free_cash_flow,
      current_assets, current_liabilities, total_debt, shareholders_equity,
      market_cap, eps, price_to_earnings, price_to_book, price_to_sales,
      return_on_equity, net_margin, operating_margin,
      revenue_growth, earnings_growth（近4-8期数据）
```
