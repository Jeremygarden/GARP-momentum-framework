# 技术面分析（Technicals Agent）

来源：`ai-hedge-fund/src/agents/technicals.py`

四个维度各自产生 signal + confidence，最终加权合并。

---

## 1. 趋势跟踪信号（Trend Following）

### 计算指标
- **EMA系列**：EMA(8)、EMA(21)、EMA(55)
- **ADX**：平均趋向指数（衡量趋势强度）
- **趋势得分** = EMA8>EMA21 (+1) + EMA21>EMA55 (+1) + 价格>EMA8 (+1) + ADX>25 (+1)

### 信号规则
| 趋势得分 | 信号 | 置信度 |
|---|---|---|
| ≥ 3 | bullish | trend_score / 4 |
| ≤ 1 | bearish | (4 - trend_score) / 4 |
| 2 | neutral | 0.5 |

---

## 2. 均值回归信号（Mean Reversion）

### 计算指标
- **Z-score**：(当前价 - 52周均值) / 52周标准差
- **布林带**：20日均值 ± 2×标准差
- **BB位置**：(当前价 - 下轨) / (上轨 - 下轨)，范围 0-1
- **RSI(14)** 和 **RSI(28)**

### 信号规则
| 条件 | 信号 | 置信度 |
|---|---|---|
| Z-score < -2 **且** BB位置 < 0.2 | bullish | min(abs(z)/4, 1.0) |
| Z-score > +2 **且** BB位置 > 0.8 | bearish | min(abs(z)/4, 1.0) |
| 其他 | neutral | 0.5 |

**辅助参考（RSI）：**
- RSI(14) < 30：超卖（支持 bullish）
- RSI(14) > 70：超买（支持 bearish）

---

## 3. 动量信号（Momentum）

### 计算指标
- **1个月收益率**：return_1m = (P_now - P_21d_ago) / P_21d_ago
- **3个月收益率**：return_3m = (P_now - P_63d_ago) / P_63d_ago
- **12个月收益率**：return_12m = (P_now - P_252d_ago) / P_252d_ago
- **相对强度**：各周期加权综合

### 信号规则
| 条件 | 信号 | 置信度 |
|---|---|---|
| 3个月和12个月收益均 > 0 | bullish | min(avg_return/0.25, 1.0) |
| 3个月和12个月收益均 < 0 | bearish | min(abs(avg_return)/0.25, 1.0) |
| 混合 | neutral | 0.5 |

---

## 4. 波动率信号（Volatility）

### 计算指标
- **历史波动率**：21日收益率标准差 × √252（年化）
- **波动率均值（VMA）**：63日移动平均
- **波动率制度**：当前波动率 / VMA
- **波动率 Z-score**：(当前 - VMA) / 63日标准差
- **ATR 比率**：ATR / 收盘价

### 信号规则
| 条件 | 信号 | 置信度 |
|---|---|---|
| 波动率制度 < 0.8 **且** Z-score < -1 | bullish | min(abs(z)/3, 1.0) |
| 波动率制度 > 1.2 **且** Z-score > +1 | bearish | min(abs(z)/3, 1.0) |
| 其他 | neutral | 0.5 |

---

## 5. 最终信号合并（加权）

```
权重：趋势(0.25) + 均值回归(0.25) + 动量(0.30) + 波动率(0.20) = 1.0

信号编码：bullish=1, neutral=0, bearish=-1

combined_score = Σ (signal_i × confidence_i × weight_i)

if combined_score > 0.2:  final = "bullish",  conf = abs(combined_score) × 100
if combined_score < -0.2: final = "bearish",  conf = abs(combined_score) × 100
else:                      final = "neutral",  conf = 50
```

---

## 关键数据需求

```
必需：至少252个交易日的日OHLCV数据（约1年）
推荐：500日（约2年）用于稳健趋势判断
字段：date, open, high, low, close, volume
```
