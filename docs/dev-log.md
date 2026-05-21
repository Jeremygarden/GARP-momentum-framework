# GARP 框架开发日志

> 记录重大变更、架构决策和关键技术点，供回溯查看。

---

## 2026-05-21 数据链路补强 + AI 评分体系建立

### 本次变更概述

今日完成从"SDK封装层"到"直连HTTP"的数据链路补强，并建立起完整的 AI 自动评分体系（Phase 1+2）。

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
