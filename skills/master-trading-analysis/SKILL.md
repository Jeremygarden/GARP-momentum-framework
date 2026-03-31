---
name: master-trading-analysis
description: 综合股票投资分析框架，集成12位投资大师的分析方法论（巴菲特/芒格/格雷厄姆/林奇/伯里/伍德/达摩达兰/帕布莱/费雪/阿克曼/德鲁肯米勒/尊加华拉）以及量化基本面/技术面/估值/情绪/风险分析。当用户需要多维度分析股票、生成投资信号、评估仓位风险、做估值建模时使用。支持 A股/港股/美股。数据源通过 DATA_PROVIDER 变量切换（yfinance / baostock / thsdk）。
---

# master-trading-analysis 综合交易分析框架

从 ai-hedge-fund 项目提炼的完整投资分析方法论，无需运行代码即可指导 OpenClaw investor agent 完成专业级股票分析。

> ⚠️ 仅供研究参考，不构成投资建议。

---

## 分析模块索引

| 模块 | 文件 | 说明 |
|---|---|---|
| **数据接入** | `references/data-providers.md` | yfinance / baostock / thsdk 三种数据源接入方式 |
| **基本面分析** | `references/fundamentals.md` | 盈利能力/增长/健康度/估值比率评分体系 |
| **技术面分析** | `references/technicals.md` | 趋势/均值回归/动量/波动率四维度技术信号 |
| **估值模型** | `references/valuation.md` | DCF/EV-EBITDA/剩余收益三情景估值 |
| **情绪分析** | `references/sentiment.md` | 内部交易 + 新闻情绪加权信号 |
| **风险管理** | `references/risk-manager.md` | 波动率调整仓位限制/相关性调整/止损规则 |
| **组合管理** | `references/portfolio-manager.md` | 多信号加权聚合/下单决策框架 |
| **Warren Buffett** | `references/analysts/warren-buffett.md` | 护城河/盈利能力/FCF/稳定性 |
| **Charlie Munger** | `references/analysts/charlie-munger.md` | ROIC/定价权/可预测性/估值 |
| **Ben Graham** | `references/analysts/ben-graham.md` | 净流动资产/格雷厄姆数/安全边际 |
| **Peter Lynch** | `references/analysts/peter-lynch.md` | PEG/成长性/FCF/日常选股 |
| **Michael Burry** | `references/analysts/michael-burry.md` | FCF收益率/EV/EBIT/逆向情绪 |
| **Cathie Wood** | `references/analysts/cathie-wood.md` | 颠覆创新/研发/TAM/超高增长 |
| **Aswath Damodaran** | `references/analysts/aswath-damodaran.md` | DCF/WACC/成长-风险-相对估值 |
| **Mohnish Pabrai** | `references/analysts/mohnish-pabrai.md` | 下行保护/FCF收益率/翻倍潜力 |
| **Phil Fisher** | `references/analysts/phil-fisher.md` | 成长质量/利润率/管理效率/调研 |
| **Bill Ackman** | `references/analysts/bill-ackman.md` | 品牌护城河/激进主义/DCF |
| **Stanley Druckenmiller** | `references/analysts/stanley-druckenmiller.md` | 宏观/动量/非对称风险 |
| **Growth Agent** | `references/analysts/growth-agent.md` | 纯成长因子/加速/趋势回归 |
| **GARP+质量动能 v2.0** | `references/garp-quality-momentum/README.md` | 五因子量化评分模型（含市场状态动态权重切换）|

---

## 标准分析流程

```
1. 获取数据          → 参考 data-providers.md 选择数据源
2. 基本面评分        → fundamentals.md 打分（满分100）
3. 技术信号          → technicals.md 生成 bullish/bearish/neutral
4. 估值建模          → valuation.md 计算内在价值与安全边际
5. 大师视角（选2-3） → analysts/*.md 各自打分
6. 情绪过滤          → sentiment.md 加权情绪信号
7. 风险核查          → risk-manager.md 确认仓位上限
8. 综合决策          → portfolio-manager.md 聚合最终信号
```

## 信号定义

所有模块统一输出：
```json
{
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": 0-100,
  "reasoning": "简短说明"
}
```

## 数据变量配置

两个全局变量控制数据接入，在 `references/data-providers.md` 中详细说明：

- **`DATA_PROVIDER`** — 数据源类型：`yfinance` | `baostock` | `thsdk`
- **`DATA_API_KEY`** — API 密钥（仅 yfinance/financialdatasets 类型需要；thsdk 使用账号体系）
