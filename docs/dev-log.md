# GARP 框架开发日志

> 记录重大变更、架构决策和关键技术点，供回溯查看。

---

## 2026-05-21 数据链路补强 + AI 评分体系建立

### 本次变更概述

今日完成从"SDK封装层"到"直连HTTP"的数据链路补强，并建立起完整的 AI 自动评分体系（Phase 1+2）。核心工具：**a-stock-data V3.1**（开源项目，simonlin1212/a-stock-data）。

---

### 0. a-stock-data 项目概述与引入决策

**项目地址**：https://github.com/simonlin1212/a-stock-data

**选用理由**：
- 7层架构 · 28端点 · 13数据源，OpenClaw 原生兼容
- V3.0 起彻底移除 akshare 依赖，所有数据源改为直连 HTTP API
- 直接解决了 akshare pandas 3.0 兼容问题（ArrowInvalid 等）
- V3.1（2026-05-19）全量实测通过，28个端点均对 600519 验证

**使用方式**：将 SKILL.md 内容注入项目上下文，内嵌 Python 代码直接执行（不安装为 CLI）。本项目将关键接口直接吸收进 `a_stock_supplement.py`。

**依赖**：`pip install mootdx requests pandas stockstats`（零 akshare）

---

### a-stock-data 七层架构与本项目映射

```
a-stock-data 层级          本项目使用的模块/函数
──────────────────────────────────────────────────────
行情层（腾讯财经+mootdx）  → tencent_quote()
                              PE/PB/市值/换手率/量比/涨跌停
                              注意：索引46=PB，索引43=振幅（非PB！）

研报层（东财reportapi）    → get_eastmoney_reports()
                              与妙想 MX-FinSearch 并联，保留妙想不替换

信号层（东财push2）        → get_fund_flow_minute() / get_fund_flow_summary()
                              资金流分钟级，主力/大单/超大单/小单
                              ⚠️ 盘后重定向 push2delay，Azure超时，盘后静默

信号层（东财datacenter）   → get_dragon_tiger()        龙虎榜+机构席位
                              get_lockup_expiry()        限售解禁日历90天
                              (另: 大宗交易/股东户数/融资融券)

新闻层（cls.cn直连）       → get_cls_telegraph()        财联社电报
                              filter_cls_by_holdings()   持仓过滤
                              cls_keyword_alert()         关键词风险告警

公告层（巨潮cninfo）       → get_cninfo_announcements()
                              ⚠️ orgId格式: gssh0600519（有0）
                              ⚠️ announcementTime是毫秒时间戳int，非字符串

基础数据层（东财push2）    → eastmoney_stock_info()
                              行业/总股本/流通股/上市日期（盘后静默）
```

---

### a-stock-data 引入过程中发现的关键 Bug 和坑

#### Bug 1：巨潮公告 orgId 格式错误
- **错误**：`gssh600519`（无0）→ 返回空
- **正确**：`gssh0600519`（有0）→ 正常返回5条
- **来源**：a-stock-data V3.1 CHANGELOG 已记录此修复，但代码里未严格对齐

#### Bug 2：announcementTime 类型
- **问题**：`announcementTime` 返回 `int`（如 `1778169600000`），不是字符串
- **错误**：直接 `[:10]` 切片 → TypeError
- **修复**：`_ts_to_date(ts)` 函数，毫秒→`YYYY-MM-DD`

#### Bug 3：资金流单位误用
- **问题**：push2 返回的分钟增量单位是**元**，每根K线是该分钟净流入增量
- **错误**：先除以10000再累加 → 数值正确但步骤多余
- **正确**：保留元精度累加，最终汇总时统一换算（`main_net_yuan`字段名，避免歧义）
- **教训**：100根分钟K线累加 = 全天总量，茅台全天约 -360亿元 = -3.6亿万元，数值本身正常

#### Bug 4：东财 datacenter 盘后偶发超时
- **问题**：Azure → datacenter-web.eastmoney.com 盘后偶发 ReadTimeout
- **修复**：`eastmoney_datacenter()` 加 3 次自动重试（间隔 2s/4s/6s）

#### Bug 5：腾讯财经字段索引误用（高频踩坑）
- **索引43**：振幅%（非PB！）
- **索引46**：PB（市净率）
- 网上大量教程写错，实测校准后写入代码注释

