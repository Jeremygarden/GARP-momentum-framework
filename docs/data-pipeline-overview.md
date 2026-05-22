# GARP 框架数据链路全景

> 最后更新：2026-05-21（补强版，基于 a-stock-data V3.1 实测）
> 权威来源：本文件 + `docs/migration-risk-validation.md`

---

## 七层架构总览

```
L1 实时行情层   腾讯财经(估值) + mootdx(盘口/K线) + 百度股市通(MA均线) + yfinance(港美股)
L2 研报层       妙想 MX-FinSearch(AI解读) + 东财 reportapi(列表/PDF) + 同花顺一致预期
L3 信号层       妙想 MX-StockPick + auto_garp_score() + 东财push2(资金流) + 龙虎榜 + 解禁
L4 资金面层     东财 datacenter(融资融券/大宗/股东户数/分红) + push2his(120日资金流)
L5 新闻层       财联社 cls.cn(直连) + 东财新闻 + Tavily(宏观兜底)
L6 基础数据层   妙想 MX-Data(深度财务) + 东财ZYZBAjaxNew(财务增速) + yfinance(前复权K线) + mootdx(37字段) [baostock备用🔒]
L7 公告层       巨潮 cninfo(直连) + mootdx F10
```

---

## L1 · 实时行情层

| 数据项 | 主力来源 | 协议 | 兜底/备注 |
|--------|---------|------|----------|
| PE(TTM)/PE(静)/PB/市值/换手率/涨跌停/量比/振幅 | 腾讯财经 `qt.gtimg.cn` | HTTP GET/GBK | — |
| 实时报价46字段 + 五档盘口 + 逐笔成交 | mootdx TCP 7709 | TCP 二进制 | 延迟64ms(Azure实测) |
| K线（多周期）| mootdx TCP 7709 | TCP 二进制 | 百度股市通 |
| K线 + MA5/MA10/MA20（直带均线）| 百度股市通 `finance.pae.baidu.com` | HTTP | — |
| 港股/美股实时价格 | yfinance | HTTP | 腾讯财经港股格式 `hk00700` |
| 指数/ETF | 腾讯财经（sh000001 等）| HTTP | — |

> ⚠️ **mootdx 不提供 PE/PB/市值**，这些字段走腾讯财经。
> ⚠️ **mootdx 不支持前复权**（实测所有复权参数无效），历史K线前复权走 baostock。

---

## L2 · 研报层

| 数据项 | 主力来源 | 协议 | 状态 |
|--------|---------|------|------|
| AI研报解读 + 选股推荐 | **妙想 MX-FinSearch**（保留）| MX-Skill | 主力，不替换 |
| 研报列表 + 评级 + 三年EPS预测 | 东财 `reportapi.eastmoney.com` | HTTP | 并联补强 |
| 研报 PDF 下载 | 东财 `pdf.dfcfw.com` | HTTP（需 Referer）| — |
| 机构一致预期 EPS | 同花顺 `basic.10jqka.com.cn` | HTTP/HTML | — |
| NL 语义搜索研报 | iwencai OpenAPI | HTTPS（需 Key）| 可选 |

---

## L3 · 信号层

| 数据项 | 主力来源 | 协议 | 状态 |
|--------|---------|------|------|
| **AI 选股评分/推荐** | **妙想 MX-StockPick**（保留）| MX-Skill | 主力，不替换 |
| GARP 五因子自动评分 | `auto_garp_score()` | Python本地 | 并联，与 MX 交叉验证 |
| 个股资金流（分钟级，主力/大单/超大单）| 东财 `push2.eastmoney.com/fflow/kline` | HTTP | 主力 |
| 个股资金流兜底 | thsdk `big_order_flow()` | SDK | ⚠️ 需重新鉴权，当前不可用 |
| 当日强势股 + 题材归因 | 同花顺热点 | HTTP（零鉴权）| — |
| 北向资金分钟级 | 同花顺北向 + 本地缓存 | HTTP | — |
| 概念板块归属（行业/概念/地域）| 百度股市通 | HTTP | — |
| 🆕 龙虎榜席位 + 机构动向 | 东财 `datacenter-web` `RPT_DAILYBILLBOARD_DETAILSNEW` | HTTP | GARP Layer4 新维度 |
| 🆕 全市场龙虎榜 | 东财 datacenter-web | HTTP | — |
| 🆕 限售解禁日历（未来90天）| 东财 datacenter-web `RPT_LIFT_STAGE` | HTTP | 风险层 |
| 行业板块涨跌排名 | 东财 push2 `m:90+t:2` | HTTP | — |

> 盘后注意：东财 push2 盘后重定向至 push2delay，Azure 访问超时属正常，资金流信号在盘中使用。

---

## L4 · 资金面 / 筹码层

| 数据项 | 主力来源 | 状态 |
|--------|---------|------|
| 融资融券明细（日级）| 东财 datacenter | — |
| 🆕 大宗交易（价/量/营业部/溢价率）| 东财 datacenter | — |
| 🆕 股东户数变化（季度/集中度）| 东财 datacenter | — |
| 分红送转历史 | 东财 datacenter | — |
| 个股资金流 120 日（日级）| 东财 `push2his` | — |

