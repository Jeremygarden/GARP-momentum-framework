# GARP Final Review - Issues Log

## 已修复 (2026-06-14)

### Issue #1: V因子PB>10惩罚对稀缺性模型股票双重扣分
- **严重度**: 中
- **文件**: `data/a_stock_supplement.py` line ~1580
- **问题**: `_score_v()` 末尾对所有 PB>10 的股票扣5分，但稀缺性溢价模型中高PB是护城河特征（PB≥5是模型入口条件），不应再被惩罚
- **影响**: 中际旭创(PB=37)、三环集团(PB=11.3)、生益科技(PB=23) V因子均被多扣5分
- **修复**: 添加 `not use_scarcity` 条件，仅对PEG轨股票应用PB惩罚

### Issue #2: CLS财联社API 404错误刷屏日志
- **严重度**: 低
- **文件**: `data/a_stock_supplement.py` `get_cls_telegraph()`
- **问题**: CLS nodeapi/telegraphList 返回404 HTML，json解析失败打印 `[ERROR]` 刷屏
- **影响**: 每次auto_garp_score调用打印一行ERROR，不影响功能
- **修复**: 非200状态码时静默返回空列表，不再打印错误

---

## 未修复 - 待办

### Issue #3: CLS API端点迁移
- **严重度**: 中
- **发现**: 2026-06-14
- **详情**: `https://www.cls.cn/nodeapi/telegraphList` 返回404。替代端点 `v1/roll/get_roll_list` 需签名认证，`v3/roll/get_roll_list` 返回"小财正在加载中"
- **影响**: R因子的CLS新闻告警子组件完全失效（返回空列表），无法捕捉即时新闻风险
- **降级策略**: R因子仍有龙虎榜+限售解禁两个独立子组件工作，CLS子组件graceful返回空
- **TODO**: 需要：(1) 抓包CLS新版API签名方式，或 (2) 替换为东财资讯/雪球舆情接口

### Issue #4: consensus_eps_growth始终为None
- **严重度**: 中
- **详情**: 东财ZYZBAjaxNew接口只返回历史财务数据，不包含券商一致预期EPS增速
- **影响**: V因子PEG计算只能用历史3年CAGR均值作为G，而非更准确的前瞻预期增速
- **典型案例**: 许继电气(历史CAGR=7.58%，但券商预期加速)→PEG=3.98被过度惩罚
- **TODO**: 接入东财 `reportapi.eastmoney.com` 的一致预期EPS字段（已有 `get_eastmoney_reports()` 函数，但尚未提取consensus）

### Issue #5: V因子稀缺性模型缺失scarcity_tier输入
- **严重度**: 中
- **详情**: 当 `scarcity_tier=None` 且 `industry_avg_pe=None` 时，稀缺性模型使用当前PE作为base_pe，premium=0%→ratio=1.0→所有高PB科技股V=78
- **影响**: 中际旭创/三环集团/生益科技 V因子无差异化（全是78分）
- **设计意图**: 不伪造数据，无确切稀缺性信息时给中性偏好分数
- **TODO**: 在GARP Bitable/知识库中为核心池标的维护scarcity_tier字段

### Issue #6: 东财财务接口偶发超时
- **严重度**: 低
- **详情**: `emweb.securities.eastmoney.com` 偶尔read timeout（10s），导致个别标的G/Q回落中性分
- **影响**: 本次测试生益科技600183触发一次超时
- **TODO**: timeout从10s增加到20s，或添加1次重试

---

## 设计权衡记录

### 为什么scarcity_tier不自动填充？
稀缺性是主观判断（"全球唯一"vs"2-3家"），无法从公开财务数据自动推导。强制自动化会导致错误标注。正确做法是人工或知识库维护+周期性复核。

### 为什么CLS失效不算高严重度？
R因子有3个独立子组件：龙虎榜机构席位 + 限售解禁日历 + CLS新闻告警。CLS失效只影响"即时新闻风险"这一个维度，另外两个子组件仍正常工作，且新闻风险的定性较弱（关键词匹配不够精确）。

### 为什么许继电气得分远低于预期？
许继电气历史3年EPS CAGR仅7.58%，对GARP框架而言这就是"低成长"（G=50）。框架设计理念是"以合理价格买入成长"，低成长+高PE=被框架边缘化。如需捕获"未来加速型"标的，必须接入consensus_eps_growth前瞻数据。
