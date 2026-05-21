---
name: AShare-Overnight-Arb-Trader
description: A股隔夜套利交易策略——每日14:45精准执行的短线选股系统，通过四层过滤（大盘情绪→板块强度→个股条件→资金确认）筛选隔夜持有标的，次日10:15前全部离场。当用户需要A股尾盘选股、隔夜套利操作建议、短线入场信号、日内交易纪律执行时使用。与基本面长线分析完全独立，专注情绪周期和盘口动量。
---

# AShare-Overnight-Arb-Trader 隔夜套利策略 2.0

A股短线尾盘选股系统，基于四层过滤机制，每日 **14:45–14:55** 精准执行，次日 **10:15 前无条件离场**。

> ⚠️ 本策略仅供研究参考，不构成投资建议。短线交易存在较大风险，务必严格遵守铁律规则。

---

## 策略执行流程（每日14:45启动）

```
第一层：大盘&情绪环境（一票否决）
    ↓ 通过
第二层：板块强度筛选
    ↓ 通过
第三层：个股六维硬条件
    ↓ 通过
第四层：资金确认
    ↓ 通过
最终选定 1-3 只标的 → 14:45-14:55 建仓 → 次日10:15前清仓
```

详细评分规则见各 references 文件。

---

## 模块索引

| 模块 | 文件 | 说明 |
|---|---|---|
| 第一层：大盘情绪 | `references/layer1-market.md` | 大盘趋势/情绪周期/一票否决规则 |
| 第二层：板块强度 | `references/layer2-sector.md` | 热点板块筛选/龙头带动 |
| 第三层：个股条件 | `references/layer3-stock.md` | 六维硬条件（涨幅/量能/换手/形态等）|
| 第四层：资金确认 | `references/layer4-capital.md` | 尾盘大单/龙虎榜/盘口验证 |
| 交易铁律 | `references/trading-rules.md` | 入场/离场/风控/屏蔽清单 |
| 数据接入 | `references/data-sources.md` | thsdk+tavily 各层数据获取代码 |

---

## 信号输出格式

```json
{
  "signal": "入场" | "空仓",
  "targets": ["股票代码1", "股票代码2"],
  "entry_window": "14:45-14:55",
  "exit_rule": "次日10:15前全部清仓",
  "position_limit": "单只≤15%，总仓位≤30%",
  "reasoning": "各层通过/否决说明"
}
```

## 数据需求

> 最后更新：2026-05-21（数据链路补强）

**数据源现状：**
- **东财 push2 HTTP（当前主链路，无需鉴权）** — 替代不可用的 thsdk
- **thsdk（需重新鉴权，当前不可用）** — 原主数据源，待重新鉴权后恢复兜底
- **cls.cn 直连（主）** — 财联社快讯，替代 Tavily 爬取
- **Tavily（兜底）** — 仅在直连失败时使用

详细接入代码见 [references/data-sources.md](references/data-sources.md)。

| 层 | 数据类型 | 主数据源（当前）| 原始数据源（需鉴权）|
|---|---|---|---|
| 第一层 | 指数MA20、涨跌停数、北向资金、情绪周期 | 东财push2 HTTP + cls.cn | thsdk `klines()` |
| 第二层 | 板块涨幅排行、板块涨停数 | 东财 push2 行业板块 | thsdk `ths_industry()` |
| 第三层 | 个股K线、量比、换手率、分时、流通市值 | 腾讯财经 + mootdx TCP | thsdk `klines()` + `market_data_cn()` |
| 第四层 | 大单净流入 | **东财push2 `fflow/kline`（主）** | thsdk `big_order_flow()`（兜底，口径略有差异） |
| 第四层 | 龙虎榜 | 东财 datacenter-web `RPT_DAILYBILLBOARD` 🆕 | — |
| 新闻层 | 财联社快讯 | **cls.cn 直连 HTTP（主）** | Tavily（兜底）|