#### 数据单位统一规范
- 所有金额字段：统一为**万元**（`*_wan` 后缀）或**元**（`*_yuan` 后缀，需汇总时换算）
- 市值：腾讯返回亿元（`mcap_yi`），东财返回元（除以 1e8 转亿）
- 东财 PE/PB 字段放大了100倍（f9/f23），需除以100

---

### a-stock-data 中未引入的部分及原因

| 模块 | 未引入原因 |
|------|-----------|
| mootdx K线（前复权）| mootdx 实测不支持前复权，GARP 动量因子走 baostock（冻结）|
| mootdx F10/财报37字段 | 行业字段覆盖率 <5%，财务深度不如 baostock |
| 新浪财报三表 | 接口失效（`__ERROR:3`），废弃，由 baostock 财务接口承担 |
| iwencai NL搜索 | 需 API Key，暂未配置，妙想 MX-FinSearch 已覆盖 |
| 同花顺北向资金 | 已有妙想覆盖，未额外接入 |
| 百度股市通K线+MA | 作为 mootdx 备选，实际使用腾讯财经 |

---

### 替换关系总结

| 原有方式 | 新方式 | 状态 |
|---------|--------|------|
| Tavily 爬取财联社 | cls.cn 直连 HTTP | ✅ 已替换，稳定性↑ |
| Tavily 抓资金流 | 东财 push2 HTTP | ✅ 已替换，精度↑（分钟级）|
| 无（缺失）| 龙虎榜（GARP Layer4新维度）| ✅ 新增 |
| 无（缺失）| 限售解禁日历（风险层）| ✅ 新增 |
| 无（缺失）| 巨潮公告直连 | ✅ 新增 |
| MX-StockPick 基础行情 | 腾讯财经（PE/PB/估值）| ✅ 并联补强，MX保留 |
| MX-FinSearch 东财研报 | 东财 reportapi | ✅ 并联对比，MX保留 |
| 新浪三表（财报）| ~~废弃~~ | ❌ 接口失效，由baostock承担 |
| thsdk big_order_flow | 东财 push2 | ⚠️ thsdk需重新鉴权，暂由push2承接 |
| baostock（历史K线）| baostock（不变）| 🔒 冻结，不迁移 |
| baostock（财务增速）| baostock（不变）| 🔒 冻结，不迁移 |

---

### 1. 数据链路架构升级（L1-L7）

**核心原则：并联补强，不替换妙想/MX-Skill 任何模块。**

新增补强层：
- **东财 datacenter 直连**：龙虎榜（RPT_DAILYBILLBOARD_DETAILSNEW）、全市场龙虎榜、限售解禁（RPT_LIFT_STAGE）、大宗交易、股东户数
- **财联社 cls.cn 直连**：替代不稳定的 Tavily 爬取，含关联股票代码字段
- **巨潮 cninfo 直连**：全量公告，orgId 格式 `gssh0{code}`（注意加0）
- **腾讯财经 qt.gtimg.cn**：PE/PB/市值/涨跌停/量比（索引46=PB，索引43=振幅非PB）

权威总览文档：`docs/data-pipeline-overview.md`

---

### 2. 实测风险验证结论（gpt-5.2-codex，2026-05-21）

详见：`docs/migration-risk-validation.md`

**🔒 两条永久冻结（禁止迁移）：**

| 数据源 | 用途 | 冻结原因 |
|--------|------|---------|
| baostock `adjustflag=2` | GARP M动量因子前复权K线 | mootdx 实测不支持前复权 |
| baostock `query_profit/growth/balance_data` | GARP G增长因子多期YOY增速 | 新浪三表接口已失效+历史深度不足 |

**废弃：**
- 新浪财经三表（`__ERROR:3 Service not valid`）
- 财联社 Tavily 爬取（已被 cls.cn 直连替代）

---

### 3. push2 盘后静默机制

**问题根源**：东财盘后将 push2.eastmoney.com 重定向至 push2delay.eastmoney.com，Azure 境外 IP 访问超时。无法在代码层修复（服务器架构设计）。

**解决方案**：`is_trading_hours()` 注入所有 push2/baostock 调用，盘后自动跳过，彻底消除超时 warning。

