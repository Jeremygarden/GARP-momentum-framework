# GARP + 质量动能 v2.0 框架

A股/港股成长股筛选与评分框架，基于 GARP（Growth at a Reasonable Price）+ 质量因子 + 价格动量。

## 框架概述

五因子加权评分（满分100）：
- **G 成长性**（默认30%）：赛道景气 + G折扣修正
- **Q 质量因子**（默认30%）：分行业差异化质量基准
- **V 估值合理性**（默认20%）：修正PEG + 绝对估值锚
- **M 价格动量**（默认15%）：价格动量 + 盈利修正动量
- **R 风险修正**（固定10%）：一票否决 + 加减分，不参与动态调整

权重随市场状态动态切换（详见 `skills/master-trading-analysis/references/garp-quality-momentum/market-regime.md`）

## 目录结构

```
skills/
├── master-trading-analysis/          # 综合投资分析框架（12位大师+量化）
│   ├── SKILL.md
│   └── references/
│       ├── garp-quality-momentum/    # GARP v2.0 核心模型
│       │   ├── README.md             # 框架概述+权重+评分公式
│       │   ├── execution-sop.md      # 执行SOP（数据获取/评分/入库/榜单输出）
│       │   ├── market-regime.md      # 市场状态判断+动态权重+PEG/股息率切换
│       │   ├── layer1-sector.md      # 赛道景气筛选
│       │   ├── layer2-quality.md     # 盈利质量评分（分行业）
│       │   ├── layer3-valuation.md   # 修正PEG+绝对估值
│       │   ├── layer4-risk.md        # 风险一票否决+加减分
│       │   ├── layer5-momentum.md    # 价格+盈利修正动量
│       │   └── improvement.md        # 改进记录
│       ├── analysts/                 # 12位投资大师分析模块
│       ├── fundamentals.md
│       ├── technicals.md
│       ├── valuation.md
│       ├── sentiment.md
│       ├── risk-manager.md
│       ├── portfolio-manager.md
│       └── data-providers.md
└── AShare-Overnight-Arb-Trader/      # A股隔夜套利策略（独立）
```

## 快速开始

1. 读取 `skills/master-trading-analysis/references/garp-quality-momentum/execution-sop.md`
2. 按步骤0判断当前市场状态
3. 按步骤1-4获取数据并评分
4. 按步骤7输出榜单并入库 Bitable

## 榜单

- Bitable（2026Q1）：https://c3icju884w.feishu.cn/base/PMdqbVXrdaOM1IsZZpVcocThnDb
- 每周一 UTC 02:00 自动刷新（investor agent cron）

## 免责声明

本框架仅供研究参考，不构成任何投资建议。
