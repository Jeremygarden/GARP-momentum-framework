# 估值模型（Valuation Agent）

来源：`ai-hedge-fund/src/agents/valuation.py`

使用三种估值方法加权得出内在价值，与市值对比生成信号。

---

## 三种估值方法

### 方法一：DCF（现金流折现）

**三情景模型：**

| 情景 | 增长率假设 | WACC | 权重 |
|---|---|---|---|
| 悲观（Bear） | revenue_growth × 0.5，最低 -5% | WACC + 2% | 25% |
| 基准（Base） | revenue_growth（-5% 至 +15%限制） | WACC | 50% |
| 乐观（Bull） | revenue_growth × 1.5，最高 +25% | WACC - 1% | 25% |

**WACC 估算：**
```
无风险利率 = 4.5%（10年美债近似）
风险溢价   = 5.5%
Cost of Equity = 无风险利率 + beta × 风险溢价
WACC = Cost of Equity × (1 - debt_ratio) + debt_cost × debt_ratio × (1 - tax_rate)
默认税率 = 21%，债务成本 = 5%
```

**FCF 计算（5年预测 + 永续价值）：**
```
base_fcf = 近4年平均FCF
每年 FCF_t = base_fcf × (1 + growth_rate)^t
terminal_value = FCF_5 × (1 + terminal_growth) / (WACC - terminal_growth)
terminal_growth = 2.5%（默认）

DCF_value = Σ FCF_t/(1+WACC)^t + terminal_value/(1+WACC)^5
```

**期望值：**
```
dcf_expected = 0.25×bear + 0.50×base + 0.25×bull
```

**DCF 方法权重**：整体估值中占 **50%**

---

### 方法二：EV/EBITDA 估值

```
peer_ev_ebitda = 同行业中位数 EV/EBITDA（默认用 12×）
implied_ev = peer_ev_ebitda × EBITDA
implied_equity = implied_ev - total_debt + cash
```

**EV/EBITDA 方法权重**：整体估值中占 **30%**

---

### 方法三：剩余收益模型（RIM）

```
cost_of_equity = 无风险利率 + beta × 风险溢价
residual_income = net_income - cost_of_equity × book_value
RIM_value = book_value + Σ residual_income_t/(1+cost_of_equity)^t
（预测期5年 + 永续，使用历史账面价值增速）
```

**RIM 方法权重**：整体估值中占 **20%**

---

## 综合估值与信号

```python
# 加权内在价值
intrinsic_value = (
    dcf_value    × 0.50 +
    ev_ebitda_v  × 0.30 +
    rim_value    × 0.20
)

# 安全边际（相对市值的差距）
gap = (intrinsic_value - market_cap) / market_cap

# 加权差距
weighted_gap = gap（各方法各自计算 gap 再加权）
```

### 信号规则

| 加权差距 | 信号 | 置信度计算 |
|---|---|---|
| > +15% | **bullish**（低估） | min(abs(gap)/0.30, 1.0) × 100 |
| < -15% | **bearish**（高估） | min(abs(gap)/0.30, 1.0) × 100 |
| -15% ~ +15% | **neutral** | 50 |

---

## 快速判断参考

```
安全边际 > 30%  → 强 bullish（非常低估）
安全边际 15-30% → bullish
安全边际 -15%~+15% → neutral
安全边际 -15%~-30% → bearish
安全边际 < -30% → 强 bearish（严重高估）
```

---

## 关键数据需求

```
必需：free_cash_flow（近4年），net_income，ebitda，total_debt，cash，
      book_value，market_cap，beta，revenue_growth，shares_outstanding
可选：peer_ev_ebitda（行业中位数，默认12×）
```
