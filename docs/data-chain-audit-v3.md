# GARP v3.0 数据链路审核报告

生成时间：2026-06-14 UTC  
执行方式：按要求创建 `PROMPT.md` 并运行 Ralph 3 轮：

```bash
ralph --prompt-file PROMPT.md --agent codex --model github-copilot/gpt-5.5 --max-iterations 3 --completion-promise "DATA_AUDIT_COMPLETE" --allow-all
```

> 注意：Ralph 3 轮均已执行，但 Codex CLI 在本机缺少 OpenAI/Copilot 认证，三轮均返回 `401 Unauthorized`，未产生有效智能体修改。后续审核与修复由本次 subagent 直接完成。

## 审核结论

### 1. `data/pre_filter.py`

| 检查项 | 结论 |
|---|---|
| 行业白名单包含 10/11/13/14/17/18/22/23 | PASS，已覆盖 AI 底层材料/先进制造 |
| `apply_dynamic_filter(..., pe_max_moat=200)` | PASS，函数参数已存在 |
| `run_pre_filter` 调用传入 `pe_max_moat=200` | PASS，调用处显式传入 |

### 2. `data/a_stock_supplement.py`

| 检查项 | 结论 |
|---|---|
| `_score_m()` 三层 35/35/30 | PASS，价格动量 35% + 资金流 35% + 产业链传导 30% |
| `north_flow_slope` 参数 | PASS，`_score_m()` 与 `auto_garp_score()` 已接入 |
| `get_north_flow_slope()` 数据函数 | FIXED，本次新增东财 HTTP `kamt.kline/get` 轻量函数，返回北向 20 日净流入斜率（亿元/天）；失败返回 `None`，评分回落主力资金信号 |
| 产业链传导 `industry_chain_score` | PASS/SKELETON，支持外部传入；缺失时回落研报评级趋势兼容模式 |
| 质量稀缺性评分 `_score_q()` | FIXED/PARTIAL，本次补充财务质量 60% + 稀缺性 40% skeleton，并对缺失子项输出 `MANUAL_REQUIRED` |

新增 `_score_q()` 稀缺性三子项接口：
- `domestic_substitution_slope`：国产替代/市占率提升斜率；缺失标注 `MANUAL_REQUIRED`。
- `replacement_cost_to_mcap`：重置成本/市值比；缺失标注 `MANUAL_REQUIRED`。
- `customer_irreplaceability`：客户切换成本/不可替代性；缺失标注 `MANUAL_REQUIRED`。
- `scarcity_score`：允许外部人工打分直接传入。

### 3. `data/baostock_financial.py`

| 检查项 | 结论 |
|---|---|
| baostock K 线是否显式 `adjustflag="2"` | PASS，baostock 分支 `query_history_k_data_plus(..., adjustflag="2")` 已冻结标注 |
| 当前默认数据源是否完全满足 v3.0 | MANUAL_REQUIRED |

说明：当前 `DATA_SOURCE="eastmoney"`，K 线实际走 yfinance `auto_adjust=True` / 东财替代链路，而不是 baostock TCP 9898。代码保留 baostock `adjustflag="2"` 分支，但 v3.0 若严格要求 baostock 官方前复权，需要人工解封/验证 Azure 到 baostock TCP 9898 后切换 `DATA_SOURCE="baostock"`。

### 4. 市场状态判断 / 状态 5b

| 检查项 | 结论 |
|---|---|
| 文档 5b 过热/泡沫预警可被代码读取 | FIXED |
| 触发条件 | 支持 `PE分位 > 90% AND ERP < 0.5%`，并兼容 `broad_index_1m_return_pct` |

本次新增接口：
- `is_overheat_bubble_warning(pe_percentile, erp_pct, broad_index_1m_return_pct=None, require_index_surge=False)`
- `detect_market_regime(...)`
- `auto_garp_score()` 可通过 `pe_percentile` / `erp_pct` / `broad_index_1m_return_pct` 自动切换到 `bubble` 权重。

## 发现的数据缺口

1. **北向资金斜率历史口径仍需实盘验证**：已实现东财 HTTP 轻量函数，但东财字段 schema 可能变化；失败回落主力资金流。
2. **产业链传导动量数据源未自动化**：`industry_chain_score` 仅支持外部传入；下游 CAPEX/招标额、海关高频、调研关键词频率尚未自动接入。`MANUAL_REQUIRED`。
3. **稀缺性三子指标需要人工/外部产业数据**：国产替代率、重置成本、客户不可替代性无法从当前免费 HTTP 链路稳定自动获取；已加接口与缺失标注。`MANUAL_REQUIRED`。
4. **baostock 官方前复权链路未作为默认源**：baostock 分支满足 `adjustflag="2"`，但默认仍是 Eastmoney/yfinance 替代源。严格 v3.0 需人工处理 Azure TCP 9898 后切回。`MANUAL_REQUIRED`。
5. **市场状态四维指标采集未全自动**：判断函数已具备，但 PE 分位、ERP、波动率、北向 10 日流入等市场级输入仍需上游任务提供。`MANUAL_REQUIRED`。

## 验证

已运行：

```bash
python3 -m py_compile data/pre_filter.py data/a_stock_supplement.py data/baostock_financial.py
```

结果：通过。
