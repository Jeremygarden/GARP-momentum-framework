# 风险管理（Risk Manager）

来源：`ai-hedge-fund/src/agents/risk_manager.py`

## 核心功能

为每只股票计算：
1. **波动率调整后的仓位上限**
2. **相关性调整**（减少组合内高相关资产的集中度）
3. **当前仓位与上限对比**，输出剩余可操作空间

---

## 一、波动率调整仓位限制

年化波动率（`annualized_volatility`）= 21日日收益率标准差 × √252

| 年化波动率区间 | 最大仓位（占组合） | 说明 |
|---|---|---|
| < 15% | **25%** | 低波动稳健股，允许较大仓位 |
| 15% - 30% | **15%-20%** | 标准区间，线性内插 |
| 30% - 50% | **10%-15%** | 高波动，控制风险敞口 |
| > 50% | **10%** | 极高波动，严格限制 |

```python
# 精确计算
def vol_adjusted_limit(annual_vol):
    if annual_vol < 0.15:
        return 0.25
    elif annual_vol < 0.30:
        return 0.20 - ((annual_vol - 0.15) / 0.15) × 0.05  # 线性插值 20%→15%
    elif annual_vol < 0.50:
        return 0.15 - ((annual_vol - 0.30) / 0.20) × 0.05  # 线性插值 15%→10%
    else:
        return 0.10
```

---

## 二、相关性调整

若组合中已有多只高相关资产（如同行业股票），对新标的的仓位上限打折：

```
若 avg_correlation > 0.7（与现有持仓高度相关）：
    仓位上限 × 0.7（减少30%）

若 avg_correlation > 0.5（中度相关）：
    仓位上限 × 0.85（减少15%）

若 avg_correlation ≤ 0.5（低相关）：
    仓位上限不变
```

---

## 三、最大持仓股票数

```
max_positions = 10（默认，可配置）

若当前持仓 = max_positions:
    不允许新增任何仓位（0% 上限）
```

---

## 四、现有仓位核查

```python
current_position_value = abs(long_value - short_value)

# 剩余可操作额度
remaining_limit = max(0, position_limit_value - current_position_value)
remaining_shares = int(remaining_limit / current_price)
```

---

## 五、信号输出格式

```json
{
  "ticker": "AAPL",
  "signal": "bullish",           // 透传综合分析信号
  "confidence": 72,
  "current_price": 185.50,
  "current_position_value": 9000,
  "position_limit": 25000,       // 波动率调整后的总限额（元）
  "remaining_position_limit": 16000,
  "max_shares": 86,              // 剩余可买入最大股数
  "annualized_volatility": 0.22,
  "volatility_percentile": 45    // 相对历史波动率的百分位
}
```

---

## 六、简化快速评估

当没有完整价格历史时，可用以下经验规则：

| 股票类型 | 典型波动率 | 建议最大仓位 |
|---|---|---|
| 大盘蓝筹（茅台/苹果/微软） | 15-20% | 20-25% |
| 成长股（科技/新能源） | 25-40% | 12-18% |
| 小盘/题材股 | 40-60% | 8-12% |
| 加密货币/概念股 | > 60% | 5-10% |

---

## 关键数据需求

```
必需：至少126日（6个月）日价格数据计算波动率
可选：组合现有持仓数据、股票间相关性矩阵
```