---

## L5 · 新闻层

| 数据项 | 主力来源 | 状态 |
|--------|---------|------|
| 🆕 财联社分钟级快讯（含关联股票代码）| 直连 `cls.cn` HTTP | 已替代 Tavily 爬取 |
| 个股新闻流 | 东财 `search-api-web` JSONP | — |
| 全球财经资讯 | 东财 `np-weblist`（需 req_trace UUID）| — |
| 宏观趋势 / 网搜补充 | Tavily | 保留，仅宏观兜底 |

---

## L6 · 基础数据层

| 数据项 | 主力来源 | 状态 |
|--------|---------|------|
| **深度财务（ROE/ROIC/FCF/估值历史）** | **妙想 MX-Data**（保留）| 主力，不替换 |
| 季报快照 37 字段（EPS/ROE/净利）| mootdx finance TCP | 轻量快照 |
| F10 公司资料（9大类）| mootdx F10 TCP | — |
| 行业/总股本/流通股/上市日期 | 东财 push2 | — |
| ~~财报三表~~ | ~~新浪财经~~ | ❌ **接口已失效，废弃** |
| **A股财务增速（ROE/毛利率/负债率/YOY）** | **东财 `ZYZBAjaxNew`**（HTTPS）| ✅ 当前主力（baostock TCP封锁后迁移 2026-05-22）|
| **A股历史K线（前复权）** | **yfinance `auto_adjust=True`**（HTTPS）| ✅ 当前主力（baostock TCP封锁后迁移 2026-05-22）|
| baostock 财务+K线（备用）| baostock TCP 9898 | ⚠️ Azure NSG封锁，代码保留，`DATA_SOURCE="baostock"` 可切回 |
| 港股/美股历史K线 | yfinance `auto_adjust=True` | — |
| 大盘情绪指标（全A PE/北向）| 东财全A估值 + Tavily | — |

---

## L7 · 公告层

| 数据项 | 主力来源 | 状态 |
|--------|---------|------|
| 🆕 沪深北交所全量公告 | 巨潮 `cninfo.com.cn`（直连，`gssh0{code}` 格式）| 已替代原有方案 |
| 最新公告摘要 | mootdx F10 | — |

---

## 冻结项（🔒 已迁移替代方案，2026-05-22 更新）

| 原数据源 | 用途 | 当前替代 | 切回条件 |
|--------|------|---------|---------|
| baostock `adjustflag=2` | GARP 动量因子前复权K线 | **yfinance `auto_adjust=True`** ✅ | Azure NSG 开放出站 TCP 9898 → 验证通过 |
| baostock `query_profit/growth/balance_data` | GARP G/Q因子多期财务增速 | **东财 `ZYZBAjaxNew`** ✅ | 同上 |

> baostock 代码完整保留在 `data/baostock_financial.py`，将 `DATA_SOURCE="baostock"` 可一键切回。
> push2/push2his 系列：东财服务端对 Azure IP 返回空响应（非 NSG 问题），无法使用。

---

## 废弃项

| 数据源 | 废弃原因 | 替代方案 |
|--------|---------|---------|
| 新浪财经三表 | 接口返回 `__ERROR:3 Service not valid` | baostock 财务接口 |
| Tavily 爬取财联社 | 不稳定 | 直连 `cls.cn` HTTP |

---

## thsdk 当前状态

- `big_order_flow()` 需要 10 位 ths_code（如 `USHA600519`），当前未登录返回"未登录"
- **东财 push2 为当前可用主链路**，thsdk 降级为"需重新鉴权才能用作兜底"
- AShare-Overnight-Arb-Trader 的资金流信号暂由东财 push2 承接

---

## PE/PB 双源对照（腾讯 vs 东财）

| 字段 | 腾讯财经 | 东财 push2 | 说明 |
|------|---------|-----------|------|
| PE(TTM) | ✅ 索引39 | ✅ f9/100 | 盘中双源校验，差异>5%告警 |
| PE(静态) | ✅ 索引52 | ❌ | 腾讯独有 |
| PB | ✅ 索引46 | ✅ f23/100 | |
| 总市值 | ✅ 索引44（亿）| ✅ f116/1e8 | |
| 换手率/涨跌停/量比 | ✅ | ❌ | 腾讯独有 |
| 资金流（主力/大单/超大单）| ❌ | ✅ | 东财独有 |
| 总股本/行业/上市日期 | ❌ | ✅ | 东财独有 |

> ⚠️ 腾讯财经索引 43 = 振幅%（不是 PB！），PB 在索引 46。

---

## 行业口径说明

东财行业分类 ≠ 申万/中信一级行业，通过 `a_stock_supplement.py` 中的 `INDUSTRY_MAP` + `map_industry()` 做映射。未映射行业自动打印 `[WARN]`，需人工添加。

---

## 相关文件

| 文件 | 内容 |
|------|------|
| `data/a_stock_supplement.py` | 补强模块全部实现代码 |
| `docs/migration-risk-validation.md` | 实测风险验证报告（含冻结决策依据）|
| `docs/garp-core-framework.md` | GARP 框架核心文档 |
| `skills/master-trading-analysis/references/data-providers.md` | 数据源接入指南 |
