# Aswath Damodaran 分析框架

来源：`ai-hedge-fund/src/agents/aswath_damodaran.py`

**核心理念**："估值大师"——用严谨的财务模型计算内在价值，以 25% 安全边际为行动基准。

---

## 三维分析体系

### 1. 增长质量分析（满分6分）

| 指标 | 条件 | 分值 |
|---|---|---|
| 营收增速 | > 15% | +2 |
| 营收增速 | > 8% | +1 |
| EPS 增速 | > 15% | +2 |
| EPS 增速 | > 8% | +1 |
| FCF 增速 | > 10% | +1 |
| 增速一致性（营收/利润同向）| 是 | +1 |

### 2. 风险评估（满分6分）

| 指标 | 条件 | 分值 |
|---|---|---|
| Beta | < 1.0（低系统风险）| +2 |
| Beta | 1.0-1.5 | +1 |
| D/E | < 1.0 | +1 |
| 利息覆盖率 | > 3× | +1 |
| 营收稳定性（低波动）| std < 10% | +1 |
| 市场地位（毛利率 > 40%）| 是 | +1 |

```python
# 权益成本估算（CAPM）
risk_free_rate = 0.045   # 4.5%（10年美债近似）
risk_premium   = 0.055   # 5.5%
cost_of_equity = risk_free_rate + beta × risk_premium
```

### 3. 相对估值（满分6分）

| 指标 | 条件 | 分值 |
|---|---|---|
| P/E vs 行业中位数 | 折价 > 20% | +2 |
| P/E vs 行业中位数 | 折价 0-20% | +1 |
| EV/EBITDA vs 行业 | 折价 > 20% | +2 |
| P/B vs 行业 | 折价 > 20% | +2 |

---

## DCF 内在价值计算

```python
# 1. 增长假设
rev_growth = clamp(revenue_growth, -0.05, 0.15)   # 限制 -5% 到 15%
terminal_growth = 0.025                             # 永续增长 2.5%

# 2. WACC
cost_of_equity = 0.045 + beta × 0.055
debt_ratio = total_debt / (total_debt + market_cap)
wacc = cost_of_equity × (1 - debt_ratio) + 0.05 × debt_ratio × 0.79

# 3. FCF 预测（5年）
base_fcf = mean(recent_4_years_fcf)
projected_fcf = [base_fcf × (1 + rev_growth)^t for t in 1..5]

# 4. 终值
terminal_value = fcf_5 × (1 + terminal_growth) / (wacc - terminal_growth)

# 5. 现值
dcf_value = Σ fcf_t/(1+wacc)^t + terminal_value/(1+wacc)^5
```

---

## 信号规则（安全边际为核心）

```
margin_of_safety = (intrinsic_value - market_cap) / market_cap

≥ +25% → bullish（显著低估，Damodaran 行动阈值）
≤ -25% → bearish（显著高估）
-25% ~ +25% → neutral
```

---

## Damodaran 式 LLM Prompt

```
你是 Aswath Damodaran AI 代理：
1. 用故事+数字驱动估值——先构建公司增长叙事，再用数字验证
2. DCF 是核心工具，但参数假设必须明确且保守
3. 用 25% 安全边际作为行动阈值
4. 将增长/风险/相对估值三角互证
5. 明确指出最大不确定性（什么假设最影响内在价值）

分析结构：
1. 公司处于哪个生命周期阶段？（早期/成长/成熟/衰退）
2. 可持续增长率是多少？
3. WACC 合理范围？
4. 内在价值 vs 市价差距多少？
5. 最大风险点是什么？
```

---

## 关键指标速查

```
必需：FCF（近4年），revenue_growth，beta，total_debt，market_cap
估值：安全边际 = (DCF内在价值 - 市值) / 市值
阈值：安全边际 > 25% → bullish；< -25% → bearish
```