baostock TCP 盘后同样不可用（与 mootdx 一致）。

---

### 4. 全市场预筛选 Phase 1（pre_filter.py）

**效果**：5579 只 → 426 只，压缩 92%，耗时 41s。

**筛选逻辑**（有意不做行业硬切）：
- 市值 ≥ 100亿（过滤微盘）
- PE 8-120（剔除亏损和极端泡沫，保留高成长赛道）
- 换手率 ≥ 1.5%（确保流动性）
- PB ≥ 3.0（护城河代理指标）

**行业过滤决策**：不做硬切，原因是证监会行业分类会系统性错杀强赛道标的（万华化学=化学制品行业代码19，但护城河极强，CR3=90%的MDI寡头）。行业维度通过赛道质量评分嵌入 G 因子权重调节。

---

### 5. auto_garp_score() 五因子评分

**关键设计**：
- 动态权重矩阵（5种市场状态，与 market-regime.md 完全对齐）
- 自动拉取：PE/PB/资金流/龙虎榜/解禁/财联社（盘中）
- 手动传入：ROE/增速/毛利率等财务字段（来自 baostock 或 MX-Data）
- MX-StockPick 并联交叉验证：方向一致 +3分，背离触发人工复核
- R < 90 强制输出风险披露
- 一票否决：立案调查/ST/退市/财务造假 → 总分归零

**验证（茅台 neutral）**：`G=50 Q=100 V=25 M=57 R=90 → 68.9分 🥈白银`（符合高质量+PEG=2.36超贵的真实情况）

---

### 6. 赛道质量评分（score_sector_quality）

不做行业硬过滤，改为**量化赛道质量分**嵌入 G 因子：

| 维度 | 说明 |
|------|------|
| CR3 集中度 | 行业前三名市占率，越高=护城河越强 |
| 供需结构 | tight/balanced/oversupply |
| 产品价格趋势 | 近12个月，rising=正向 |
| 护城河类型 | tech/scale/brand/resource/weak |
| 大宗周期位置 | early/mid/late/peak（周期股专用）|

G 因子修正：赛道<43分→×0.6，赛道≥70分→×1.1。

万华化学示例（CR3=90% + 供需偏紧 + 价格上行 + 技术壁垒 + 周期中期）= 100分，G因子获得 10% 加成。

---

### 7. Phase 2 baostock 财务自动填充（baostock_financial.py）

实现字段：
- G 因子：EPS CAGR（3年平均YOY）、营收CAGR
- Q 因子：ROE（含3年趋势）、毛利率（gpMargin）、资产负债率
- M 因子：6M/1M 超额收益（前复权 adjustflag=2，相对沪深300）

**⚠️ 待盘中验证**：baostock TCP 盘后不可用。验证命令：
```bash
python3 data/baostock_financial.py  # 需在 09:30-15:00 北京时间运行
```

---

### 8. 股票代码核验教训

**问题**：用户提供"天孚通信 688629"，未核验直接使用，实际 688629 是华丰科技。

**正确做法**：任何评分分析任务，先通过 `tencent_quote()` 回查名称与用户输入做比对，名称不匹配时停止并确认。

天孚通信正确代码：**300394**（通过 sina 搜索 API 确认）。

---

### Git 提交记录（今日，11个commit）

```
c82f79a fix: baostock_financial.py 盘后静默 + import路径修复
b677830 feat: Phase 2 — baostock 财务数据自动填充
a362792 feat: 赛道质量评分 + batch_garp_score + push2盘后静默
1d61f10 feat: 新增 pre_filter.py — GARP 全市场预筛选 Phase 1
b3f6583 docs: 全量更新数据链路文档 — 补强后 L1-L7 七层架构现状
2a70e64 feat: 新增 auto_garp_score() — GARP 五因子 AI 自动评分轻量版
13d1aa2 feat: 新增 PE/PB 双源交叉校验 + 腾讯财经/东财基础信息函数
db60f3d docs: 更新迁移风险验证报告 — 确认两条 baostock 冻结决策
aa6e901 docs: 数据链路迁移风险验证报告 — gpt-5.2-codex 实测
b8e0942 fix: a_stock_supplement.py 数据链路验证修复
69574d6 feat: 新增 a_stock_supplement.py — GARP 数据链路补强模块 v1.0
```
