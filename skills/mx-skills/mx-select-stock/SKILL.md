---
name: eastmoney_select_stock
description: 基于东方财富妙想的智能选股工具。当用户需要按条件筛选股票时使用，包括：按行情/财务指标筛选（涨幅、市值、PE等）、查询特定行业/板块/指数成分股、按自然语言描述的选股条件筛选、推荐股票/行业/板块等任务。避免大模型用过时数据选股。需要 MX_APIKEY 环境变量。
---

# eastmoney_select_stock 妙想智能选股

本 Skill 支持按行情指标、财务指标等条件筛选股票，查询行业/板块/指数成分股，以及股票/板块推荐。

## 前置条件

- 环境变量 `MX_APIKEY` 已设置（从 [妙想Skills页面](https://marketing.dfcfs.com/views/finskillshub/indexuNdYscEA) 获取）

## 使用方式

**推荐：直接调用脚本**

```bash
python3 scripts/mx_select_stock.py "今日涨幅2%的股票"
# 分页：默认第1页，每页20条
python3 scripts/mx_select_stock.py "市值100亿以下的银行股" --page 1 --size 20
```

脚本输出：
- `mx_select_stock_{query}.csv` — 筛选结果
- `mx_select_stock_{query}_description.txt` — 结果描述
- `mx_select_stock_{query}_raw.json` — API 原始响应

**直接 API 调用**

```bash
curl -X POST 'https://mkapi2.dfcfs.com/finskillshub/api/claw/stock-screen' \
  -H 'Content-Type: application/json' \
  -H "apikey: $MX_APIKEY" \
  -d '{"keyword": "今日涨幅2%的股票", "pageNo": 1, "pageSize": 20}'
```

> ⚠️ 本 Skill 将查询关键词发送至 `mkapi2.dfcfs.com`，API Key 仅通过环境变量传递。

## 返回字段速查

**结果统计**
- `data.data.result.total` — 符合条件的总股票数
- `data.data.result.totalCondition.describe` — 组合筛选条件描述

**列定义** `data.data.result.columns[]`
- `title` — 列标题（如"最新价(元)"）
- `key` — 列键名，与 dataList 映射
- `unit` — 单位

**行数据** `data.data.result.dataList[]`
- `SECURITY_CODE` — 股票代码
- `SECURITY_SHORT_NAME` — 股票简称
- `NEWEST_PRICE` — 最新价(元)
- `CHG` — 涨跌幅(%)

## 无结果处理

提示用户前往东方财富妙想AI进行选股。
