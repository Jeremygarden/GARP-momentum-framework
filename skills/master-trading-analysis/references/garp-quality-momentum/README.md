# GARP+质量动能 量化评分模型 v2.0

## 策略概述

"不以便宜买平庸，只以合理买卓越。" 对传统PEG策略的修正升级，解决低PEG陷阱和高成长泡沫两大痛点。

**核心哲学**：成长是赛道给的（Beta），质量是护城河给的（Alpha），估值是纪律给的（赔率），风险管理是生存给的（底线），动量是市场确认给的（时机）。

---

## 默认五因子权重（中性市场基准）

| 因子 | 权重 | 说明 |
|---|---|---|
| 成长（Growth） | **25%** | 赛道景气 + G折扣修正 |
| 质量（Quality） | **35%** | 行业差异化质量基准 |
| 估值（Valuation） | **15%** | 修正PEG + 绝对估值 |
| 动量（Momentum） | **15%** | 价格动量 + 盈利修正动量 |
| 风险修正（Risk） | **10%** | 一票否决 + 加减分 |

> 市场状态触发时，权重按动态切换规则调整。详见 `market-regime.md`。

---

## 评分公式

```
总分 = 成长得分×25% + 质量得分×35% + 估值得分×15% + 动量得分×15% + 风险修正×10%

入选门槛：总分 > 75分 → 核心成长股资格
梯队分级：
  钻石级（核心底仓）：总分 > 85分
  黄金级（进攻仓位）：75-84分
  白银级（观察/卫星）：60-74分
  剔除名单：< 60分
```

---

## 模块索引

| 模块 | 文件 | 说明 |
|---|---|---|
| 第一层：赛道景气 | `references/garp-quality-momentum/layer1-sector.md` | TAM/CAGR/竞争格局三维赛道过滤 |
| 第二层：盈利质量 | `references/garp-quality-momentum/layer2-quality.md` | 分行业差异化质量基准 |
| 第三层：估值安全边际 | `references/garp-quality-momentum/layer3-valuation.md` | 修正PEG（G折扣）+ 绝对估值锚 |
| 第四层：风险排雷 | `references/garp-quality-momentum/layer4-risk.md` | 一票否决 + 风险加减分 |
| 第五层：动量确认 | `references/garp-quality-momentum/layer5-momentum.md` | 价格动量 + 盈利修正动量 |
| 市场状态切换 | `references/garp-quality-momentum/market-regime.md` | 四种市场状态 + 动态权重规则 |
| 执行SOP | `references/garp-quality-momentum/execution-sop.md` | 初筛→复选→评分→组合构建 |
