---
name: stock-knowledge-base
description: 量化投资与股票分析知识库，涵盖经典量化策略、技术指标、风险控制和回测工具。当用户需要了解或应用以下内容时使用：均值回归/动量/因子投资策略、MA/MACD/RSI/布林带等技术指标、止损/仓位管理/回撤控制等风控方法、backtrader回测框架使用、OpenClaw价格监控示例。提供方法论参考，辅助投资决策分析。
---

# stock-knowledge-base 量化投资知识库

专为 OpenClaw AI Agent 打造的量化投资与股票分析知识库，系统性整理了核心方法论。

## 知识库目录

| 模块 | 内容 | 路径 |
|---|---|---|
| 量化策略 | 均值回归、动量、配对交易 | `references/strategies/` |
| 技术指标 | MA/MACD/RSI/布林带等 | `references/indicators/` |
| 风险管理 | 止损策略、仓位管理(Kelly) | `references/risk-management/` |
| 实战示例 | 双均线策略、价格监控 | `references/examples/` |
| 工具 | Backtrader 回测框架 | `references/tools/` |

## 使用方式

按需读取对应 references 文件。示例：

- 了解均值回归 → 读取 `references/strategies/mean-reversion/simple-mean-reversion.md`
- 配置止损 → 读取 `references/risk-management/stop-loss/fixed-percentage.md`
- RSI 指标 → 读取 `references/indicators/momentum/rsi.md`
- Kelly 仓位 → 读取 `references/risk-management/position-sizing/kelly-criterion.md`
- 双均线完整策略 → 读取 `references/examples/complete/dual-ma.md`

## 策略速查

**均值回归** (`references/strategies/mean-reversion/`)
- `simple-mean-reversion.md` — 简单均值回归
- `bollinger-mean-reversion.md` — 布林带均值回归
- `pairs-trading.md` — 配对交易

**动量策略** (`references/strategies/momentum/`)
- `simple-momentum.md` — 简单动量策略

**技术指标** (`references/indicators/`)
- `trend/ma.md`, `trend/macd.md` — 趋势指标
- `momentum/rsi.md` — 动量指标
- `volatility/bollinger.md` — 波动率指标

**风控** (`references/risk-management/`)
- `stop-loss/fixed-percentage.md` — 固定比例止损
- `stop-loss/atr-stop.md` — ATR动态止损
- `position-sizing/kelly-criterion.md` — Kelly公式仓位管理
